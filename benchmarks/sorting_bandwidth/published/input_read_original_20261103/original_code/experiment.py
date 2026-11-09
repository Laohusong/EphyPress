from __future__ import annotations
import argparse,csv,hashlib,json,os,random,subprocess,sys,time,traceback
from pathlib import Path

ROOT=Path(r'F:\EphyPress_benchmarks\bandwidth_30min_20261103')
SCRIPT=Path(__file__).resolve().parent
PYTHON=Path(r'D:\EphyPress\.venv-windows-gpu\Scripts\python.exe')
RATES=[50,100,200,500,1000,2000,5000]
def save(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.new');temp.write_text(json.dumps(obj,indent=2,default=str),encoding='utf-8');temp.replace(path)
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def environment(jobpath):
    env={**os.environ,'BANDWIDTH_JOB':str(jobpath),'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1',
         'PYTHONUNBUFFERED':'1','MPLBACKEND':'Agg','PYTHONPATH':os.pathsep.join([str(SCRIPT),str(ROOT/'source_snapshot/src')])}
    for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS'):env[key]='8'
    return env
def job_for(sorter,kind,rate,name=None):
    name=name or f'{sorter}_{kind}_{rate:04d}MBps'
    return dict(name=name,sorter=sorter,kind=kind,bandwidth_MB_s=rate,
        raw=str(ROOT/'first30min.dat'),archive=str(ROOT/'first30min.ep'),
        output=str(ROOT/name),limiter_state=str(ROOT/(name+'.limiter.bin')))
def launch(job,validation=False):
    from bandwidth_adapter import initialize
    request=ROOT/(job['name']+'.job.json');save(request,job);initialize(job)
    log=ROOT/(job['name']+'.log')
    args=[str(PYTHON),'-u',str(Path(__file__).resolve()),'--validate' if validation else '--worker',str(request)]
    with log.open('w',encoding='utf-8') as f:
        child=subprocess.Popen(args,stdout=f,stderr=subprocess.STDOUT,env=environment(request),creationflags=subprocess.CREATE_NO_WINDOW)
        save(ROOT/'progress.json',dict(stage='validating' if validation else 'sorting',job=job,pid=child.pid,log=str(log),started=time.time()))
        start=time.monotonic();last=0
        while child.poll() is None:
            elapsed=time.monotonic()-start
            if elapsed-last>=45:
                last=elapsed
                save(ROOT/'progress.json',dict(stage='validating' if validation else 'sorting',job=job,
                    pid=child.pid,log=str(log),elapsed_seconds=elapsed,updated=time.time()))
                print(f"RUNNING {job['name']} {elapsed:.0f}s",flush=True)
            time.sleep(2)
    if child.returncode:raise RuntimeError(f'{job["name"]} exited {child.returncode}; see {log}')
    return read(ROOT/(job['name']+'.json'))

def validate(job):
    import concurrent.futures
    import numpy as np
    import ephypress as ep
    from bandwidth_adapter import RawArray,metrics
    # Charge identical logical windows and check all columns, halos and striding.
    raw=RawArray(job['raw'])
    reference=np.memmap(job['raw'],mode='r',dtype='<i2',shape=raw.shape)
    with ep.open_recording(job['archive']) as compressed:
        for a,b,step in [(0,1000,1),(59900,60500,1),(1234567,1240000,3),(53999000,54000000,1)]:
            assert np.array_equal(raw[a:b:step],reference[a:b:step])
            assert np.array_equal(compressed[a:b:step],reference[a:b:step])
        assert np.array_equal(raw[-1],reference[-1])
    before=metrics(job)['charged_file_bytes'];start=time.perf_counter()
    # Simultaneous reads must share one cap rather than each receiving the cap.
    def work(i):return raw[i*60000:(i+1)*60000].shape
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(work,range(12)))
    elapsed=time.perf_counter()-start;charged=metrics(job)['charged_file_bytes']-before
    throughput=charged/elapsed/1e6
    assert 0.85*job['bandwidth_MB_s']<throughput<1.02*job['bandwidth_MB_s'],(elapsed,throughput)
    before_process=metrics(job)['charged_file_bytes'];process_start=time.perf_counter()
    code="import os,json;from pathlib import Path;from bandwidth_adapter import RawArray;j=json.loads(Path(os.environ['BANDWIDTH_JOB']).read_text());a=RawArray(j['raw']);[a[i*60000:(i+1)*60000] for i in range(3)]"
    children=[subprocess.Popen([sys.executable,'-c',code],creationflags=subprocess.CREATE_NO_WINDOW) for _ in range(4)]
    for child in children:assert child.wait()==0
    process_elapsed=time.perf_counter()-process_start
    process_bytes=metrics(job)['charged_file_bytes']-before_process
    assert process_bytes==12*60000*384*2
    assert process_bytes/process_elapsed/1e6<1.02*job['bandwidth_MB_s']
    save(ROOT/(job['name']+'.json'),dict(status='success',value_equality=True,threads=4,
        requested_MB_s=job['bandwidth_MB_s'],observed_MB_s=throughput,elapsed_seconds=elapsed,
        subprocesses=4,subprocess_observed_MB_s=process_bytes/process_elapsed/1e6,metrics=metrics(job)))

