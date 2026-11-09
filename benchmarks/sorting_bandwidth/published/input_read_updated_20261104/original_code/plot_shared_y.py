import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path(r'F:\EphyPress_benchmarks\bandwidth_30min_updated_shared_cache_20261104')
rows=json.loads((root/'results.json').read_text(encoding='utf-8'))
lookup={(r['sorter'],r['kind'],r['bandwidth_MB_s']):r for r in rows}
rates=[50,100,200,500,1000,2000,5000]
plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
fig,axes=plt.subplots(1,2,figsize=(12.8,5.5),sharex=True,sharey=True)
for ax,sorter,title in zip(axes,['ks4','chronosort'],['Kilosort 4.1.7','ChronoSort: updated shared decoded cache']):
    for kind,color in [('raw','#2166ac'),('compressed','#d6604d')]:
        label='Raw input' if kind=='raw' else 'EphyPress input'
        if sorter=='chronosort':label='Raw input (historical)' if kind=='raw' else 'EphyPress shared cache (new)'
        ax.plot(rates,[lookup[(sorter,kind,r)]['minutes'] for r in rates],'o-',color=color,label=label,lw=2)
    ax.set_xscale('log');ax.set_xticks(rates,labels=[str(r) for r in rates],rotation=35)
    ax.set_ylim(0,60);ax.set_yticks(range(0,61,10));ax.tick_params(axis='y',labelleft=True)
    ax.set_xlabel('Shared input bandwidth ceiling (decimal MB/s)');ax.set_ylabel('Complete sorting time (min)')
    ax.set_title(title);ax.grid(alpha=.2);ax.legend(frameon=False,fontsize=10)
assert axes[0].get_ylim()==axes[1].get_ylim()==(0.0,60.0)
fig.suptitle('ProbeB-AP, first 30 min | RTX 5090 / Windows | shared y-axis: 0-60 min',fontsize=14)
fig.text(.5,.065,'21 historical points retained; only 7 ChronoSort EphyPress points replaced with new shared-cache measurements.',ha='center',fontsize=8.5)
fig.text(.5,.022,'Reader-level input cap; writes unthrottled; not physical HDD emulation. Outputs vary across runs; historical comparisons are descriptive.',ha='center',fontsize=8)
fig.tight_layout(rect=[0,.11,1,.94])
for suffix in ('png','pdf'):fig.savefig(root/f'sorting_time_vs_bandwidth_shared_y.{suffix}',dpi=190)
plt.close(fig)
