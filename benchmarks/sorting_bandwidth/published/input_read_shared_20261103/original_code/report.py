import csv,hashlib,json,os,shutil,subprocess
from pathlib import Path
from bench import ROOT,OLD,SCRIPT,PY,load,save,job_for,launch
RATES=[50,100,200,500,1000,2000,5000]

def historical():
    import numpy as np
    rows=[]
    for kind in ('raw','compressed'):
        for rate in RATES:
            source=OLD/f'chronosort_{kind}_{rate:04d}MBps.json';r=load(source)
            resultdir=Path(r['resultdir']);times=np.load(resultdir/'day_0000/sample_indices.npy',mmap_mode='r');labels=np.load(resultdir/'day_0000/cluster_labels.npy',mmap_mode='r')
            rows.append(dict(series='raw' if kind=='raw' else 'old_compressed',rate=rate,seconds=r['sorting_seconds'],
                read_GB=r['input_metrics']['charged_file_bytes']/1e9,units=r['units'],spikes=r['spikes'],
                times_sha256=hashlib.sha256(times.tobytes()).hexdigest(),labels_sha256=hashlib.sha256(labels.tobytes()).hexdigest(),
                stage_seconds=r['stage_seconds'],source=str(source),historical=True))
    return rows

def main():
    fresh=load(ROOT/'results.json');assert len(fresh)==7 and {r['rate'] for r in fresh}==set(RATES)
    # One contemporaneous high-bandwidth raw anchor checks the observed compute drift.
    # Keep the seven original raw curve points explicitly historical.
    anchor_job=job_for('sorting','scheduled',5000,kind='raw')
    jobs=load(ROOT/'jobs.json')
    if not any(job['name']==anchor_job['name'] for job in jobs):save(ROOT/'jobs.json',jobs+[anchor_job])
    protocol=load(ROOT/'protocol.json')
    protocol['additional_control']=dict(kind='raw',rate=5000,reason='First new5000 run has identical arrays to historical compressed5000 but slower non-reader clustering stages. Add one fresh high-bandwidth raw anchor to assess contemporaneous compute cost; retain historical raw curve unchanged.')
    save(ROOT/'protocol.json',protocol)
    save(ROOT/'progress.json',dict(stage='starting',job=anchor_job['name'],completed=7,total=8))
    anchor=launch(anchor_job);save(ROOT/'raw_anchor.json',anchor)
    save(ROOT/'progress.json',dict(stage='complete',runs=8,shared_curve_points=7,raw_anchor_points=1))
    rows=historical()
    for r in fresh:
        rows.append(dict(series='shared',rate=r['rate'],seconds=r['seconds'],seconds_including_reader_close=r['seconds_including_reader_close'],
            read_GB=r['input_metrics']['charged_file_bytes']/1e9,units=r['units'],spikes=r['spikes'],times_sha256=r['spike_times_sha256'],labels_sha256=r['labels_sha256'],
            stage_seconds=r['stage_seconds'],source=str(ROOT/r['name']/'result.json'),historical=False,reader_metrics=r['reader_metrics']))
    anchor_summary=dict(rate=5000,seconds=anchor['seconds'],units=anchor['units'],spikes=anchor['spikes'],
        times_sha256=anchor['spike_times_sha256'],labels_sha256=anchor['labels_sha256'],read_GB=anchor['input_metrics']['charged_file_bytes']/1e9)
    new_high=next(r for r in fresh if r['rate']==5000)
    anchor_summary['contemporaneous_raw_over_shared']=anchor['seconds']/new_high['seconds']
    anchor_summary['same_arrays_as_new_shared']=(anchor['spike_times_sha256'],anchor['labels_sha256'])==(new_high['spike_times_sha256'],new_high['labels_sha256'])
    comparisons=[]
    for rate in RATES:
        raw=next(r for r in rows if r['series']=='raw' and r['rate']==rate)
        old=next(r for r in rows if r['series']=='old_compressed' and r['rate']==rate)
        new=next(r for r in rows if r['series']=='shared' and r['rate']==rate)
        for r in (raw,old,new):r['observed_raw_over_method']=raw['seconds']/r['seconds']
        comparisons.append(dict(rate=rate,raw_historical_seconds=raw['seconds'],compressed_historical_seconds=old['seconds'],shared_fresh_seconds=new['seconds'],
            observed_raw_over_shared=raw['seconds']/new['seconds'],observed_time_saved_vs_raw_percent=100*(1-new['seconds']/raw['seconds']),
            observed_time_saved_vs_old_compressed_percent=100*(1-new['seconds']/old['seconds']),shared_read_GB=new['read_GB'],
            read_saved_vs_raw_percent=100*(1-new['read_GB']/raw['read_GB']),
            same_arrays_as_historical_raw=(new['times_sha256'],new['labels_sha256'])==(raw['times_sha256'],raw['labels_sha256']),
            same_arrays_as_historical_compressed=(new['times_sha256'],new['labels_sha256'])==(old['times_sha256'],old['labels_sha256'])))
    new_identity=len({(r['spike_times_sha256'],r['labels_sha256']) for r in fresh})==1
    historical_pairs={(r['times_sha256'],r['labels_sha256']) for r in rows if r['historical']}
    matches_known={str(r['rate']):(r['spike_times_sha256'],r['labels_sha256']) in historical_pairs for r in fresh}
    save(ROOT/'curve_data.json',rows);save(ROOT/'comparisons.json',comparisons)
    scope_diagnostics=[]
    for run in fresh:
        scopes={}
        for p in (ROOT/run['name']/'reader_stats').glob('*.jsonl'):
            if p.name=='loaders.jsonl':continue
            for line in p.read_text(encoding='utf-8').splitlines():
                reader=json.loads(line);shared=reader.get('shared_stats')
                if not shared:continue
                scope=scopes.setdefault(shared['scope'],dict(requested=set(),decode_calls=0,shared_hits=0,shared_copy_bytes=0))
                scope['requested'].update(reader['requested_blocks']);scope['decode_calls']+=reader['statistics']['decoded_blocks']
                scope['shared_hits']+=shared['hits'];scope['shared_copy_bytes']+=shared['copied_bytes']
        for name,scope in scopes.items():
            requested=len(scope.pop('requested'))
            scope_diagnostics.append(dict(rate=run['rate'],scope=name,unique_requested_blocks=requested,
                exactly_one_decode_per_requested_block=scope['decode_calls']==requested,**scope))
    save(ROOT/'scope_cache_diagnostics.json',scope_diagnostics)
    save(ROOT/'raw_anchor_comparison.json',anchor_summary)
    save(ROOT/'output_identity.json',dict(all_seven_new_identical=new_identity,
        each_new_matches_a_historical_array_pair=matches_known,
        historical_unit_counts=sorted({r['units'] for r in rows if r['historical']}),comparisons=comparisons,
        caution='Historical outputs vary; historical runtime ratios are descriptive comparisons, not proof of equal-output speedup.'))
    with (ROOT/'timings.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(comparisons[0]));writer.writeheader();writer.writerows(comparisons)
    with (ROOT/'stage_timings.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['series','rate','historical','stage','seconds'])
        for r in rows:
            for stage,seconds in r['stage_seconds'].items():writer.writerow([r['series'],r['rate'],r['historical'],stage,seconds])
    manifest=load(OLD/'source_manifest.json');changed=[]
    for name,digest in manifest['sha256'].items():
        if hashlib.sha256((Path(r'D:\ChronoSort')/name).read_bytes()).hexdigest()!=digest:changed.append(name)
    prior=Path(r'D:\ChronoSort\artifacts\worker_cache_compare_20261103')
    integrity=dict(source_commit=manifest['git_commit'],changed_files=changed,matches_snapshot=not changed,
        git_status=subprocess.check_output(['git','status','--short'],cwd=r'D:\ChronoSort',text=True),
        ephypress_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=r'D:\EphyPress',text=True).strip(),
        ephypress_git_status=subprocess.check_output(['git','status','--short'],cwd=r'D:\EphyPress',text=True),
        shared_implementation_identical_to_five_minute_test={name:(SCRIPT/name).read_bytes()==(prior/name).read_bytes() for name in ['policy.py','shared_cache.py','bandwidth_adapter.py','sitecustomize.py']})
    save(ROOT/'source_integrity.json',integrity)
    environment=dict(gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv'],text=True),
        source=manifest['git_commit'],historical_environment=load(OLD/'chronosort_raw_5000MBps/protocol.json'))
    software_code="import sys,json,importlib.metadata as m; print(json.dumps(dict(python=sys.version,versions={p:m.version(p) for p in ['torch','numpy','ephypress','isosplit6','triton-windows']})))"
    environment['current_software']=json.loads(subprocess.check_output([str(PY),'-c',software_code],text=True))
    save(ROOT/'environment.json',environment)
    code=ROOT/'experiment_code';code.mkdir(exist_ok=True)
    for p in SCRIPT.iterdir():
        if p.suffix in ('.py','.js','.html'):shutil.copy2(p,code/p.name)
    save(code/'sha256.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in code.iterdir() if p.suffix in ('.py','.js','.html')})
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    labels={'raw':'Raw（历史）','old_compressed':'EphyPress 旧预测（历史）','shared':'EphyPress 调度感知＋共享缓存（新测）'}
    colors={'raw':'#64748b','old_compressed':'#3b82f6','shared':'#10b981'}
    fig,axes=plt.subplots(1,3,figsize=(17,6.8))
    for key in ('raw','old_compressed','shared'):
        seq=sorted([r for r in rows if r['series']==key],key=lambda r:r['rate']);style='-' if key=='shared' else '--'
        for ax,values in zip(axes,[[r['seconds']/60 for r in seq],[r['observed_raw_over_method'] for r in seq],[r['read_GB'] for r in seq]]):
            ax.plot(RATES,values,style,marker='o',label=labels[key],color=colors[key],linewidth=2)
    for ax,title in zip(axes,['完整 ChronoSort 耗时（分钟）','相对历史 raw 的观测耗时比','累计计费输入读取量（GB）']):
        ax.set_xscale('log');ax.set_xticks(RATES,labels=[str(r) for r in RATES],rotation=35);ax.set_xlabel('输入字节交付上限（MB/s，对数轴）');ax.set_title(title);ax.grid(alpha=.2);ax.spines[['top','right']].set_visible(False)
    axes[0].set_ylim(bottom=0);axes[2].set_ylim(bottom=0)
    axes[0].scatter([5000],[anchor['seconds']/60],marker='*',s=130,color='#a855f7',label='Raw 同轮5000锚点',zorder=5)
    fig.legend(*axes[0].get_legend_handles_labels(),loc='lower center',ncol=2,bbox_to_anchor=(.5,.005),fontsize=10)
    fig.suptitle('ProbeB-AP 前30分钟 · 新测共享缓存七档曲线',fontsize=15)
    fig.text(.5,.115,'历史输出存在576/624两种 unit 数；耗时比为描述性对照。各新档位1次；写入不限速。',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.18,1,.95));fig.savefig(ROOT/'chronosort_shared_cache_curve.png',dpi=180);fig.savefig(ROOT/'chronosort_shared_cache_curve.pdf');plt.close(fig)
    payload=json.dumps(dict(rows=rows,comparisons=comparisons,identical=new_identity,integrity=integrity,anchor=anchor_summary),ensure_ascii=False)
    template=(SCRIPT/'report_template.html').read_text(encoding='utf-8');page=template.replace('__DATA__',payload)
    anchor_svg="""if(metric==='seconds'){const ax=x(5000),ay=y(DATA.anchor.seconds/60);svg+='<polygon points="'+ax+','+(ay-8)+' '+(ax-7)+','+(ay+6)+' '+(ax+7)+','+(ay+6)+'" fill="#a855f7"><title>同轮 raw 5000 MB/s · '+duration(DATA.anchor.seconds)+'</title></polygon>';}"""
    page=page.replace("svg+='<text x=\"'+W/2",anchor_svg+"svg+='<text x=\"'+W/2")
    page=page.replace('</div><p class="muted">悬停数据点','<span><i class="dot" style="background:#a855f7"></i>同轮 Raw 5000锚点（仅耗时视图）</span></div><p class="muted">悬停数据点')
    if all(matches_known.values()):
        extra=json.dumps(' 新测7档各自均能与某个已有历史结果的时间及标签数组逐字节对应。',ensure_ascii=False)
        page=page.replace('</script>',f"el('identity').textContent+={extra};</script>")
    (ROOT/'report.html').write_text(page,encoding='utf-8')
    if os.environ.get('ORCA_CHAT_SCRATCH_DIR'):
        Path(os.environ['ORCA_CHAT_SCRATCH_DIR'],'chronosort-shared-cache-curve-30min-20261103.html').write_text(page,encoding='utf-8')
    save(ROOT/'finalization.json',dict(success=True,runs=8,shared_curve_points=7,raw_anchor_points=1,all_new_shared_outputs_identical=new_identity,source_matches=not changed))
    print(json.dumps(comparisons,ensure_ascii=True,indent=2),flush=True)

if __name__=='__main__':main()