def worker(job):
    import importlib.metadata
    import numpy as np
    import torch
    import psutil
    from bandwidth_adapter import RawArray,metrics
    from threadpoolctl import threadpool_limits
    output=Path(job['output']);assert not output.exists();output.mkdir()
    random.seed(1);np.random.seed(1);torch.manual_seed(1);torch.cuda.manual_seed_all(1);torch.set_num_threads(8)
    torch.ones(1,device='cuda').sum().item();torch.cuda.synchronize()
    protocol=dict(job=job,seed=1,numeric_threads=8,source=read(ROOT/'source_manifest.json')['git_commit'],
        device=torch.cuda.get_device_name(0),torch=torch.__version__,python=sys.version,
        versions={p:importlib.metadata.version(p) for p in ['ephypress','kilosort','triton-windows','isosplit6']},
        scope='First 1800 seconds, all 384 channels; no GT or biological accuracy evaluation',
        throttle='Shared input-file byte delivery budget across processes and threads; decimal MB/s; outputs unthrottled; OS file-cache hits remain charged; decoded SPC cache hits are uncharged.',
        compressed_adapter='Experiment-only EphyPress adapter in sitecustomize; source unchanged',
        timer='Complete public sorting API including exports, excludes imports/initial CUDA warmup')
    save(output/'protocol.json',protocol)
    with threadpool_limits(limits=8):
        if job['sorter']=='ks4':
            from kilosort import run_kilosort
            import ephypress as ep
            from kilosort.io import load_probe
            settings=dict(n_chan_bin=384,fs=30000.0,batch_size=60000,cluster_init_seed=1)
            common=dict(settings=settings,probe=load_probe(ROOT/'ks4_probe.json'),results_dir=output/'results',
                device=torch.device('cuda:0'),save_preprocessed_copy=False,torch_thread_lim=8)
            reader=RawArray(job['raw']) if job['kind']=='raw' else ep.open_recording(job['archive'])
            start=time.perf_counter();cpu=time.process_time()
            result=run_kilosort(filename=Path(job['raw'] if job['kind']=='raw' else job['archive']),
                file_object=reader,data_dtype='int16',**common)
            torch.cuda.synchronize();seconds=time.perf_counter()-start;cpu=time.process_time()-cpu
            resultdir=output/'results'
            samples=np.load(resultdir/'spike_times.npy',mmap_mode='r').reshape(-1)
            labels=np.load(resultdir/'spike_clusters.npy',mmap_mode='r').reshape(-1)
            if hasattr(reader,'close'):reader.close()
            stage='ks4_complete'
        else:
            from chronosort.config import BaseParams,RunParams,ExtraParams,params_to_dict
            from chronosort.run_sorting import run_ChronoSort
            from chronosort.first_pass_results import validate_first_pass_results
            base=BaseParams(input_data_style='binary',input_folder_list=[job['raw'] if job['kind']=='raw' else job['archive']],
                output_folder=output/'run',probe_file=ROOT/'probe.npy',sampling_rate=30000)
            run=RunParams(device='cuda:0',running_mode='standard',generate_plots=False,
                initial_cluster_gpu_owner_memory_gib=4.0)
            extra=ExtraParams()
            save(output/'requested_settings.json',params_to_dict(base,run,extra))
            start=time.perf_counter();cpu=time.process_time()
            resultdir=run_ChronoSort(base,run,extra)
            torch.cuda.synchronize();seconds=time.perf_counter()-start;cpu=time.process_time()-cpu
            manifest=validate_first_pass_results(resultdir)
            stage=manifest['completed_stage'];assert stage=='single_session_quality_filter',stage
            samples=np.load(resultdir/'day_0000/sample_indices.npy',mmap_mode='r')
            labels=np.load(resultdir/'day_0000/cluster_labels.npy',mmap_mode='r')
    assert len(samples)==len(labels) and len(samples)>0
    assert samples.min()>=0 and samples.max()<54000000
    metric=metrics(job);assert metric['charged_file_bytes']>0
    stage_seconds={}
    if job['sorter']=='chronosort':
        starts={}
        for line in (output/'run/stage_events.jsonl').read_text().splitlines():
            event=json.loads(line)
            if event['event']=='start':starts[event['stage']]=event['monotonic_time']
            elif event['stage'] in starts:
                stage_seconds[event['stage']]=event['monotonic_time']-starts.pop(event['stage'])
    report=dict(status='success',**job,sorting_seconds=seconds,process_cpu_seconds=cpu,
        spikes=len(samples),units=len(np.unique(labels)),resultdir=str(resultdir),completed_stage=stage,
        peak_working_set_bytes=getattr(psutil.Process().memory_info(),'peak_wset',None),input_metrics=metric,
        stage_seconds=stage_seconds)
    save(ROOT/(job['name']+'.json'),report)
    print(json.dumps(report),flush=True)

