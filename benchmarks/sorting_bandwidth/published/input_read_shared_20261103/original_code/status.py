import json
from pathlib import Path
ROOT=Path(r'F:\EphyPress_benchmarks\shared_cache_curve_30min_20261103')
progress=json.loads((ROOT/'progress.json').read_text())
print(json.dumps(progress,ensure_ascii=False))
for path in sorted(ROOT.glob('sorting_*/result.json')):
    r=json.loads(path.read_text())
    print(r['name'],round(r['seconds'],2),'sec',round(r['input_metrics']['charged_file_bytes']/1e9,3),'GB',r['units'],'units',r['spikes'],'spikes', 'decode',r['reader_metrics']['decode_calls'])
if progress.get('job'):
    import struct
    state=ROOT/progress['job']/'limiter.bin'
    if state.exists():
        _,total,calls,_,_=struct.unpack('<dQQdd',state.read_bytes())
        print('active charged reads',round(total/1e9,3),'GB',calls,'calls')
    log=ROOT/progress['job']/'process_0.log'
    if log.exists():print('\n'.join(log.read_text(encoding='utf-8',errors='replace').splitlines()[-4:]))
