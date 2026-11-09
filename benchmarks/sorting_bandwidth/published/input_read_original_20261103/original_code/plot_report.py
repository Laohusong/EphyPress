"""Generate the final auditable speed report only after all 28 jobs succeed."""
import csv,hashlib,json,platform,importlib.metadata
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path(r'F:\EphyPress_benchmarks\bandwidth_30min_20261103')
rows=json.loads((root/'results.json').read_text())
assert len(rows)==28 and all(x['status']=='success' for x in rows)
rates=[50,100,200,500,1000,2000,5000]
lookup={(x['sorter'],x['kind'],x['bandwidth_MB_s']):x for x in rows}
assert len(lookup)==28
for x in rows:
    x['minutes']=x['sorting_seconds']/60
    x['charged_file_GB']=x['input_metrics']['charged_file_bytes']/1e9
    x['whole_sort_average_input_MB_s']=x['input_metrics']['charged_file_bytes']/x['sorting_seconds']/1e6
with (root/'timings.csv').open('w',encoding='utf-8-sig',newline='') as f:
    fields=['sorter','kind','bandwidth_MB_s','sorting_seconds','minutes','spikes','units','charged_file_GB','whole_sort_average_input_MB_s','peak_working_set_bytes','resultdir']
    writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)

plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
colors={'raw':'#2166ac','compressed':'#d6604d'}
fig,axes=plt.subplots(1,2,figsize=(12.8,5),sharex=True)
for ax,sorter,title in zip(axes,['ks4','chronosort'],['Kilosort 4.1.7','ChronoSort: current single-session pipeline']):
    for kind in ['raw','compressed']:
        values=[lookup[(sorter,kind,r)]['minutes'] for r in rates]
        ax.plot(rates,values,'o-',color=colors[kind],label='Raw input' if kind=='raw' else 'EphyPress input',lw=2)
    ax.set_xscale('log');ax.set_xticks(rates,labels=[str(r) for r in rates],rotation=35)
    ax.set_xlabel('Shared input bandwidth ceiling (decimal MB/s)');ax.set_ylabel('Complete sorting time (min)')
    ax.set_title(title);ax.grid(alpha=.2);ax.legend(frameon=False)
fig.suptitle('ProbeB-AP, first 30 min | RTX 5090 / Windows | one run per point',fontsize=14)
fig.text(.5,.015,'Reader-level bandwidth model; output writes unthrottled; normal OS cache; not physical HDD emulation.',ha='center',fontsize=9)
fig.tight_layout(rect=[0,.06,1,.94])
fig.savefig(root/'sorting_time_vs_bandwidth.png',dpi=190);fig.savefig(root/'sorting_time_vs_bandwidth.pdf');plt.close(fig)

fig,ax=plt.subplots(figsize=(8.8,4.8))
comparisons=[]
for sorter,color,label in [('ks4','#4c78a8','Kilosort 4.1.7'),('chronosort','#54a24b','ChronoSort')]:
    ratios=[]
    for rate in rates:
        a=lookup[(sorter,'raw',rate)];b=lookup[(sorter,'compressed',rate)]
        ratio=a['sorting_seconds']/b['sorting_seconds'];ratios.append(ratio)
        comparisons.append(dict(sorter=sorter,bandwidth_MB_s=rate,raw_seconds=a['sorting_seconds'],
            compressed_seconds=b['sorting_seconds'],speedup=ratio,
            compressed_time_reduction_percent=100*(1-b['sorting_seconds']/a['sorting_seconds'])))
    ax.plot(rates,ratios,'o-',lw=2,color=color,label=label)
ax.axhline(1,color='#888888',ls='--',lw=1);ax.set_xscale('log');ax.set_xticks(rates,labels=[str(r) for r in rates])
ax.set_xlabel('Shared input bandwidth ceiling (decimal MB/s)');ax.set_ylabel('Raw time / compressed time')
ax.set_title('Compressed-input sorting speedup (>1 means faster)');ax.legend(frameon=False);ax.grid(alpha=.2)
fig.tight_layout();fig.savefig(root/'compressed_speedup.png',dpi=190);fig.savefig(root/'compressed_speedup.pdf');plt.close(fig)

