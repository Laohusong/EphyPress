"""Exercise real hooks, cross-process budgets and KS4-style input windows."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from benchmark import HERE, load, save


def child(job_path, worker):
    import bandwidth_adapter
    job = load(job_path)
    folder = Path(job['folder'])
    assert not any(name == 'chronosort' or name.startswith('chronosort.') for name in sys.modules)
    (folder / f'ready_{worker}').touch()
    limit = time.monotonic() + 60
    while not (folder / 'go').exists():
        if time.monotonic() > limit:
            raise TimeoutError('Preflight start barrier')
        time.sleep(.005)
    started = time.perf_counter()
    raw = bandwidth_adapter.RawArray(job['raw'])
    assert raw[:6000].shape == (6000, 384)
    with (folder / 'run' / f'out_{worker}.bin').open('wb') as f:
        f.write(bytes(4000000))
    with (folder / 'run/source.bin').open('rb') as f:
        assert len(f.read()) == 4000000
    ended = time.perf_counter()
    save(folder / f'worker_{worker}.json', dict(start=started, end=ended))


def fidelity(job_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import bandwidth_adapter
    import io_budget
    import numpy as np
    import torch

    import ephypress as ep
    job = load(job_path)
    folder = Path(job['folder'])
    raw = bandwidth_adapter.RawArray(job['raw'])
    windows = [(0, 60061), (59939, 120061), (119939, 120123)]
    with ep.open_recording(job['archive'], reader_mode='blocks') as reader:
        for lo, hi in windows:
            assert np.array_equal(raw[lo:hi], reader[lo:hi])
        assert np.array_equal(raw[59939:60100:25, ::3], reader[59939:60100:25, ::3])
    run = folder / 'results'
    run.mkdir()
    values = np.arange(4096, dtype=np.float32).reshape(256, 16)
    np.save(run / 'array.npy', values)
    mapped = np.load(run / 'array.npy', mmap_mode='r+')
    assert isinstance(mapped, io_budget.MappedArray)
    assert np.array_equal(mapped[10:20], values[10:20])
    mapped[10:20] = values[10:20] + 1
    assert np.array_equal(mapped[10:20], values[10:20] + 1)
    mapped.flush()
    torch.save(torch.arange(100), run / 'tensor.pt')
    assert torch.equal(torch.load(run / 'tensor.pt', weights_only=True), torch.arange(100))
    stats = io_budget.metrics(job)
    assert all(stats[k]['bytes'] > 0 for k in ['input_read', 'stream_read', 'stream_write', 'mapped_read', 'mapped_write'])
    # Synchronized read and write reservations must overlap: separate budgets.
    barrier = threading.Barrier(2)
    def reserve(category):
        barrier.wait()
        start = time.perf_counter()
        deadline = io_budget.reserve(32000000, category)
        io_budget.deliver(deadline)
        return dict(start=start, deadline=deadline, end=time.perf_counter())
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(reserve, 'input_read')
        b = pool.submit(reserve, 'stream_write')
        a, b = a.result(), b.result()
    overlap = min(a['deadline'], b['deadline']) - max(a['start'], b['start'])
    assert overlap > .5, (a, b)
    save(folder / 'fidelity.json', dict(status='passed', padded_windows=windows,
          stride25_exact=True, mapped_and_torch_io=True, independent_budget_overlap_seconds=overlap,
          metrics=stats, no_chronosort_dependency=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child')
    parser.add_argument('--worker', type=int)
    parser.add_argument('--fidelity')
    args = parser.parse_args()
    if args.child:
        child(args.child, args.worker)
        return
    if args.fidelity:
        fidelity(args.fidelity)
        return
    if os.name != 'nt':
        raise RuntimeError('Windows IPC preflight only')
    if args.output is None:
        parser.error('--output is required')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    import numpy as np

    import ephypress as ep
    samples = 120123
    raw = out / 'input.dat'
    archive = out / 'input.ep'
    signal = (np.arange(samples, dtype=np.int32)[:, None] * 7 + np.arange(384)[None, :] * 19).astype('<i2')
    signal.tofile(raw)
    del signal
    ep.compress(raw, archive, 384, workers=2)
    sys.path.insert(0, str(HERE / 'runtime'))
    import bandwidth_adapter
    import io_budget
    def initialize(folder, condition):
        folder.mkdir()
        (folder / 'run').mkdir()
        (folder / 'run/source.bin').write_bytes(bytes(4000000))
        job = dict(sorter='ks4', raw=str(raw), archive=str(archive), folder=str(folder), rate=50,
                   bandwidth_MB_s=50, io_condition=condition, probe=str(HERE / 'fixture/ks4_probe.json'),
                   source_root=str(folder / 'unused/src'), limiter_state=str(folder / 'input.bin'), io_state=str(folder / 'io.bin'))
        jp = folder / 'job.json'
        save(jp, job)
        bandwidth_adapter.initialize(job)
        io_budget.initialize(job)
        env = dict(os.environ, BANDWIDTH_JOB=str(jp), ALL_IO_JOB=str(jp), PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=os.pathsep.join([str(HERE / 'runtime'), str(HERE)]))
        return job, jp, env
    results = []
    for condition in ['input_read_only', 'all_read_write']:
        folder = out / condition
        job, jp, env = initialize(folder, condition)
        children = [subprocess.Popen([sys.executable, str(__file__), '--child', str(jp), '--worker', str(i)],
                        env=env, creationflags=subprocess.CREATE_NO_WINDOW) for i in range(4)]
        deadline = time.monotonic() + 60
        while not all((folder / f'ready_{i}').exists() for i in range(4)):
            if time.monotonic() > deadline or any(p.poll() is not None for p in children):
                raise RuntimeError('Preflight process did not reach barrier')
            time.sleep(.05)
        (folder / 'go').touch()
        assert all(p.wait(timeout=30) == 0 for p in children)
        records = [load(folder / f'worker_{i}.json') for i in range(4)]
        elapsed = max(r['end'] for r in records) - min(r['start'] for r in records)
        stats = io_budget.metrics(job)
        assert stats['input_read']['bytes'] == 18432000
        assert stats['stream_read']['bytes'] == 16000000
        assert stats['stream_write']['bytes'] == 16000000
        minimum = (18432000 + (16000000 if condition == 'all_read_write' else 0)) / 50e6
        assert elapsed >= minimum - .025
        assert elapsed < minimum + 3
        results.append(dict(condition=condition, seconds=elapsed, minimum_seconds=minimum, metrics=stats))
        print('PASS shared budgets', condition, round(elapsed, 3), flush=True)
    job, jp, env = initialize(out / 'fidelity', 'all_read_write')
    subprocess.run([sys.executable, str(__file__), '--fidelity', str(jp)], env=env,
                   creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=60)
    save(out / 'preflight.json', dict(status='passed', multiprocess=results, fidelity=load(out / 'fidelity/fidelity.json')))
    print(out / 'preflight.json', flush=True)


if __name__ == '__main__':
    main()
