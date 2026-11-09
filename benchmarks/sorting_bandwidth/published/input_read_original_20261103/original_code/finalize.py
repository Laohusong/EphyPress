"""Exclude the first successful ChronoSort warmup, rerun its formal point, plot."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from experiment import ROOT,SCRIPT,PYTHON,job_for,launch,read,save

def rebase_excluded(prefix,name,folder):
    marker=ROOT/(prefix+name+'.json')
    report=read(marker)
    if 'original_name' not in report:
        report['original_name']=report['name']
        report['original_paths']={k:report[k] for k in ('output','resultdir','limiter_state')}
        report['name']=prefix+name
        report['scope']='excluded_diagnostic_or_warmup'
        report['output']=str(folder)
        report['resultdir']=str(folder/Path(report['resultdir']).relative_to(ROOT/name))
        report['limiter_state']=str(ROOT/(prefix+name+'.limiter.bin'))
        save(marker,report)

rows=read(ROOT/'results.json')
assert len(rows)==28 and all(x['status']=='success' for x in rows)
if not (ROOT/'consumer_window_fidelity.json').exists():
    subprocess.run([str(PYTHON),str(SCRIPT/'verify_consumer_windows.py')],check=True)
assert read(ROOT/'consumer_window_fidelity.json')['exact_equal']
name='chronosort_raw_5000MBps'
marker=ROOT/(name+'.json')
pilot=ROOT/('warmup_'+name)
if not pilot.exists():
    source=(ROOT/name).resolve();target=pilot.resolve()
    assert source.parent==ROOT.resolve() and target.parent==ROOT.resolve()
    source.rename(target)
    for suffix in ('.json','.log','.job.json','.limiter.bin'):
        path=ROOT/(name+suffix)
        if path.exists():path.rename(ROOT/('warmup_'+name+suffix))
    save(ROOT/'warmup_policy.json',dict(excluded_run='warmup_'+name,
        reason='First successful full ChronoSort call warms Triton/Numba and Windows runtime caches. Its cold-start time is excluded; rerun at end for the formal 5000 MB/s raw point.',
        failed_attempt='failed_attempt_01_'+name,failed_reason='Default initial GPU owner 1.4 GiB budget exhausted, then Windows temp log lock during cleanup.',
        uniform_override=dict(initial_cluster_gpu_owner_memory_gib=4.0)))
rebase_excluded('warmup_',name,pilot)
if not marker.exists():
    result=launch(job_for('chronosort','raw',5000))
else:result=read(marker)
rows=[result if x['name']==name else x for x in rows]
comp_name='chronosort_compressed_5000MBps'
comp_marker=ROOT/(comp_name+'.json')
comp_pilot=ROOT/('prefetch_diagnostic_'+comp_name)
if not comp_pilot.exists():
    source=(ROOT/comp_name).resolve();target=comp_pilot.resolve()
    assert source.parent==ROOT.resolve() and target.parent==ROOT.resolve()
    source.rename(target)
    for suffix in ('.json','.log','.job.json','.limiter.bin'):
        path=ROOT/(comp_name+suffix)
        if path.exists():path.rename(ROOT/('prefetch_diagnostic_'+comp_name+suffix))
rebase_excluded('prefetch_diagnostic_',comp_name,comp_pilot)
if not comp_marker.exists():comp_result=launch(job_for('chronosort','compressed',5000))
else:comp_result=read(comp_marker)
rows=[comp_result if x['name']==comp_name else x for x in rows]
save(ROOT/'results.json',rows)
save(ROOT/'partial_results.json',rows)
protocol=read(ROOT/'experiment_protocol.json')
protocol['warmup_policy']=read(ROOT/'warmup_policy.json')
protocol['formal_order']=[x for x in protocol['ordered_jobs'] if x not in (name,comp_name)]+[name,comp_name]
protocol['compressed_reader_policy']='ChronoSort WindowPrefetch mixin + EphyPress codec, 8 cached blocks / 4 prefetch blocks; KS4 uses native EphyPress reader defaults.'
protocol['prefetch_diagnostic_excluded']='Initial high-bandwidth compressed ChronoSort run used generic EphyPress prefetch, produced excess file reads, excluded and replaced after preserving native consumer-window policy.'
save(ROOT/'experiment_protocol.json',protocol)
audit=ROOT/'experiment_code';audit.mkdir(exist_ok=True)
for p in SCRIPT.glob('*.py'):shutil.copy2(p,audit/p.name)
save(audit/'sha256.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in audit.glob('*.py')})
subprocess.run([str(PYTHON),str(SCRIPT/'plot_report.py')],check=True)
save(ROOT/'progress.json',dict(stage='complete',formal_runs=28,warmup_excluded=True,plots_complete=True))
if (ROOT/'pending_exclusions.json').exists():
    pending=read(ROOT/'pending_exclusions.json')
    save(ROOT/'excluded_diagnostics.json',dict(status='resolved',decisions=pending,
        warmup='warmup_chronosort_raw_5000MBps',prefetch_diagnostic='prefetch_diagnostic_chronosort_compressed_5000MBps',
        all_formal_points_replaced=True))
    (ROOT/'pending_exclusions.json').rename(ROOT/'original_exclusion_decisions.json')
print('FINAL REPORT AND PLOTS COMPLETE',flush=True)
