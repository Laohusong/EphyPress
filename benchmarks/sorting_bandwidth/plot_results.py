"""Regenerate figures and a self-contained HTML report from saved timing rows."""
import argparse
import base64
import csv
import html
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def published_rows():
    rows = []
    for r in read_csv(HERE / 'published/ks4_read_write_20261104/timings.csv'):
        rows.append(dict(sorter='ks4', kind=r['input'], condition=r['io_condition'],
                         rate=int(r['bandwidth_MB_s']), seconds=float(r['seconds']),
                         provenance='KS4 fresh input-only / all-data-read-write sweep',
                         units=int(r['units']), spikes=int(r['spikes'])))
    for r in read_csv(HERE / 'published/input_read_updated_20261104/timings.csv'):
        if r['sorter'] == 'chronosort':
            rows.append(dict(sorter='chronosort', kind=r['kind'], condition='input_read_only',
                             rate=int(r['bandwidth_MB_s']), seconds=float(r['sorting_seconds']),
                             provenance=r['measurement_batch'], units=int(r['units']), spikes=int(r['spikes'])))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', type=Path, help='Fresh run results.json; omit for bundled published results')
    p.add_argument('--output', type=Path, default=HERE / 'summary')
    args = p.parse_args()
    if args.results:
        runs = json.loads(args.results.read_text(encoding='utf-8'))
        rows = [dict(sorter=r['sorter'], kind=r['kind'], condition=r['io_condition'], rate=r['rate'],
                     seconds=r['seconds'], units=r['units'], spikes=r['spikes'], provenance=r['name']) for r in runs]
    else:
        rows = published_rows()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    fields = ['sorter', 'kind', 'condition', 'rate', 'seconds', 'units', 'spikes', 'provenance']
    with (out / 'timings.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'pdf.fonttype': 42, 'axes.spines.top': False, 'axes.spines.right': False})
    images = []
    comparison = []
    for sorter in sorted({r['sorter'] for r in rows}):
        own = [r for r in rows if r['sorter'] == sorter]
        fig, ax = plt.subplots(figsize=(8, 4.7))
        for condition, style in [('input_read_only', '-'), ('all_read_write', '--')]:
            for kind, color in [('raw', '#2775b6'), ('compressed', '#da7826')]:
                subset = [r for r in own if r['condition'] == condition and r['kind'] == kind]
                if not subset:
                    continue
                rates = sorted({r['rate'] for r in subset})
                values = [statistics.median(r['seconds'] for r in subset if r['rate'] == rate) / 60 for rate in rates]
                label = f'{"Raw" if kind == "raw" else "EphyPress"} / {"input reads" if condition == "input_read_only" else "all reads + writes"}'
                ax.plot(rates, values, marker='o', linestyle=style, color=color, label=label)
        ax.set_xscale('log')
        rates = sorted({r['rate'] for r in own})
        ax.set_xticks(rates, [str(x) for x in rates])
        ax.set_ylim(0, max(r['seconds'] for r in own) / 60 * 1.1)
        ax.set_xlabel('Application logical bandwidth ceiling (decimal MB/s)')
        ax.set_ylabel('Sorting API wall time (min)')
        ax.set_title('KS4: native padded 60000-sample batches' if sorter == 'ks4'
                     else 'ChronoSort: core 62000 + 1768 context per side')
        ax.grid(alpha=.25)
        ax.legend(fontsize=8)
        fig.tight_layout()
        name = f'{sorter}_bandwidth'
        fig.savefig(out / f'{name}.png', dpi=180)
        fig.savefig(out / f'{name}.pdf')
        plt.close(fig)
        images.append((sorter, name))
        for condition in ['input_read_only', 'all_read_write']:
            for rate in rates:
                a = [r['seconds'] for r in own if r['condition'] == condition and r['rate'] == rate and r['kind'] == 'raw']
                b = [r['seconds'] for r in own if r['condition'] == condition and r['rate'] == rate and r['kind'] == 'compressed']
                if a and b:
                    comparison.append(dict(sorter=sorter, condition=condition, rate=rate,
                        raw_seconds=statistics.median(a), compressed_seconds=statistics.median(b),
                        raw_over_compressed=statistics.median(a) / statistics.median(b)))
    (out / 'comparisons.json').write_text(json.dumps(comparison, indent=2), encoding='utf-8')
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>EphyPress sorting bandwidth benchmark</title><style>body{font:16px/1.65 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#183044;background:#f6f8fb}img{max-width:100%;background:white;border-radius:12px}table{border-collapse:collapse;width:100%;background:white}td,th{padding:9px;border-bottom:1px solid #d9e2e9;text-align:right}td:first-child,th:first-child{text-align:left}code{background:#e8edf3;padding:2px 5px}</style>',
        '<h1>EphyPress: KS4 and ChronoSort bandwidth benchmark</h1>']
    if not args.results:
        parts += ['<p>First 30 minutes of ProbeB-AP; 30 kHz, 384 channels, int16. One run per point. Windows 10 / RTX 5090; EphyPress 0.2.0; KS4 4.1.7. ',
            'ChronoSort uses a 62000-sample valid core with 1768 context samples per side and a bounded cross-worker shared decode cache for compressed input.</p>',
            '<p><strong>All-data read/write measurements are not available for this ChronoSort configuration.</strong> Only the two input-read-limited curves are shown. ',
            'Raw uses historical controls; the compressed curve comes from seven subsequent runs. These are not contemporaneous paired repetitions. The 60000-sample zero-context version is excluded.</p>',
            '<p>The 28 KS4 points across both conditions come from a separate sweep. Original input values were verified exactly, but GPU clustering can change output counts; final arrays are not identical at every point.</p>']
    else:
        parts += ['<p>This report was generated from a new results.json. Recording duration, hardware, seeds, and detailed I/O counters are recorded in dataset.json, environment.json, and each task\'s result.json in the run directory.</p>']
    parts += ['<p>Input-read limits apply only to original recording reads. All-data read/write limits use one shared read budget for original input and instrumented intermediates, plus a separate shared write budget; each direction uses the specified MB/s ceiling. ',
        'This is application-level logical-byte delivery throttling, not a physical HDD test. OS file-cache hits are charged; decoded-cache hits and RAM reuse are not file reads. ',
        'Imports, DLLs, filesystem metadata, and benchmark logs are excluded. Timing spans the public sorting API through final export and CUDA synchronization; initial CUDA setup and KS4 probe/reader construction are outside the timer.</p>']
    for sorter, name in images:
        encoded = base64.b64encode((out / f'{name}.png').read_bytes()).decode()
        parts.append(f'<h2>{html.escape(sorter)}</h2><img alt="{sorter} bandwidth curve" src="data:image/png;base64,{encoded}">')
    parts.append('<h2>Elapsed time and speedup</h2><table><tr><th>Sorter / condition</th><th>MB/s</th><th>Raw (s)</th><th>EphyPress (s)</th><th>Raw / EphyPress</th></tr>')
    for r in comparison:
        parts.append(f'<tr><td>{r["sorter"]} / {r["condition"]}</td><td>{r["rate"]}</td><td>{r["raw_seconds"]:.2f}</td><td>{r["compressed_seconds"]:.2f}</td><td>{r["raw_over_compressed"]:.3f}×</td></tr>')
    parts.append('</table><p>Individual values: timings.csv. Ratios: comparisons.json. Setup and reproduction instructions are in the parent README.md; historical evidence and experiment code are in published/. Figure y-axes start at zero; all four KS4 curves share the same y-axis.</p></html>')
    (out / 'report.html').write_text(''.join(parts), encoding='utf-8')
    print(out / 'report.html', flush=True)


if __name__ == '__main__':
    main()
