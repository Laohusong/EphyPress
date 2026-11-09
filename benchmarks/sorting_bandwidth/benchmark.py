"""Prepare, validate and run the Windows logical-bandwidth sorting benchmark.

No product source edits. KS4 runs without importing ChronoSort. ChronoSort uses
its native 62000+1768+1768 defaults; zero-context profiles are not supported.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RATES = [50, 100, 200, 500, 1000, 2000, 5000]
CONDITIONS = ['input_read_only', 'all_read_write']


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding='utf-8')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def environment():
    names = ['ephypress', 'kilosort', 'torch', 'numpy', 'scipy', 'numba', 'threadpoolctl']
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total',
                          '--format=csv,noheader'], capture_output=True, text=True, check=True).stdout.strip()
    return dict(python=sys.version, executable=sys.executable, platform=platform.platform(), packages=versions, gpu=gpu)


def prepare(args):
    import numpy as np

    import ephypress as ep
    dest = args.output.resolve()
    dest.mkdir(parents=True, exist_ok=False)
    source = args.source_raw.resolve()
    samples = round(args.duration * args.fs)
    length = samples * args.channels * 2
    if samples < 1 or source.stat().st_size < length:
        raise ValueError('Source is shorter than the requested positive duration')
    raw, archive = dest / 'recording.dat', dest / 'recording.ep'
    h = hashlib.sha256()
    with source.open('rb') as src, raw.open('xb') as dst:
        remaining = length
        while remaining:
            chunk = src.read(min(8 * 1024**2, remaining))
            if not chunk:
                raise OSError('Short source read')
            dst.write(chunk)
            h.update(chunk)
            remaining -= len(chunk)
    compression = ep.compress(raw, archive, args.channels, sampling_frequency=args.fs,
                              block_samples=60000, workers=args.workers,
                              prediction='temporal', entropy_backend='fse', zstd_level=3)
    verification = ep.verify(archive, original=raw, reader_mode='blocks')
    probe = dest / 'ks4_probe.json'
    shutil.copy2(args.probe, probe)
    # Exact historical ChronoSort geometry is available as a text fixture.
    chrono_probe = None
    if args.chrono_probe:
        chrono_probe = dest / 'probe.npy'
        if args.chrono_probe.suffix == '.json':
            geometry = load(args.chrono_probe)
            dtype = np.dtype([tuple(v) for v in geometry['dtype']])
            np.save(chrono_probe, np.array([tuple(v) for v in geometry['rows']], dtype=dtype))
        else:
            shutil.copy2(args.chrono_probe, chrono_probe)
    manifest = dict(raw=str(raw), archive=str(archive), probe=str(probe), chrono_probe=str(chrono_probe) if chrono_probe else None,
                    channels=args.channels, fs=args.fs, samples=samples, duration_seconds=samples / args.fs,
                    source=str(source), sha256=h.hexdigest(), raw_bytes=length, archive_sha256=sha(archive),
                    archive_bytes=archive.stat().st_size, compression=compression, verification=verification,
                    probe_sha256=sha(probe))
    save(dest / 'dataset.json', manifest)
    print(dest / 'dataset.json', flush=True)


def register(args):
    """Register existing fixtures, with a full decode and raw comparison."""
    import ephypress as ep
    dest = args.output.resolve()
    dest.mkdir(parents=True, exist_ok=False)
    raw, archive = args.raw.resolve(), args.archive.resolve()
    meta = ep.info(archive)
    with ep.open_recording(archive, prefetch=False, reader_mode='blocks') as reader:
        samples, channels = reader.shape
    verification = ep.verify(archive, original=raw, reader_mode='blocks')
    probe = dest / 'ks4_probe.json'
    shutil.copy2(args.probe, probe)
    chrono_probe = None
    if args.chrono_probe:
        chrono_probe = dest / 'probe.npy'
        shutil.copy2(args.chrono_probe, chrono_probe)
    save(dest / 'dataset.json', dict(raw=str(raw), archive=str(archive), probe=str(probe),
         chrono_probe=str(chrono_probe) if chrono_probe else None, samples=samples, channels=channels,
         fs=meta['sampling_frequency'], duration_seconds=samples / meta['sampling_frequency'],
         sha256=sha(raw), raw_bytes=raw.stat().st_size, archive_bytes=archive.stat().st_size,
         archive_sha256=sha(archive), verification=verification, probe_sha256=sha(probe)))
    print(dest / 'dataset.json', flush=True)


def source_manifest(root):
    root = Path(root).resolve()
    return {str(p.relative_to(root)).replace('\\', '/'): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def sweep(args):
    if os.name != 'nt':
        raise RuntimeError('These historical IPC/I/O hooks require Windows; Linux is not validated')
    dataset = load(args.data)
    for key in ['raw', 'archive', 'probe']:
        if not Path(dataset[key]).is_file():
            raise FileNotFoundError(dataset[key])
    if Path(dataset['raw']).stat().st_size != dataset['raw_bytes']:
        raise ValueError('Raw fixture size changed; re-register it')
    if Path(dataset['archive']).stat().st_size != dataset['archive_bytes']:
        raise ValueError('Archive fixture size changed; re-register it')
    if sha(dataset['raw']) != dataset['sha256'] or sha(dataset['archive']) != dataset['archive_sha256']:
        raise ValueError('Input content changed; re-register and verify the fixture')
    if sha(dataset['probe']) != dataset['probe_sha256']:
        raise ValueError('Probe changed; re-register it')
    if args.rates is None:
        args.rates = RATES
    if any(x <= 0 for x in args.rates) or len(set(args.rates)) != len(args.rates):
        raise ValueError('Rates must be unique positive decimal MB/s values')
    if args.repeats < 1:
        raise ValueError('Repeats must be positive')
    chrono_src = None
    if 'chronosort' in args.sorters:
        if dataset['channels'] != 384:
            raise ValueError('Historical shared-cache adapter is validated for 384 channels only')
        if args.chronosort_root is None or not dataset.get('chrono_probe'):
            raise ValueError('ChronoSort requires --chronosort-root and a prepared --chrono-probe')
        chrono_src = args.chronosort_root.resolve() / 'src'
        if not (chrono_src / 'chronosort/config.py').is_file():
            raise FileNotFoundError(chrono_src)
        expected = {k.replace('\\', '/'): v for k, v in load(HERE / 'fixture/source_manifest.json')['sha256'].items()}
        actual = {'src/' + k: v for k, v in source_manifest(chrono_src).items()}
        if actual != expected:
            raise ValueError('ChronoSort source differs from frozen 9bc7b8a snapshot; supply the documented historical source')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'dataset.json', dataset)
    jobs = []
    # Match historical counterbalancing: high cap first, then low to high.
    rates = ([5000] if 5000 in args.rates else []) + [x for x in args.rates if x != 5000]
    for repeat in range(1, args.repeats + 1):
        for ri, rate in enumerate(rates):
            for sorter in args.sorters:
                conditions = args.conditions if ri % 2 == 0 else args.conditions[::-1]
                for ci, condition in enumerate(conditions):
                    kinds = args.kinds if (ri + ci + repeat - 1) % 2 == 0 else args.kinds[::-1]
                    for kind in kinds:
                        name = f'{condition}_{sorter}_{kind}_{rate:04d}MBps_r{repeat}'
                        folder = out / name
                        jobs.append(dict(name=name, sorter=sorter, kind=kind, rate=rate, repeat=repeat,
                            io_condition=condition, folder=str(folder), raw=dataset['raw'], archive=dataset['archive'],
                            probe=dataset['probe'], chrono_probe=dataset.get('chrono_probe'),
                            source_root=str(chrono_src or out / 'unused_source/src'), samples=dataset['samples'],
                            channels=dataset['channels'], fs=dataset['fs'], bandwidth_MB_s=rate,
                            limiter_state=str(folder / 'input.bin'), io_state=str(folder / 'io.bin'),
                            device=args.device, seed=1, threads=8, chrono_segment=62000, chrono_padding=[1768, 1768]))
    save(out / 'jobs.json', jobs)
    save(out / 'runtime_hashes.json', source_manifest(HERE / 'runtime'))
    if args.dry_run:
        print(f'PLAN ONLY: {len(jobs)} jobs -> {out}', flush=True)
        return
    if importlib.metadata.version('ephypress') != '0.2.0':
        raise RuntimeError('This reader instrumentation is pinned to EphyPress 0.2.0')
    if 'ks4' in args.sorters and importlib.metadata.version('kilosort') != '4.1.7':
        raise RuntimeError('Reproduction requires kilosort==4.1.7')
    save(out / 'environment.json', environment())
    done = []
    for index, job in enumerate(jobs, 1):
        folder = Path(job['folder'])
        folder.mkdir()
        (folder / 'temp').mkdir()
        jp = folder / 'job.json'
        save(jp, job)
        # Initialize shared state without installing hooks in the orchestrator.
        sys.path.insert(0, str(HERE / 'runtime'))
        import bandwidth_adapter
        import io_budget
        bandwidth_adapter.initialize(job)
        io_budget.initialize(job)
        env = dict(os.environ)
        for key in ['BANDWIDTH_JOB', 'ALL_IO_JOB', 'SEGMENT_PROFILE', 'POLICY_STATS_DIR']:
            env.pop(key, None)
        env.update(BANDWIDTH_JOB=str(jp), ALL_IO_JOB=str(jp), PREFETCH_STRATEGY='shared',
                   POLICY_STATS_DIR=str(folder / 'reader_stats'), PYTHONUTF8='1', PYTHONUNBUFFERED='1',
                   PYTHONDONTWRITEBYTECODE='1', MPLBACKEND='Agg', TMP=str(folder / 'temp'), TEMP=str(folder / 'temp'))
        env['PYTHONPATH'] = os.pathsep.join([str(HERE / 'runtime'), str(HERE)] + ([str(chrono_src)] if job['sorter'] == 'chronosort' else []))
        for key in ['OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMBA_NUM_THREADS', 'NUMEXPR_NUM_THREADS']:
            env[key] = '8'
        print(f'RUN {index}/{len(jobs)} {job["name"]}', flush=True)
        with (folder / 'process.log').open('x', encoding='utf-8') as log:
            run = subprocess.run([sys.executable, '-u', str(HERE / 'worker.py'), str(jp)],
                    env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        if run.returncode:
            raise RuntimeError(f'Failed exit={run.returncode}; preserved {folder / "process.log"}')
        result = load(folder / 'result.json')
        done.append(result)
        save(out / 'results.json', done)
        print(f'DONE {result["seconds"]:.3f}s', flush=True)
    if source_manifest(HERE / 'runtime') != load(out / 'runtime_hashes.json'):
        raise RuntimeError('Runtime changed during sweep')
    if chrono_src and {'src/' + k: v for k, v in source_manifest(chrono_src).items()} != expected:
        raise RuntimeError('ChronoSort source changed during sweep')
    save(out / 'completion.json', dict(status='success', runs=len(done)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare', help='Copy a prefix, compress and verify every sample')
    prep.add_argument('--source-raw', type=Path, required=True)
    prep.add_argument('--duration', type=float, default=1800)
    prep.add_argument('--channels', type=int, default=384)
    prep.add_argument('--fs', type=float, default=30000)
    prep.add_argument('--workers', type=int, default=4)
    reg = sub.add_parser('register', help='Verify and register an existing raw/archive pair')
    reg.add_argument('--raw', type=Path, required=True)
    reg.add_argument('--archive', type=Path, required=True)
    for p in [prep, reg]:
        p.add_argument('--probe', type=Path, required=True, help='KS4 JSON probe; bundled fixture is ProbeB-specific')
        p.add_argument('--chrono-probe', type=Path)
        p.add_argument('--output', type=Path, required=True, help='New directory; existing contents are never overwritten')
    run = sub.add_parser('run', help='Run fresh serial sorting processes')
    run.add_argument('--data', type=Path, required=True, help='Prepared dataset.json')
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--sorters', nargs='+', choices=['ks4', 'chronosort'], default=['ks4'])
    run.add_argument('--chronosort-root', type=Path)
    run.add_argument('--rates', nargs='+', type=int)
    run.add_argument('--conditions', nargs='+', choices=CONDITIONS, default=CONDITIONS)
    run.add_argument('--kinds', nargs='+', choices=['raw', 'compressed'], default=['raw', 'compressed'])
    run.add_argument('--repeats', type=int, default=1)
    run.add_argument('--device', default='cuda:0')
    run.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    {'prepare': prepare, 'register': register, 'run': sweep}[args.command](args)


if __name__ == '__main__':
    main()
