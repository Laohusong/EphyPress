import os,subprocess,sys,time
from pathlib import Path
import experiment as ex

def child(jp,wid):
    import io_budget
    from bandwidth_adapter import RawArray
    job=ex.load(jp);folder=Path(job['folder']);(folder/f'ready_{wid}').touch()
    while not (folder/'go').exists():time.sleep(.005)
    start=time.perf_counter()
    # 4.608 MB source + 4 MB intermediate read, and 4 MB write per worker.
    data=RawArray(job['raw'])[:6000]
    assert data.shape==(6000,384)
    with open(folder/'run'/f'out_{wid}.bin','wb') as f:f.write(bytes(4000000))
    with open(folder/'run'/'source.bin','rb') as f:assert len(f.read())==4000000
    ex.save(folder/f'worker_{wid}.json',dict(start=start,end=time.perf_counter()))

def main():
    if len(sys.argv)>1:child(sys.argv[1],int(sys.argv[2]));return
    import io_budget,bandwidth_adapter
    results=[]
    for condition in ['input_read_only','all_read_write']:
        folder=ex.ROOT/f'budget_preflight_v2_{condition}';(folder/'run').mkdir(parents=True)
        (folder/'run'/'source.bin').write_bytes(bytes(4000000))
        job=dict(type='timing',profile='default',folder=str(folder),raw=str(ex.OLD/'first30min.dat'),archive=str(ex.OLD/'first30min.ep'),
            rate=50,io_condition=condition,probe=str(ex.OLD/'probe.npy'),source_root=str(ex.OLD/'source_snapshot/src'),bandwidth_MB_s=50,
            limiter_state=str(folder/'input.bin'),io_state=str(folder/'io.bin'))
        jp=folder/'job.json';ex.save(jp,job);bandwidth_adapter.initialize(job);io_budget.initialize(job)
        env=ex.env_for(jp,job);children=[]
        for wid in range(4):children.append(subprocess.Popen([str(ex.PY),'-u',__file__,str(jp),str(wid)],env=env,creationflags=subprocess.CREATE_NO_WINDOW))
        while not all((folder/f'ready_{i}').exists() for i in range(4)):
            assert all(p.poll() is None for p in children);time.sleep(.05)
        (folder/'go').touch()
        assert all(p.wait()==0 for p in children)
        rows=[ex.load(folder/f'worker_{i}.json') for i in range(4)]
        elapsed=max(r['end'] for r in rows)-min(r['start'] for r in rows)
        stats=io_budget.metrics(job)
        assert stats['input_read']['bytes']==18432000
        assert stats['stream_read']['bytes']==16000000
        assert stats['stream_write']['bytes']==16000000
        expected_read=18432000+(16000000 if condition=='all_read_write' else 0)
        assert elapsed>=expected_read/50e6-.025
        assert elapsed<expected_read/50e6+.6
        results.append(dict(condition=condition,seconds=elapsed,expected_min_read_seconds=expected_read/50e6,metrics=stats))
        print('MULTIPROCESS BUDGET PASS',condition,round(elapsed,3),flush=True)
    ex.save(ex.ROOT/'multiprocess_budget_preflight.json',results)

if __name__=='__main__':main()
