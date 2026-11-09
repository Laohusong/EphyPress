"""Sample aggregate process working sets; shared pages may be counted more than once."""
import json,time
from datetime import datetime,timezone
from pathlib import Path
import psutil
from bench import ROOT,load,save
summaries={};started=time.time()
while True:
    progress=load(ROOT/'progress.json')
    if progress.get('stage')=='complete':break
    name=progress.get('job')
    if name and name.startswith('sorting_'):
        expected=str(ROOT/name/'job.json').lower();parent=None
        for proc in psutil.process_iter(['pid','cmdline','create_time']):
            try:
                args=proc.info['cmdline'] or []
                if '--child' in args and any(str(a).lower()==expected for a in args):
                    if '--worker' in args and args[args.index('--worker')+1]=='0':parent=proc;break
            except (psutil.Error,ValueError,IndexError):pass
        if parent:
            try:
                procs=[parent]+parent.children(recursive=True)
                total=0;count=0
                for proc in procs:
                    try:total+=proc.memory_info().rss;count+=1
                    except psutil.Error:pass
                row=summaries.setdefault(name,dict(samples=0,peak_sum_working_set_bytes=0,first_sample=time.time(),
                    parent_start=parent.create_time(),partial_start=parent.create_time()<started))
                row['samples']+=1;row['last_sample']=time.time()
                row['peak_sum_working_set_bytes']=max(row['peak_sum_working_set_bytes'],total)
                with (ROOT/'memory_samples.jsonl').open('a') as f:f.write(json.dumps(dict(job=name,time=time.time(),working_set_sum=total,processes=count))+'\n')
                save(ROOT/'memory_summary.json',dict(sample_interval_seconds=2,started_utc=datetime.fromtimestamp(started,timezone.utc).isoformat(),
                    scope='Sampled sum of Windows working sets across sorting process and descendants. Shared pages can be double counted; not GPU memory; short spikes may be missed.',runs=summaries))
            except psutil.Error:pass
    time.sleep(2)
save(ROOT/'memory_monitor_complete.json',dict(status='success',runs=len(summaries)))
