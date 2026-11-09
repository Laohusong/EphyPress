"""Verbatim KS4 function from historical experiment; requires original globals.
Use the portable benchmark.py entry point instead.
"""
def ks4_child(job):
    import numpy as np,torch,ephypress as ep
    from threadpoolctl import threadpool_limits
    from kilosort import run_kilosort
    from kilosort.io import load_probe
    from bandwidth_adapter import RawArray,metrics
    import io_budget
    folder=Path(job['folder']);random.seed(1);np.random.seed(1);torch.manual_seed(1);torch.cuda.manual_seed_all(1);torch.set_num_threads(8)
    torch.ones(1,device='cuda').sum().item();torch.cuda.synchronize()
    settings=dict(n_chan_bin=384,fs=30000.0,batch_size=60000,cluster_init_seed=1)
    common=dict(settings=settings,probe=load_probe(OLD/'ks4_probe.json'),results_dir=folder/'results',
        device=torch.device('cuda:0'),save_preprocessed_copy=False,torch_thread_lim=8)
    reader=RawArray(job['raw']) if job['kind']=='raw' else ep.open_recording(job['archive'])
    before=io_budget.metrics(job)
    with threadpool_limits(limits=8):
        start=time.perf_counter()
        run_kilosort(filename=Path(job['raw'] if job['kind']=='raw' else job['archive']),file_object=reader,data_dtype='int16',**common)
        torch.cuda.synchronize();seconds=time.perf_counter()-start
        timed_metrics=io_budget.metrics(job)
    for key in io_budget.CATEGORIES:
        for field in ('bytes','calls'):timed_metrics[key][field]-=before[key][field]
    for key in ('total_read_bytes','total_write_bytes'):timed_metrics[key]-=before[key]
    assert timed_metrics['input_read']['bytes']>0, 'KS4 input bypassed metering'
    if hasattr(reader,'close'):reader.close()
    times=np.load(folder/'results/spike_times.npy').ravel();labels=np.load(folder/'results/spike_clusters.npy').ravel()
    assert len(times)==len(labels)>0 and times.min()>=0 and times.max()<job['samples']
    save(folder/'result.json',dict(**job,status='success',seconds=seconds,resultdir=str(folder/'results'),spikes=len(times),units=len(np.unique(labels)),
        io_metrics=timed_metrics,input_metrics=metrics(job),
        spike_times_sha256=hashlib.sha256(times.tobytes()).hexdigest(),labels_sha256=hashlib.sha256(labels.tobytes()).hexdigest()))
