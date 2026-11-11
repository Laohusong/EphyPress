"""一个全新进程执行一次编码、校验或解码测量。由 reproduce.py 调用。"""

import hashlib
import multiprocessing
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from experiment import configure, environment, load, mts_options, save, warm


class Blocks:
    def __init__(self, config, kind):
        self.kind, self.config = kind, config
        self.local, self.resources, self.lock = threading.local(), [], threading.Lock()
        if kind == "rans":
            from ephypress import info

            self.entries = info(config["archive"])["blocks"]
            self.count = len(self.entries)
        else:
            import mtscomp

            self.reader = mtscomp.Reader(**mts_options(1))
            self.reader.open(config["mtscomp"], Path(config["mtscomp"]).with_suffix(".ch"))
            self.count = self.reader.n_chunks
        expected = (config["samples"] + config["block_samples"] - 1) // config["block_samples"]
        assert self.count == expected

    def read(self, index):
        if self.kind == "rans":
            from ephypress._rans import Decoder

            if not hasattr(self.local, "decoder"):
                self.local.decoder = Decoder(self.config["archive"])
                with self.lock:
                    self.resources.append(self.local.decoder)
            offset, size, first, last, crc = self.entries[index]
            return self.local.decoder.decode(offset, size, crc, (last - first, self.config["channels"]), True)
        import mtscomp

        offset, end = self.reader.chunk_offsets[index : index + 2]
        return mtscomp.Reader.read_chunk(self.reader, index, offset, end - offset)

    def close(self):
        for reader in self.resources:
            reader.close()
        if self.kind != "rans":
            self.reader.close()


def process_ready(_):
    return os.getpid()


def process_initialize(cpus, barrier):
    configure(cpus, 1)
    import mtscomp
    import numpy

    from ephypress._native import library

    library()
    _ = mtscomp.__version__, numpy.__version__
    barrier.wait(timeout=120)


def decode_range(args):
    config, kind, first, last = args
    reader = Blocks(config, kind)
    try:
        return sum(reader.read(i).nbytes for i in range(first, last))
    finally:
        reader.close()


def decode_threads(config, kind, verify=False):
    reader = Blocks(config, kind)
    source = open(config["raw"], "rb") if verify else None
    digest, count = hashlib.sha256(), 0
    try:
        with ThreadPoolExecutor(max_workers=config["codec_workers"]) as pool:
            for first in range(0, reader.count, config["codec_workers"]):
                batch = list(
                    pool.map(reader.read, range(first, min(first + config["codec_workers"], reader.count)))
                )
                for array in batch:
                    assert array.flags.c_contiguous and array.dtype.str == "<i2"
                    count += array.nbytes
                    if source is not None:
                        payload = memoryview(array).cast("B")
                        assert source.read(len(payload)) == payload, "解码结果与原始字节不一致"
                        digest.update(payload)
                del array, batch
        if source is not None:
            assert not source.read(1) and digest.hexdigest() == config["sha256"]
    finally:
        reader.close()
        if source is not None:
            source.close()
    return count


def run(job):
    config, kind, operation = job["config"], job["kind"], job["operation"]
    configure(config["codec_cpus"], 1)
    import mtscomp
    import psutil
    from threadpoolctl import threadpool_limits

    import ephypress
    from ephypress._native import library

    library()
    paths = (
        [Path(config["archive"])]
        if kind == "rans"
        else [Path(config["mtscomp"]), Path(config["mtscomp"]).with_suffix(".ch")]
    )
    raw_bytes = config["samples"] * config["channels"] * 2
    prewarm = None
    if operation in {"threads", "processes"}:
        assert psutil.virtual_memory().available > sum(p.stat().st_size for p in paths) + 4 * 1024**3
        prewarm = warm(paths)
    with threadpool_limits(limits=1):
        started = time.perf_counter()
        if operation == "encode":
            if any(p.exists() for p in paths):
                raise FileExistsError("压缩目标已存在，请使用新实验目录")
            paths[0].parent.mkdir(parents=True, exist_ok=True)
            if kind == "rans":
                ephypress.compress(
                    config["raw"],
                    paths[0],
                    config["channels"],
                    sampling_frequency=config["fs"],
                    block_samples=config["block_samples"],
                    workers=config["codec_workers"],
                )
            else:
                options = mts_options(config["codec_workers"])
                options["chunk_duration"] = config["block_samples"] / config["fs"]
                mtscomp.compress(
                    config["raw"],
                    *paths,
                    sample_rate=config["fs"],
                    n_channels=config["channels"],
                    dtype="int16",
                    **options,
                )
            for path in paths:
                with path.open("r+b") as stream:
                    os.fsync(stream.fileno())
            count = raw_bytes
        elif operation == "processes":
            count_blocks = (config["samples"] + config["block_samples"] - 1) // config["block_samples"]
            workers = config["codec_workers"]
            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=context,
                initializer=process_initialize,
                initargs=(config["codec_cpus"], context.Barrier(workers)),
            ) as pool:
                list(pool.map(process_ready, range(workers)))
                # Process startup is outside the timer; each task opens its own decoder.
                jobs = [
                    (config, kind, i * count_blocks // workers, (i + 1) * count_blocks // workers)
                    for i in range(workers)
                ]
                started = time.perf_counter()
                count = sum(pool.map(decode_range, jobs))
                seconds = time.perf_counter() - started
        else:
            count = decode_threads(config, kind, verify=operation == "verify")
        if operation != "processes":
            seconds = time.perf_counter() - started
    assert count == raw_bytes
    size = sum(p.stat().st_size for p in paths)
    return dict(
        status="success",
        kind=kind,
        operation=operation,
        seconds=seconds,
        raw_bytes=count,
        archive_bytes=size,
        ratio=count / size,
        raw_MB_s=count / seconds / 1e6,
        exact_equal=operation == "verify",
        prewarm=prewarm,
        environment=environment(config),
    )


def summarize(folder):
    folder = Path(folder)
    records = [load(p) for p in sorted(folder.glob("*/result.json"))]
    rows, processes = [], []
    for kind in ("rans", "mtscomp"):
        selected = [r for r in records if r["kind"] == kind]
        encode = next(r for r in selected if r["operation"] == "encode")
        verified = next(r for r in selected if r["operation"] == "verify")
        for operation, target in (("threads", rows), ("processes", processes)):
            times = [r["seconds"] for r in selected if r["operation"] == operation]
            target.append(
                dict(
                    dataset="neuropixels",
                    profile="delta_ans0" if kind == "rans" else kind,
                    raw_bytes=encode["raw_bytes"],
                    archive_bytes=encode["archive_bytes"],
                    ratio=encode["ratio"],
                    encode_seconds=encode["seconds"],
                    decode_runs_s=times,
                    decode_median_s=statistics.median(times),
                    raw_MB_s=encode["raw_bytes"] / statistics.median(times) / 1e6,
                    exact_equal=verified["exact_equal"],
                )
            )
    save(
        folder.parent / "codec_comparison.json",
        dict(
            rows=rows,
            process_rows=processes,
            implementation="cleaned_production_v3",
            historical_measurement=False,
        ),
    )


if __name__ == "__main__":
    job = load(sys.argv[1])
    save(job["result"], run(job))