fig,axes=plt.subplots(1,2,figsize=(12.8,4.7))
for ax,sorter in zip(axes,['ks4','chronosort']):
    for kind in ['raw','compressed']:
        ax.plot(rates,[lookup[(sorter,kind,r)]['charged_file_GB'] for r in rates],'o-',color=colors[kind],label=kind)
    ax.set_xscale('log');ax.set_xticks(rates,labels=[str(r) for r in rates],rotation=35)
    ax.set_xlabel('Shared input bandwidth ceiling (MB/s)');ax.set_ylabel('Cumulative charged input-file bytes (GB)')
    ax.set_title(sorter);ax.grid(alpha=.2);ax.legend(frameon=False)
fig.suptitle('Reader requests across all passes, threads and subprocesses')
fig.tight_layout();fig.savefig(root/'input_bytes.png',dpi=190);fig.savefig(root/'input_bytes.pdf');plt.close(fig)

subset=json.loads((root/'subset.json').read_text());stat=Path(subset['source']).stat()
assert stat.st_size==subset['original_size'] and stat.st_mtime_ns==subset['original_mtime_ns']
manifest=json.loads((root/'source_manifest.json').read_text())
for relative,digest in manifest['sha256'].items():
    assert hashlib.sha256((root/'source_snapshot'/relative).read_bytes()).hexdigest()==digest
summary=dict(status='success',runs=28,comparisons=comparisons,subset=subset,
    compression=json.loads((root/'compression.json').read_text()),
    verification=json.loads((root/'verification.json').read_text()),
    consumer_window_fidelity=json.loads((root/'consumer_window_fidelity.json').read_text()),
    crc_incident=json.loads((root/'crc_incident.json').read_text()),
    source_commit=manifest['git_commit'],snapshot_verified=True,original_size_mtime_unchanged=True,
    caveats=['One run per point; no error bars or statistical significance claims.',
        'Reader byte-delivery model, not physical HDD or OS block-device throttling.',
        'The cap is shared by every thread/process; OS cache hits remain charged.',
        'Native EphyPress decode caches/prefetch remain active; decoded-cache hits do not read file bytes.',
        'High requested ceilings may exceed actual reader/device capacity and may be inactive.',
        'ChronoSort uses an experiment-only EphyPress reader adapter, not the built-in older SPC codec.',
        'ChronoSort initial_cluster_gpu_owner_memory_gib=4.0 in every formal run; default 1.4 GiB exhausted on the pilot.',
        'First successful ChronoSort raw 5000 MB/s call excluded as warmup and rerun last; see warmup_policy.json.',
        'First ChronoSort compressed 5000 MB/s call excluded as a prefetch diagnostic; formal adapter preserves the native ChronoSort WindowPrefetch policy.',
        'Raw reader uses explicit buffered windows instead of memmap to enforce input throttling.',
        'No biological GT; units/spikes are reported for audit, not accuracy scores.'])
summary['environment']={'platform':platform.platform(),'python':platform.python_version(),
    'GPU':'NVIDIA GeForce RTX 5090','packages':{name:importlib.metadata.version(name) for name in
        ['numpy','pandas','scipy','scikit-learn','numba','matplotlib','torch','ephypress','kilosort',
         'zstandard','probeinterface','isosplit6','triton-windows']}}
