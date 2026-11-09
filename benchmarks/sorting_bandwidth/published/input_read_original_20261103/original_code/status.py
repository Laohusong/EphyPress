import json,time,re,struct
from pathlib import Path
root=Path(r'F:\EphyPress_benchmarks\bandwidth_30min_20261103')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
p=read(root/'progress.json');job=p.get('job',{});name=job.get('name','')
completed=read(root/'partial_results.json') if (root/'partial_results.json').exists() else []
stage=''
events=root/name/'run/stage_events.jsonl'
if events.exists():
    rows=events.read_text().splitlines()
    if rows:
        event=json.loads(rows[-1]);stage=event['stage']+':'+event['event']
elif (root/(name+'.log')).exists():
    lines=(root/(name+'.log')).read_text(encoding='utf-8',errors='replace').splitlines()
    recent=[x for x in lines[-8:] if x.strip()]
    stage=re.sub(r'[^\x20-\x7e]','',recent[-1])[-140:] if recent else ''
charged=None
state=root/(name+'.limiter.bin')
if state.is_file():charged=round(struct.unpack('<dQQdd',state.read_bytes())[1]/1e9,2)
print(json.dumps(dict(queue_completed=len(completed),formal_completed=p.get('formal_runs',max(0,len(completed)-2)),current=name,
    elapsed_seconds=round(p.get('elapsed_seconds',time.time()-p.get('started',time.time()))),stage=stage,charged_input_GB=charged),ensure_ascii=False))