def queue():
    assert read(ROOT/'verification.json')['exact_equal']
    validation=job_for('validation','raw',50,'limiter_validation')
    if not (ROOT/'limiter_validation.json').exists():launch(validation,True)
    # First test both ChronoSort input paths at high bandwidth, then cover the grid.
    jobs=[job_for('chronosort',kind,5000) for kind in ('raw','compressed')]
    for i,rate in enumerate(RATES):
        for sorter in ('ks4','chronosort'):
            kinds=('raw','compressed') if i%2==0 else ('compressed','raw')
            jobs += [job_for(sorter,kind,rate) for kind in kinds if not (sorter=='chronosort' and rate==5000)]
    save(ROOT/'jobs.json',jobs)
    protocol=dict(rates_MB_s=RATES,run_count=len(jobs),repeats_per_combination=1,
        ordered_jobs=[j['name'] for j in jobs],input=read(ROOT/'subset.json'),
        source=read(ROOT/'source_manifest.json')['git_commit'],source_changes=False,
        notes=['Input bandwidth simulation, not physical HDD emulation.',
            'Normal OS caching, but every reader-requested file byte is charged before delivery.',
            'Each sorter/input/rate uses a fresh subprocess; all GPU jobs run serially.',
            'ChronoSort uses current single-session defaults including final quality filter; initial_cluster_gpu_owner_memory_gib=4.0 uniformly because default 1.4 GiB exhausted on this input.',
            'Source snapshot fixed at task start. One run per combination, no uncertainty estimates.'])
    save(ROOT/'experiment_protocol.json',protocol)
    completed=[]
    for index,job in enumerate(jobs):
        marker=ROOT/(job['name']+'.json')
        report=read(marker) if marker.exists() else launch(job)
        assert report['status']=='success'
        completed.append(report)
        save(ROOT/'partial_results.json',completed)
        print(f"DONE {index+1}/{len(jobs)} {job['name']} {report['sorting_seconds']:.2f}s",flush=True)
    save(ROOT/'results.json',completed)
    save(ROOT/'progress.json',dict(stage='complete',runs=len(completed)))
    print('ALL 28 RUNS COMPLETE',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--validate');p.add_argument('--queue',action='store_true');a=p.parse_args()
    if a.worker:worker(read(a.worker))
    elif a.validate:validate(read(a.validate))
    else:queue()
