import json,os,subprocess,sys,time
from pathlib import Path
import experiment as ex

def child(job):
    import numpy as np, torch, io_budget, shutil, tempfile
    root=Path(job['folder'])/'run';root.mkdir()
    values=np.arange(1000000,dtype=np.float32).reshape(10000,100)
    start=time.perf_counter()
    np.save(root/'data.npy',values)
    assert np.array_equal(np.load(root/'data.npy'),values)
    mapped=np.load(root/'data.npy',mmap_mode='r')
    assert isinstance(mapped,io_budget.MappedArray)
    assert np.array_equal(mapped[:100],values[:100])
    assert np.array_equal(np.asarray(mapped),values)
    assert np.array_equal(mapped==values,np.ones_like(values,dtype=bool))
    assert torch.equal(torch.as_tensor(mapped),torch.from_numpy(values))
    assert mapped.min()==0
    target=np.lib.format.open_memmap(root/'mapped.npy',mode='w+',dtype=np.float32,shape=values.shape)
    target[:5000]=values[:5000];target[5000:]=values[5000:];target.flush();del target
    assert np.array_equal(np.load(root/'mapped.npy'),values)
    torch.save({'array':torch.from_numpy(values)},root/'tensor.pt')
    assert torch.equal(torch.load(root/'tensor.pt')['array'],torch.from_numpy(values))
    np.savez(root/'arrays.npz',data=values)
    with np.load(root/'arrays.npz') as data:assert np.array_equal(data['data'],values)
    shutil.copy2(root/'data.npy',root/'copy.npy')
    fd,path=tempfile.mkstemp(dir=root)
    with os.fdopen(fd,'w',encoding='utf-8') as f:f.write('test\n');f.flush();os.fsync(f.fileno())
    assert Path(path).read_text()=='test\n'
    # Independent read and write reservations share the same rates but not deadlines.
    elapsed=time.perf_counter()-start;metrics=io_budget.metrics(job)
    assert metrics['mapped_read']['bytes']==40000+4*4000000
    assert metrics['mapped_write']['bytes']==4000000
    assert metrics['stream_read']['bytes']>20000000 and metrics['stream_write']['bytes']>16000000
    ex.save(Path(job['folder'])/'preflight.json',dict(status='passed',elapsed=elapsed,metrics=metrics))
    print('IO PREFLIGHT PASS',round(elapsed,3),flush=True)

def main():
    if len(sys.argv)>1:child(ex.load(sys.argv[1]));return
    root=ex.ROOT/'io_preflight_v3';root.mkdir(parents=True,exist_ok=True)
    import bandwidth_adapter,io_budget
    results=[]
    for condition,rate in [('input_read_only',5000),('all_read_write',50),('all_read_write',5000)]:
        folder=root/f'{condition}_{rate}';folder.mkdir()
        job=dict(type='timing',profile='default',folder=str(folder),raw=str(ex.OLD/'first30min.dat'),archive=str(ex.OLD/'first30min.ep'),
            rate=rate,io_condition=condition,probe=str(ex.OLD/'probe.npy'),source_root=str(ex.OLD/'source_snapshot/src'),bandwidth_MB_s=rate,
            limiter_state=str(folder/'input.bin'),io_state=str(folder/'io.bin'))
        jp=folder/'job.json';ex.save(jp,job);bandwidth_adapter.initialize(job);io_budget.initialize(job)
        env=ex.env_for(jp,job)
        result=subprocess.run([str(ex.PY),'-u',__file__,str(jp)],env=env)
        assert result.returncode==0
        results.append(ex.load(folder/'preflight.json'))
    ex.save(ex.ROOT/'io_preflight.json',results)

if __name__=='__main__':main()
