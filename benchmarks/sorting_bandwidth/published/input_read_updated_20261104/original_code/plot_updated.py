"""Replace exactly the seven ChronoSort compressed-input points; no sorting reruns."""
import copy,csv,hashlib,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OLD=Path(r'F:\EphyPress_benchmarks\bandwidth_30min_20261103')
NEW=Path(r'F:\EphyPress_benchmarks\shared_cache_curve_30min_20261103')
OUT=Path(r'F:\EphyPress_benchmarks\bandwidth_30min_updated_shared_cache_20261104')
OUT.mkdir(parents=True,exist_ok=True)
rates=[50,100,200,500,1000,2000,5000]
old=json.loads((OLD/'results.json').read_text(encoding='utf-8'))
fresh=json.loads((NEW/'results.json').read_text(encoding='utf-8'))
assert len(old)==28 and len(fresh)==7
new_lookup={r['rate']:r for r in fresh};assert set(new_lookup)==set(rates)
rows=[];preserved=[];replaced=[]
for original in old:
    row=copy.deepcopy(original);key=(row['sorter'],row['kind'],row['bandwidth_MB_s'])
    if key[:2]==('chronosort','compressed'):
        replacement=new_lookup[key[2]];assert replacement['status']=='success'
        row.update(sorting_seconds=replacement['seconds'],spikes=replacement['spikes'],units=replacement['units'],
            input_metrics=replacement['input_metrics'],stage_seconds=replacement['stage_seconds'],
            times_sha256=replacement['spike_times_sha256'],labels_sha256=replacement['labels_sha256'],
            measurement_batch='new_shared_cache',source_result=str(NEW/replacement['name']/'result.json'))
        replaced.append(key)
    else:
        assert row==original
        row.update(measurement_batch='historical_original',source_result=str(OLD/(row['name']+'.json')))
        preserved.append(key)
    row['minutes']=row['sorting_seconds']/60
    row['charged_file_GB']=row['input_metrics']['charged_file_bytes']/1e9
    rows.append(row)
