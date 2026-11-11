"""完整 KS4 单任务；导入、文件预读和读取器创建在计时之外。"""

import random
import sys
import time
from pathlib import Path

from experiment import Budget, configure, environment, load, save, sorting_reader, warm


def run(job):
    config, kind = job["config"], job["kind"]
    configure(config["sorting_cpus"], config["numeric_threads"])
    import numpy as np
    import torch
    from kilosort import run_kilosort
    from kilosort.io import BinaryRWFile, load_probe
    from threadpoolctl import threadpool_limits

    torch.set_num_threads(config["numeric_threads"])
    random.seed(config["seed"])
    np.random.seed(config["seed"])
    torch.manual_seed(config["seed"])
    folder = Path(job["result"]).parent
    source = config[{"raw": "raw", "rans": "archive", "mtscomp": "mtscomp"}[kind]]
    budget = Budget(0 if job["operation"] == "preflight" else job["rate"])
    if job["operation"] == "preflight":
        raw = np.memmap(config["raw"], mode="r", dtype="<i2", shape=(config["samples"], config["channels"]))
        try:
            with sorting_reader(config, kind, budget) as reader:
                block, samples = config["block_samples"], config["samples"]
                for start, stop, step in [
                    (0, min(samples, block + 61), 1),
                    (max(0, block - 61), min(samples, 2 * block + 61), 1),
                    (0, min(samples, 3 * block + 61), 101),
                    (max(0, samples - block - 1), samples, 1),
                ]:
                    assert np.array_equal(reader[start:stop:step], raw[start:stop:step])
                options = dict(
                    n_chan_bin=config["channels"],
                    NT=config["batch_samples"],
                    nt=61,
                    device=torch.device("cpu"),
                )
                original = BinaryRWFile(config["raw"], **options)
                adapted = BinaryRWFile(source, file_object=reader, **options)
                for index in sorted({0, int(original.n_batches) - 1}):
                    assert torch.equal(
                        original.padded_batch_to_torch(index), adapted.padded_batch_to_torch(index)
                    )
                # Fresh reader checks metering independently of speculative reads.
            with sorting_reader(config, kind, budget) as reader:
                budget.reset()
                reader[0:100]
                if kind == "rans":
                    for future in reader._online_frames.values():
                        future.result()
                    assert budget.bytes == reader.statistics()["bytes_read"]
                elif kind == "mtscomp":
                    assert budget.bytes == int(reader.chunk_offsets[1] - reader.chunk_offsets[0])
                before = budget.bytes
                reader[0:100]
                assert (
                    (budget.bytes == before)
                    if kind != "raw"
                    else (budget.bytes == before + 100 * config["channels"] * 2)
                )
            return dict(
                status="success",
                kind=kind,
                exact_windows=True,
                exact_padded_batches=True,
                metering_verified=True,
                input_read=budget.metrics(),
            )
        finally:
            raw._mmap.close()
    if not torch.cuda.is_available():
        raise RuntimeError("完整专利实验需要 CUDA GPU；预检可在 CPU 上运行")
    device = torch.device("cuda:0")
    torch.cuda.manual_seed_all(config["seed"])
    torch.ones(1, device=device).sum().item()
    torch.cuda.synchronize(device)
    probe = load_probe(config["probe"])
    paths = [source] + ([str(Path(source).with_suffix(".ch"))] if kind == "mtscomp" else [])
    prewarm = warm(paths)
    settings = dict(
        n_chan_bin=config["channels"],
        fs=config["fs"],
        batch_size=config["batch_samples"],
        cluster_init_seed=config["seed"],
    )
    destination = folder / "sorting"
    if destination.exists():
        raise FileExistsError(destination)
    with threadpool_limits(limits=config["numeric_threads"]):
        with sorting_reader(config, kind, budget) as reader:
            budget.reset()
            started = time.perf_counter()
            result = run_kilosort(
                settings=settings,
                probe=probe,
                filename=Path(source),
                file_object=reader,
                results_dir=destination,
                data_dtype="int16",
                device=device,
                save_preprocessed_copy=False,
                torch_thread_lim=config["numeric_threads"],
            )
            torch.cuda.synchronize(device)
            seconds = time.perf_counter() - started
            at_stop = budget.metrics()
            save(folder / "effective_settings.json", result[0]["settings"])
        after_close = budget.metrics()
    times = np.load(destination / "spike_times.npy").ravel()
    labels = np.load(destination / "spike_clusters.npy").ravel()
    assert len(times) == len(labels) > 0 and times.min() >= 0 and times.max() < config["samples"]
    return dict(
        status="success",
        kind=kind,
        bandwidth_MB_s=job["rate"],
        seconds=seconds,
        batches=int(result[0]["Nbatches"]),
        units=len(np.unique(labels)),
        spikes=len(times),
        input_read=at_stop,
        input_after_close=after_close,
        prewarm=prewarm,
        environment=environment(config),
        gpu=torch.cuda.get_device_name(device),
    )


if __name__ == "__main__":
    job = load(sys.argv[1])
    save(job["result"], run(job))
