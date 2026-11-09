import hashlib,json,shutil,subprocess,time
from pathlib import Path
import numpy as np
import ephypress as ep
root=Path(r'F:\EphyPress_benchmarks\bandwidth_30min_20261103')
root.mkdir(parents=True,exist_ok=True)
old=Path(r'F:\EphyPress_benchmarks\251107_ProbeB_AP_20261102_193244')
cfg=json.loads((old/'config.json').read_text())
def save(name,obj): (root/name).write_text(json.dumps(obj,indent=2,default=str),encoding='utf-8')
raw=root/'first30min.dat'; archive=root/'first30min.ep'
length=1800*30000*384*2
if not raw.exists():
    digest=hashlib.sha256(); remaining=length
    with Path(cfg['raw']).open('rb') as source,raw.with_suffix('.partial').open('wb') as dest:
        while remaining:
            block=source.read(min(8*1024**2,remaining)); assert block
            dest.write(block);digest.update(block);remaining-=len(block)
    raw.with_suffix('.partial').rename(raw)
    save('subset.json',dict(source=cfg['raw'],start_sample=0,end_sample=54000000,samples=54000000,
        channels=384,fs=30000,duration_seconds=1800,bytes=length,sha256=digest.hexdigest(),
        original_size=cfg['source_bytes'],original_mtime_ns=cfg['source_mtime_ns']))
assert raw.stat().st_size==length
snapshot=root/'source_snapshot'
if not snapshot.exists():
    snapshot.mkdir()
    for folder in ('src','resources'):
        shutil.copytree(Path(r'D:\ChronoSort')/folder,snapshot/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    hashes={str(p.relative_to(snapshot)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (snapshot/'src').rglob('*') if p.is_file()}
    save('source_manifest.json',dict(git_commit=subprocess.check_output(['git','-C',r'D:\ChronoSort','rev-parse','HEAD'],text=True).strip(),sha256=hashes))
import probeinterface as pi
probe=pi.read_openephys(old/'settings.xml',stream_name='ProbeB-AP')
np.save(root/'probe.npy',probe.to_numpy(complete=True))
shutil.copy2(old/'probe.json',root/'ks4_probe.json')
if not archive.exists():
    start=time.perf_counter()
    def progress(a,b,c,d):
        if a%100==0 or a==b: print(f'compression {a}/{b} {d:.1f}s',flush=True)
    result=ep.compress(raw,archive,384,sampling_frequency=30000,workers=4,prediction='temporal',entropy_backend='fse',progress=progress)
    result['wall_seconds']=time.perf_counter()-start; save('compression.json',result)
start=time.perf_counter();digest=hashlib.sha256();count=0
with raw.open('rb') as reference,ep.open_recording(archive) as reader:
    for block in reader.iter_cores():
        b=reference.read(block.nbytes)
        assert np.array_equal(block,np.frombuffer(b,dtype='<i2').reshape(block.shape))
        digest.update(b);count+=len(b)
assert count==length and digest.hexdigest()==json.loads((root/'subset.json').read_text())['sha256']
save('verification.json',dict(exact_equal=True,bytes=count,sha256=digest.hexdigest(),seconds=time.perf_counter()-start))
print('PREPARATION COMPLETE',flush=True)