assert len(preserved)==21 and len(replaced)==7
lookup={(r['sorter'],r['kind'],r['bandwidth_MB_s']):r for r in rows};assert len(lookup)==28
with (OUT/'timings.csv').open('w',encoding='utf-8-sig',newline='') as f:
    fields=['sorter','kind','bandwidth_MB_s','sorting_seconds','minutes','spikes','units','charged_file_GB','measurement_batch','source_result']
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(sorted(rows,key=lambda r:(r['sorter'],r['kind'],r['bandwidth_MB_s'])))
(OUT/'results.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding='utf-8')

plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
colors={'raw':'#2166ac','compressed':'#d6604d'}
fig,axes=plt.subplots(1,2,figsize=(12.8,5.5),sharex=True)
for ax,sorter,title in zip(axes,['ks4','chronosort'],['Kilosort 4.1.7','ChronoSort: updated shared decoded cache']):
    for kind in ['raw','compressed']:
        values=[lookup[(sorter,kind,r)]['minutes'] for r in rates]
        if sorter=='ks4':label='Raw input' if kind=='raw' else 'EphyPress input'
        else:label='Raw input (historical)' if kind=='raw' else 'EphyPress shared cache (new)'
        ax.plot(rates,values,'o-',color=colors[kind],label=label,lw=2)
    ax.set_xscale('log');ax.set_xticks(rates,labels=[str(r) for r in rates],rotation=35)
    ax.set_xlabel('Shared input bandwidth ceiling (decimal MB/s)');ax.set_ylabel('Complete sorting time (min)')
    ax.set_title(title);ax.grid(alpha=.2);ax.legend(frameon=False,fontsize=10)
fig.suptitle('ProbeB-AP, first 30 min | RTX 5090 / Windows | one run per point',fontsize=14)
fig.text(.5,.065,'21 historical points retained; only 7 ChronoSort EphyPress points replaced with new shared-cache measurements.',ha='center',fontsize=8.5)
fig.text(.5,.022,'Reader-level input cap; writes unthrottled; not physical HDD emulation. Outputs vary across runs; historical comparisons are descriptive.',ha='center',fontsize=8)
fig.tight_layout(rect=[0,.11,1,.94])
fig.savefig(OUT/'sorting_time_vs_bandwidth.png',dpi=190);fig.savefig(OUT/'sorting_time_vs_bandwidth.pdf');plt.close(fig)

comparisons=[]
fig,ax=plt.subplots(figsize=(8.8,5.2))
for sorter,color,label in [('ks4','#4c78a8','Kilosort 4.1.7 (historical)'),('chronosort','#54a24b','ChronoSort (updated shared cache)')]:
    ratios=[]
    for rate in rates:
        a=lookup[(sorter,'raw',rate)];b=lookup[(sorter,'compressed',rate)]
        ratio=a['sorting_seconds']/b['sorting_seconds'];ratios.append(ratio)
        comparisons.append(dict(sorter=sorter,bandwidth_MB_s=rate,raw_seconds=a['sorting_seconds'],compressed_seconds=b['sorting_seconds'],
            observed_raw_over_compressed=ratio,time_saved_percent=100*(1-b['sorting_seconds']/a['sorting_seconds'])))
    ax.plot(rates,ratios,'o-',lw=2,color=color,label=label)
ax.axhline(1,color='#888888',ls='--',lw=1);ax.set_xscale('log');ax.set_xticks(rates,labels=[str(r) for r in rates])
ax.set_xlabel('Shared input bandwidth ceiling (decimal MB/s)');ax.set_ylabel('Raw time / compressed time')
ax.set_title('Compressed-input sorting: observed runtime ratio');ax.legend(frameon=False);ax.grid(alpha=.2)
fig.text(.5,.015,'Raw reference points are historical; one run per point; differing outputs limit strict equal-workload claims.',ha='center',fontsize=8)
fig.tight_layout(rect=[0,.055,1,1]);fig.savefig(OUT/'compressed_speedup.png',dpi=190);fig.savefig(OUT/'compressed_speedup.pdf');plt.close(fig)
(OUT/'comparisons.json').write_text(json.dumps(comparisons,indent=2),encoding='utf-8')
audit=dict(preserved_points=21,replaced_points=7,no_new_sorting_runs=True,
    replacement='ChronoSort compressed input only; same first30min ProbeB-AP fixture. Schedule-aware prediction plus bounded cross-worker shared decoded cache.',
    original_results=str(OLD/'results.json'),replacement_results=str(NEW/'results.json'),
    preserved_keys=preserved,replaced_keys=replaced,
    source_files_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [OLD/'results.json',NEW/'results.json']},
    all_21_retained_timing_values_exact=all(lookup[(r['sorter'],r['kind'],r['bandwidth_MB_s'])]['sorting_seconds']==r['sorting_seconds'] for r in old if (r['sorter'],r['kind'])!=('chronosort','compressed')),
    all_7_replacement_timing_values_exact=all(lookup[('chronosort','compressed',r)]['sorting_seconds']==new_lookup[r]['seconds'] for r in rates),
    caveats=['Historical raw and KS4 results retained; no current-batch full raw sweep.',
        'ChronoSort historical and new outputs include576/624-unit branches; not an equal-output benchmark at every cap.',
        'Software input-byte-delivery ceiling; intermediate/output reads and writes unthrottled.',
        'Original plots/results remain untouched. No src changes.'])
(OUT/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
lines=['更新后的28点合成图：KS4两条曲线、ChronoSort raw沿用历史结果，仅替换ChronoSort EphyPress七档曲线。',
       '本次仅重新绘图，没有重新执行28组sorting；21个历史点＋7个已完成的共享缓存实测点。',
       '原图及源结果未覆盖。原始数据：同一ProbeB-AP前30分钟。',
       '共享缓存新结果来自：'+str(NEW),
       'ChronoSort新旧结果存在576/624 units两种输出，耗时比仅作描述性历史对照。',
       '本轮5000 MB/s raw另测711.763秒，新压缩733.115秒，输出相同；该额外raw点未替换原raw曲线。',
       '读取软件限速，写入不限速，非机械硬盘实测。src未修改。',
       '', 'sorter | MB/s | raw(min) | compressed(min) | raw/compressed']
for c in comparisons:lines.append(f"{c['sorter']} | {c['bandwidth_MB_s']} | {c['raw_seconds']/60:.3f} | {c['compressed_seconds']/60:.3f} | {c['observed_raw_over_compressed']:.3f}")
(OUT/'report.txt').write_text('\n'.join(lines),encoding='utf-8-sig')
print(json.dumps(dict(output=str(OUT),preserved=21,replaced=7,all_exact=audit['all_21_retained_timing_values_exact'] and audit['all_7_replacement_timing_values_exact'])))