(root/'environment.json').write_text(json.dumps(summary['environment'],indent=2),encoding='utf-8')
(root/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
lines=['ProbeB-AP 前 30 分钟：读取带宽上限与 sorting 速度对照',
    '主要结果：本次 KS4 在 50–200 MB/s 下耗时减少 37.3%–41.2%，500 MB/s 减少 19.6%，1000 MB/s 减少 8.1%；2000–5000 MB/s 已无收益（单点一次，不做显著性判断）。',
    '当前 ChronoSort EphyPress 适配路径在七档下均更慢，压缩输入耗时增加约 6.0%–38.9%。这一结果仅适用于本次代码、读取适配和限速模型。',
    '累计读取量：KS4 原始 129.70 GB / 压缩 89.11 GB；ChronoSort 原始 110.65 GB / 压缩 159.65 GB。压缩文件更小并不保证排序过程中累计读取更少；跨块访问、缓存及预取值得进一步剖析，不能仅凭本次结果确定各因素的独立贡献。',
    f"数据源：{subset['source']}",
    f"源码快照提交：{manifest['git_commit']}；src 文件未修改。",
    '子集原始大小 41.472 GB，EphyPress 压缩后 23.227 GB（十进制 GB）；压缩总耗时约 72 秒。',
    '范围：0–1800 秒，384 通道，30 kHz。7 档 × 2 输入 × 2 排序器，共 28 次，每点一次。',
    '时间包含排序公共 API 全流程与导出，不包含模块导入和初始 CUDA 预热；输出写入不限速。',
    'KS4 使用完整原生 API（含自带绘图）；ChronoSort 使用 standard 模式、关闭可选绘图，包含最终质量过滤与导出。各排序器内部的原始/压缩配置一致；跨排序器绝对耗时还受流程和导出策略差异影响。',
    '读取字节限速由全部线程与子进程共享。Windows 缓存不绕过额度；解码缓存命中不产生文件读取。',
    '这是读取带宽模型，不等同于机械硬盘测试；高档位仅为上限，不保证实际达到。',
    '原始输入以显式窗口读取替代 memmap 来实施限速；操作系统缓存命中也计入额度。压缩路径保留解码缓存与预取，因此不能把此模型的加速比直接换算成真实硬盘加速比。',
    'ChronoSort 使用任务开始时的最新源码快照及默认单日流程，包含最终质量过滤；EphyPress 读取适配在 src 外。',
    '所有 ChronoSort 运行统一设置 initial_cluster_gpu_owner_memory_gib=4.0；默认 1.4 GiB 在首次尝试中耗尽。',
    '首次成功的 ChronoSort 原始输入 5000 MB/s 运行用作预热并排除；正式同组合在最后重跑。失败与预热日志均保留。',
    '首次高带宽压缩 ChronoSort 运行因通用预取额外读取而作为诊断排除；正式测试复用当前 ChronoSort 的 WindowPrefetch 消费窗口预测策略，并重跑该点。',
    '', '排序器 | MB/s 上限 | 原始耗时(min) | 压缩耗时(min) | 原始/压缩加速比']
for c in comparisons:lines.append(f"{c['sorter']} | {c['bandwidth_MB_s']} | {c['raw_seconds']/60:.3f} | {c['compressed_seconds']/60:.3f} | {c['speedup']:.3f}")
lines+=['','详见 experiment_protocol.json、每次 protocol.json、完整日志、timings.csv、summary.json。',
    '所有采样点均保留，未按 sorting 结果筛选；单次数据不用于统计显著性判断。',
    '整段数据另经四个进程、batch size 1 和 2 的消费窗口逐值检查，覆盖全部 30 分钟，两种模式均完全一致；见 consumer_window_fidelity.json。排序输出单元/spike 数存在差异，不能声称排序输出相同。',
    '没有 GT，未作准确率评价；原始数据大小和修改时间保持不变，源码快照内容校验通过。']
lines+=['', '异常记录：100 MB/s KS4 压缩输入的首次尝试报 block 450 CRC 错误，失败尝试排除。独立重读 CRC 正确、整段多进程逐值检查通过、三轮同带宽跨步读取未复现。完整组合重新运行且仍启用 CRC。根因尚未确定，不能宣称已修复。详见 crc_incident.json。']
(root/'report.txt').write_text('\n'.join(lines),encoding='utf-8-sig')
print(json.dumps(comparisons,indent=2))
