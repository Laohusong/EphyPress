import argparse,collections,hashlib,json,os,random,shutil,subprocess,sys,time
from pathlib import Path
SCRIPT=Path(__file__).resolve().parent
ROOT=Path(r'F:\EphyPress_benchmarks\shared_cache_curve_30min_20261103')
DATA=Path(r'F:\EphyPress_benchmarks\prefetch_strategies_20261103')
OLD=Path(r'F:\EphyPress_benchmarks\bandwidth_30min_20261103')
PY=Path(r'D:\EphyPress\.venv-windows-gpu\Scripts\python.exe')
SAMPLES=54000000
STRATEGIES=['baseline','batch2_off','scheduled']

def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.new');tmp.write_text(json.dumps(v,indent=2,ensure_ascii=False,default=str),encoding='utf-8');tmp.replace(p)
def windows():
    return [(i,max(0,i*62000-1768),min(SAMPLES,(i+1)*62000+1768)) for i in range((SAMPLES+61999)//62000)]

def prepare():
    import numpy as np,ephypress as ep
    ROOT.mkdir(parents=True,exist_ok=True)
    if (ROOT/'verification.json').exists():return
    subset=load(OLD/'subset.json');raw=OLD/'first30min.dat';archive=OLD/'first30min.ep'
    meta=dict(raw=str(raw),archive=str(archive),raw_bytes=raw.stat().st_size,archive_bytes=archive.stat().st_size,
        samples=SAMPLES,seconds=1800,channels=384,fs=30000,block_samples=60000,blocks=900,source=subset['source'])
    assert meta['raw_bytes']==41472000000 and meta['archive_bytes']==23227387437
    ref=np.memmap(raw,mode='r',dtype='<i2',shape=(SAMPLES,384));expected={}
    with ep.open_recording(archive,prefetch=False) as reader:
        for i,a,b in windows():
            assert np.array_equal(reader[a:b],ref[a:b]);expected[str(i)]=hashlib.sha256(ref[a:b].tobytes()).hexdigest()
    digest=hashlib.sha256()
    for lo in range(0,SAMPLES,60000):digest.update(ref[lo:lo+60000].tobytes())
    assert digest.hexdigest()==subset['sha256']
    meta['expected']=expected;meta['raw_sha256']=digest.hexdigest();save(ROOT/'input.json',meta)
    save(ROOT/'verification.json',dict(exact_equal=True,all_ADC_windows_verified=True,
        matches_original_30min_sha256=True,raw_sha256=digest.hexdigest(),windows=len(expected),samples=SAMPLES))

def env_for(jobpath,job):
    env={**os.environ,'BANDWIDTH_JOB':str(jobpath),'PREFETCH_STRATEGY':job['strategy'],
       'POLICY_STATS_DIR':str(Path(job['folder'])/'reader_stats'),'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8',
       'PYTHONUNBUFFERED':'1','MPLBACKEND':'Agg','PYTHONPATH':os.pathsep.join([str(SCRIPT),str(OLD/'source_snapshot/src')])}
    for key in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS']:env[key]='8' if job['mode']=='sorting' else '1'
    return env

def job_for(mode,strategy,rate,batch=0,repeat=1,kind='compressed'):
    meta=load(ROOT/'input.json');name=f'{mode}_{kind}_{strategy}_{rate:04d}MBps'+(f'_b{batch}' if batch else '');folder=ROOT/name
    return dict(name=name,mode=mode,strategy=strategy,rate=rate,batch=batch,repeat=repeat,
        kind=kind,
        raw=meta['raw'],archive=meta['archive'],bandwidth_MB_s=rate or 1e12,
        folder=str(folder),limiter_state=str(folder/'limiter.bin'))

def aggregate(folder):
    rows=[]
    for p in (Path(folder)/'reader_stats').glob('*.jsonl'):
        if p.name=='loaders.jsonl':continue
        rows.extend(json.loads(line) for line in p.read_text().splitlines())
    return dict(readers=len(rows),payload_bytes=sum(r['statistics']['bytes_read'] for r in rows),
        decode_calls=sum(r['statistics']['decoded_blocks'] for r in rows),
        windows=sum(r['windows'] for r in rows),context_windows=sum(r['context_windows'] for r in rows),
        batch2_windows=sum(r['batch2_windows'] for r in rows),
        unused_decode_calls=sum(r['unused_decode_calls'] for r in rows),
        within_reader_repeat_decodes=sum(r['repeat_decode_calls'] for r in rows),
        cache_hits=sum(r['statistics']['cache_hits'] for r in rows),
        max_single_reader_cache_bytes=max([r['statistics']['max_decoded_cache_bytes'] for r in rows] or [0]),
        shared_hits=sum((r.get('shared_stats') or {}).get('hits',0) for r in rows),
        shared_misses=sum((r.get('shared_stats') or {}).get('misses',0) for r in rows))

def replay_child(job,wid):
    import policy
    from policy import PolicyReader
    folder=Path(job['folder']);mine=[w for w in windows() if (w[0]//job['batch'])%4==wid]
    reader=PolicyReader(job['archive'],cache_blocks=8,prefetch_blocks=4)
    (folder/f'ready_{wid}').touch()
    while not (folder/'go').exists():time.sleep(.01)
    start=time.perf_counter();cpu=time.process_time();digests={};hash_seconds=0
    for pos,(i,a,b) in enumerate(mine):
        policy.ACTIVE=dict(batch=job['batch'],future=[(job['archive'],lo,hi) for _,lo,hi in mine[pos+1:pos+5]])
        data=reader[a:b];t=time.perf_counter();digests[str(i)]=hashlib.sha256(data.tobytes()).hexdigest();hash_seconds+=time.perf_counter()-t
    reader.close()
    save(folder/f'worker_{wid}.json',dict(seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu,hash_seconds=hash_seconds,digests=digests))

def sorting_child(job):
    import numpy as np,torch
    from threadpoolctl import threadpool_limits
    from chronosort.config import BaseParams,RunParams,ExtraParams,params_to_dict
    from chronosort.run_sorting import run_ChronoSort
    from chronosort.first_pass_results import validate_first_pass_results
    from chronosort.utils import recording
    from bandwidth_adapter import metrics
    random.seed(1);np.random.seed(1);torch.manual_seed(1);torch.cuda.manual_seed_all(1);torch.set_num_threads(8)
    torch.ones(1,device='cuda').sum().item();torch.cuda.synchronize()
    folder=Path(job['folder'])
    base=BaseParams(input_data_style='binary',input_folder_list=[job['raw'] if job['kind']=='raw' else job['archive']],output_folder=folder/'run',probe_file=OLD/'probe.npy',sampling_rate=30000)
    run=RunParams(device='cuda:0',running_mode='standard',generate_plots=False,initial_cluster_gpu_owner_memory_gib=4.0)
    extra=ExtraParams();save(folder/'settings.json',params_to_dict(base,run,extra))
    with threadpool_limits(limits=8):
        start=time.perf_counter();cpu=time.process_time();resultdir=run_ChronoSort(base,run,extra)
        torch.cuda.synchronize();seconds=time.perf_counter()-start;cpu=time.process_time()-cpu
        recording.close_recordings();torch.cuda.synchronize();seconds_including_reader_close=time.perf_counter()-start
    manifest=validate_first_pass_results(resultdir);assert manifest['completed_stage']=='single_session_quality_filter'
    times=np.load(resultdir/'day_0000/sample_indices.npy',mmap_mode='r');labels=np.load(resultdir/'day_0000/cluster_labels.npy',mmap_mode='r')
    assert len(times)==len(labels)>0 and times.min()>=0 and times.max()<SAMPLES
    stages={};starts={}
    for line in (folder/'run/stage_events.jsonl').read_text().splitlines():
        event=json.loads(line)
        if event['event']=='start':starts[event['stage']]=event['monotonic_time']
        elif event['stage'] in starts:stages[event['stage']]=event['monotonic_time']-starts.pop(event['stage'])
    save(folder/'result.json',dict(**job,status='success',seconds=seconds,seconds_including_reader_close=seconds_including_reader_close,cpu_seconds=cpu,stage_seconds=stages,
        spikes=len(times),units=len(np.unique(labels)),completed_stage=manifest['completed_stage'],
        spike_times_sha256=hashlib.sha256(times.tobytes()).hexdigest(),labels_sha256=hashlib.sha256(labels.tobytes()).hexdigest(),
        input_metrics=metrics(job),reader_metrics=aggregate(folder)))

def launch(job):
    from bandwidth_adapter import initialize,metrics
    folder=Path(job['folder']);marker=folder/'result.json'
    if marker.exists():return load(marker)
    folder.mkdir(exist_ok=True);jp=folder/'job.json';save(jp,job);initialize(job)
    env=env_for(jp,job);children=[];logs=[]
    n=4 if job['mode']=='replay' else 1
    for wid in range(n):
        log=(folder/f'process_{wid}.log').open('w',encoding='utf-8');logs.append(log)
        args=[str(PY),'-u',str(__file__),'--child',str(jp),'--worker',str(wid)]
        children.append(subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW))
    start=time.perf_counter()
    if job['mode']=='replay':
        while not all((folder/f'ready_{i}').exists() for i in range(n)):
            if any(p.poll() is not None for p in children):raise RuntimeError(f'Child startup failed: {folder}')
            if time.perf_counter()-start>150:raise RuntimeError('Startup timeout')
            time.sleep(.05)
        start=time.perf_counter();(folder/'go').touch()
    last=0
    while any(p.poll() is None for p in children):
        elapsed=time.perf_counter()-start
        if elapsed-last>=45:
            last=elapsed;save(ROOT/'progress.json',dict(stage='running',job=job['name'],elapsed_seconds=elapsed,pids=[p.pid for p in children]))
            print('RUNNING',job['name'],round(elapsed),flush=True)
        time.sleep(.5)
    elapsed=time.perf_counter()-start
    for log in logs:log.close()
    if any(p.returncode for p in children):raise RuntimeError(f'Job failed {folder}; codes {[p.returncode for p in children]}')
    if job['mode']=='replay':
        rows=[load(folder/f'worker_{i}.json') for i in range(n)]
        digests={k:v for row in rows for k,v in row['digests'].items()};assert digests==load(ROOT/'input.json')['expected']
        # Use worker region timing; parent 0.5s polling is excluded from reported replay time.
        result=dict(**job,status='success',seconds=max(r['seconds'] for r in rows),
            parent_poll_seconds=elapsed,exact_window_hashes=True,
            cpu_seconds=sum(r['cpu_seconds'] for r in rows),hash_seconds=sum(r['hash_seconds'] for r in rows),
            input_metrics=metrics(job),reader_metrics=aggregate(folder));save(marker,result)
    else:result=load(marker)
    print('DONE',job['name'],round(result['seconds'],2),'readsGB',round(result['reader_metrics']['payload_bytes']/1e9,3),flush=True)
    return result

def main():
    ROOT.mkdir(parents=True,exist_ok=True);save(ROOT/'progress.json',dict(stage='preparing',total=7))
    prepare();results=[]
    protocol=dict(source_commit=load(OLD/'source_manifest.json')['git_commit'],source_snapshot=str(OLD/'source_snapshot/src'),
        source_modified=False,seconds=1800,strategies=['shared'],rates=[50,100,200,500,1000,2000,5000],cache_blocks=8,prefetch_blocks=4,
        scope='Seven fresh complete ChronoSort runs using shared decoded cache, first1800sec ProbeB-AP. Original raw and compressed curves are historical controls, not rerun.',
        changes='Byte-identical shared policy/cache implementation from successful five-minute test. Seven shared slots plus one local retained block per worker; bounded aggregate retained budget8 blocks/worker. Single flight per block, private safe copies on shared hits. Cache isolated by loader; no cross-stage persistence; no grouped dispatch. Pending decode/copy buffers additional.',
        throttle='Shared logical input-file byte budget across processes and threads; decimal MB/s. OS cache hits charged; decoded cache hits uncharged; intermediate/output reads and writes unthrottled.5000MB/s is an upper bound, not guaranteed achieved throughput. Raw uses buffered reads at both caps rather than native memmap.',
        sorting='Full API through single_session_quality_filter/export and GPU synchronize; imports and initial CUDA warmup excluded. Main curve timer matches original30min API timer; separately record reader-close-inclusive timer. Source/defaults match original sweep, GPU owner4GiB.',
        repeat_policy='One fresh shared-cache run per bandwidth. Historical original30min raw/old-window-prediction compressed controls explicitly labelled; no new raw runs or repetitions.',
        correctness='All source windows reverified against raw and previous SHA256 references before runs; full sorting dispatch asserted. Final array identity checked across inputs and caps; no GT or biological accuracy claim.')
    save(ROOT/'protocol.json',protocol)
    # Reverse input order between caps; all GPU runs serial and fresh.
    jobs=[job_for('sorting','shared',rate,kind='compressed') for rate in [5000,50,100,200,500,1000,2000]]
    save(ROOT/'jobs.json',jobs)
    for job in jobs:
        save(ROOT/'progress.json',dict(stage='starting',job=job['name'],completed=len(results),total=7))
        results.append(launch(job));save(ROOT/'results.json',results)
    save(ROOT/'progress.json',dict(stage='complete',runs=len(results)))
    import report
    report.main()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--child');p.add_argument('--worker',type=int,default=0);a=p.parse_args()
    if a.child:
        j=load(a.child)
        if j['mode']=='replay':replay_child(j,a.worker)
        else:sorting_child(j)
    else:main()
