"""One fresh sorting process. Instrumentation is loaded by sitecustomize."""
import random
import sys
import time
from pathlib import Path

from benchmark import load, save


def run(job):
    import bandwidth_adapter
    import io_budget
    import numpy as np
    import torch
    from threadpoolctl import threadpool_limits

    import ephypress as ep
    assert bandwidth_adapter._installed and io_budget._installed, 'Missing I/O hooks'
    random.seed(1)
    np.random.seed(1)
    torch.manual_seed(1)
    torch.cuda.manual_seed_all(1)
    torch.set_num_threads(8)
    device = torch.device(job['device'])
    torch.ones(1, device=device).sum().item()
    torch.cuda.synchronize(device)
    folder = Path(job['folder'])
    reader = None
    if job['sorter'] == 'ks4':
        if 'chronosort' in sys.modules:
            raise RuntimeError('KS4 must be independent of ChronoSort')
        from kilosort import run_kilosort
        from kilosort.io import load_probe
        settings = dict(n_chan_bin=job['channels'], fs=job['fs'], batch_size=60000, cluster_init_seed=1)
        save(folder / 'settings.json', settings)
        probe = load_probe(job['probe'])
        reader = (bandwidth_adapter.RawArray(job['raw'], (job['samples'], job['channels']))
                  if job['kind'] == 'raw' else ep.open_recording(job['archive'], reader_mode='blocks'))
        resultdir = folder / 'results'
        def operation():
            return run_kilosort(settings=settings, probe=probe, results_dir=resultdir, device=device,
                    filename=Path(job['raw'] if job['kind'] == 'raw' else job['archive']), file_object=reader,
                    data_dtype='int16', save_preprocessed_copy=False, torch_thread_lim=8)
    else:
        from chronosort.config import BaseParams, Config, ExtraParams, RunParams, params_to_dict
        from chronosort.run_sorting import run_ChronoSort
        from chronosort.utils import binary, io, recording
        assert io.open_recording is recording.open_recording
        assert binary.open_recording is recording.open_recording
        defaults = Config()
        assert defaults.segment_size == 62000 and tuple(defaults.padding) == (1768, 1768)
        base = BaseParams(input_data_style='binary', input_folder_list=[job['raw'] if job['kind'] == 'raw' else job['archive']],
                output_folder=folder / 'run', probe_file=Path(job['chrono_probe']), sampling_rate=job['fs'])
        params = RunParams(device=job['device'], running_mode='standard', generate_plots=False,
                           initial_cluster_gpu_owner_memory_gib=4.0)
        extra = ExtraParams()
        resolved = params_to_dict(base, params, extra)
        save(folder / 'settings.json', resolved)
        # Native historical source defaults: no profile or source transformation.
        def operation():
            return run_ChronoSort(base, params, extra)
    before = io_budget.metrics(job)
    with threadpool_limits(limits=8):
        start = time.perf_counter()
        returned = operation()
        torch.cuda.synchronize(device)
        seconds = time.perf_counter() - start
        metrics = io_budget.metrics(job)
    for key in io_budget.CATEGORIES:
        for field in ['bytes', 'calls']:
            metrics[key][field] -= before[key][field]
    for key in ['total_read_bytes', 'total_write_bytes']:
        metrics[key] -= before[key]
    if metrics['input_read']['bytes'] <= 0:
        raise RuntimeError('Input was not metered; timing is invalid')
    if reader is not None:
        reader.close() if hasattr(reader, 'close') else None
    if job['sorter'] == 'ks4':
        save(folder / 'effective_settings.json', returned[0]['settings'])
        times = np.load(resultdir / 'spike_times.npy').ravel()
        labels = np.load(resultdir / 'spike_clusters.npy').ravel()
    else:
        recording.close_recordings()
        from chronosort.first_pass_results import validate_first_pass_results
        resultdir = Path(returned)
        manifest = validate_first_pass_results(resultdir)
        assert manifest['completed_stage'] == 'single_session_quality_filter'
        times = np.load(resultdir / 'day_0000/sample_indices.npy')
        labels = np.load(resultdir / 'day_0000/cluster_labels.npy')
    assert len(times) == len(labels) > 0 and times.min() >= 0 and times.max() < job['samples']
    import hashlib
    result = dict(**job, status='success', seconds=seconds, resultdir=str(resultdir),
                  spikes=len(times), units=len(np.unique(labels)), io_metrics=metrics,
                  input_metrics=bandwidth_adapter.metrics(job),
                  spike_times_sha256=hashlib.sha256(times.tobytes()).hexdigest(),
                  labels_sha256=hashlib.sha256(labels.tobytes()).hexdigest(),
                  scope='Public sorting API through export + CUDA synchronize; imports/probe/reader setup excluded')
    save(folder / 'result.json', result)


if __name__ == '__main__':
    run(load(sys.argv[1]))
