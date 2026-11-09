# Sorting performance under application-level I/O limits

This directory contains completed timing measurements, per-run I/O counters,
archived experiment code, and a configurable reproduction runner.
**ChronoSort results use a 62000-sample valid core with 1768 context samples on
each side.** The 60000-sample, zero-context ChronoSort experiment is excluded.
KS4 retains its native 60000-sample batches and boundary context. These
benchmarks do not modify sorter algorithms or product `src` files.

## Included results

| Primary results | Data | Conditions | Measurement provenance |
|---|---|---|---|
| KS4: 28 points | First 30 minutes of ProbeB-AP | 7 bandwidths x raw/compressed x input-read-only/all-data-read-write limits | Separate sweep on 2026-11-04; one run per point |
| ChronoSort: 14 points | Same 30-minute recording | 7 bandwidths x raw/compressed; input reads limited | Raw: historical 2026-11-03 controls. Compressed: 7 subsequent shared-cache runs |
| ChronoSort: all-data read/write limits | Not available | **No measurements for this 62000-sample contextual configuration** | Results from other segment configurations are not substituted |

Bandwidth ceilings are **50, 100, 200, 500, 1000, 2000, and 5000 MB/s**, using
decimal MB. The 42 primary rows are not one contemporaneous 42-run experiment;
see the `provenance` column in `summary/timings.csv`.
Earlier input-only results, the shared-cache experiment, and the combined
replacement curves are archived in `published/`. They are not additional
independent repetitions of the primary results.

- [Self-contained HTML report](summary/report.html)
- [Primary timing CSV](summary/timings.csv) and [speedup comparisons](summary/comparisons.json)
- [KS4 figure](summary/ks4_bandwidth.png) and [PDF](summary/ks4_bandwidth.pdf)
- [ChronoSort figure](summary/chronosort_bandwidth.png) and [PDF](summary/chronosort_bandwidth.pdf)

## Fixed data and environment

- ProbeB-AP, first 1800 seconds, 30000 Hz, 384 channels, time-major little-endian int16.
- Raw: 54,000,000 samples, 41,472,000,000 bytes; SHA256:
  `b3f6ffaf23681be08af594a485aad7809aa2e7c37a5befb78656b2a436425499`.
- Compressed: 23,227,387,437 bytes, 900 blocks of 60000 samples;
  `temporal` prediction, FSE entropy coding, Zstd level 3, and 4 encoding workers.
- EphyPress 0.2.0, commit `8cb51381919ecbe1bf37ddaffbf81cbfbf260ce3`.
- Windows 10 19045, RTX 5090 (32 GB), driver 610.88; Python 3.11.14,
  Torch 2.9.1+cu128, KS4 4.1.7, and NumPy 1.26.4.
- Seed 1; 8 numerical threads. KS4 uses `batch_size=60000`,
  `cluster_init_seed=1`, and `save_preprocessed_copy=False`.
- ChronoSort uses the frozen source associated with commit
  `9bc7b8a5011b3fd20cea1ddee2276aa85948c6ec`; file hashes are in
  `fixture/source_manifest.json`. The `standard` single-session pipeline runs
  through final quality filtering and export, with a 4 GiB GPU owner allowance.
  Its bounded shared decode cache is isolated by loader: 7 shared slots plus
  1 locally retained block per worker, single-flight decoding, and
  schedule-aware prefetch. Consecutive-window grouped dispatch is not enabled.

The recording is not distributed with this repository. Supply your own copy.
The geometry in `fixture/ks4_probe.json` and `chronosort_probe.json` is
**specific to this ProbeB recording** and must not be applied to arbitrary probes.
`fixture/subset.json` records the original path and recording provenance;
`compression.json` and `verification.json` preserve compression and exact-value
verification records. `ks4_effective_settings_30min.json` records the original
effective KS4 settings, and `ks4_source_manifest.json` records installed KS4
Python source hashes for audit.

## I/O model and interpretation

`input_read_only`: limit original raw-file reads or actual compressed-file
payload reads. Other instrumented reads and writes are counted but not limited.

`all_read_write`: original input and instrumented intermediate-file reads share
one read budget. Data writes share a separate, independent write budget.
At 50 MB/s, reads may proceed at 50 MB/s while writes proceed at 50 MB/s.
Each direction's budget is shared across all workers and threads. Both
conditions use the same I/O hooks.

These are **application-level logical-byte delivery ceilings**, not OS-level
disk limits or physical HDD simulations. OS file-cache hits are charged;
decoded-cache hits and in-memory reuse are not file reads. Instrumentation
covers the original input, task `run/` or `results/`, task temporary files,
specified probes, and ChronoSort resources. Imports, DLL loading, filesystem
metadata, benchmark logs, and files outside those scopes are excluded.
Mapped-array accesses are explicitly charged. One-dimensional iteration
preserves native order and accounts for 64 KiB read-ahead blocks. Instrumentation
and explicit memory copies add overhead.

Timing spans the public sorting API through final export and CUDA synchronization.
Imports, initial CUDA setup, KS4 probe loading, and reader construction are
outside the timer. The reproduction runner subtracts pre-timer I/O counters.
Decoded caches are not reused between sorting processes; no full decoded
recording or existing sorting checkpoints are reused. Before each sweep, raw,
archive, and probe hashes are checked again. Those reads warm the file cache
outside the timed region.

Each historical point is a single run without confidence intervals. GPU
clustering may choose different branches, changing unit counts and spike-array
hashes. Exact input equality does not guarantee identical sorting outputs.
The historical ChronoSort raw controls and later compressed runs are not
contemporaneous pairs, so their differences cannot all be attributed to compression.
An early CRC failure is documented in `fixture/crc_incident.json` and the
archive. Failed attempts are excluded from valid curves, not hidden or
automatically retried.

## Standalone KS4 reproduction

`benchmark.py` and `worker.py` run KS4 on Windows without a ChronoSort checkout
or the original machine's F-drive experiment directories. `runtime/` installs
I/O hooks only in benchmark subprocesses; it does not edit EphyPress, KS4, or
ChronoSort source. The current IPC hooks are **validated on Windows only**.

Run these PowerShell commands from the EphyPress repository root. Use Python
3.11 and a compatible NVIDIA GPU environment. Installing EphyPress from source
requires the C++ build tools described in the project documentation; a matching
prebuilt wheel can also be used.

```powershell
python -m venv .venv-bandwidth
$py = '.\.venv-bandwidth\Scripts\python.exe'
& $py -m pip install --upgrade pip
& $py -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cu128
& $py -m pip install -r benchmarks/sorting_bandwidth/requirements-windows.txt
& $py -m pip install -e '.[ks4]'
```

Copy the first 30 minutes, compress them, and verify every value to produce
`dataset.json`. The output directory must be new.

```powershell
& $py benchmarks/sorting_bandwidth/benchmark.py prepare `
  --source-raw 'F:\your-recording\ProbeB-AP\continuous.dat' `
  --duration 1800 --channels 384 --fs 30000 `
  --probe benchmarks/sorting_bandwidth/fixture/ks4_probe.json `
  --output artifacts/bandwidth_data
```

If the raw/compressed 30-minute pair already exists, verify and register it
without copying or recompressing it:

```powershell
& $py benchmarks/sorting_bandwidth/benchmark.py register `
  --raw 'F:\existing\first30min.dat' --archive 'F:\existing\first30min.ep' `
  --probe benchmarks/sorting_bandwidth/fixture/ks4_probe.json `
  --output artifacts/bandwidth_registered
```

The default run executes all 28 KS4 combinations in fresh processes, with GPU
jobs serialized. It records the environment, effective settings, input and
intermediate I/O bytes, units, spikes, and output hashes.

```powershell
& $py benchmarks/sorting_bandwidth/benchmark.py run `
  --data artifacts/bandwidth_data/dataset.json --output artifacts/ks4_bandwidth
& $py benchmarks/sorting_bandwidth/plot_results.py `
  --results artifacts/ks4_bandwidth/results.json --output artifacts/ks4_bandwidth/report
```

For an initial four-case smoke test, use `prepare --duration 60` and
`run --rates 5000`. Use `run --dry-run` to create a plan without sorting.
`--rates 50 5000` selects two ceilings; `--conditions all_read_write` selects
only the read/write condition. `--repeats 3` repeats the sweep, and plotting
uses medians. Reproducing the comparison requires matching hardware/software,
recording interval, probe, and I/O model; exact elapsed times and GPU clustering
outputs are not guaranteed.

## ChronoSort reproduction: 62000 samples with context

KS4 does not depend on this section. ChronoSort requires its frozen source and
dependencies, rather than the actively developed current `src`.
`--chronosort-root` must contain `src/` and `resources/`. The source must match
`fixture/source_manifest.json` file by file or execution is refused.
The commit identifies the revision; full source hashes are authoritative
because a commit alone does not capture uncommitted changes.

When preparing the data, also pass:

```powershell
  --chrono-probe benchmarks/sorting_bandwidth/fixture/chronosort_probe.json
```

Then run:

```powershell
& $py benchmarks/sorting_bandwidth/benchmark.py run `
  --data artifacts/bandwidth_data_with_chrono_probe/dataset.json `
  --output artifacts/chrono_62000_bandwidth `
  --sorters chronosort --chronosort-root 'D:\frozen_chronosort'
```

This command supports both conditions and can measure the missing contextual
ChronoSort read/write curves. **Unmeasured curves are not presented as results.**
No segment transformation or zero-context profile is installed; the frozen
source's native 62000 + 1768 x 2 configuration is used.

## Files and validation

| Path | Purpose |
|---|---|
| `benchmark.py` / `worker.py` | Configurable preparation, verification, and serial execution; KS4 is independent |
| `runtime/` | Adapted I/O hooks; KS4 skips ChronoSort imports |
| `plot_results.py` | Rebuild PNG, PDF, and self-contained HTML from archives or new `results.json` |
| `check_integrity.py` | Verify archive hashes, the 42 primary points, and missing-condition status |
| `preflight.py` | Check shared multiprocessing budgets, independent read/write budgets, stream/mapped I/O, and cross-block inputs |
| `fixture/` | Recording provenance, geometry, versions, verification, and frozen-source hashes |
| `published/ks4_read_write_20261104/` | 28 KS4 points, original per-run JSON, extracted KS4 function, and instrumentation |
| `published/input_read_original_20261103/` | Original 28-point input-read sweep and experiment code |
| `published/input_read_shared_20261103/` | Contextual ChronoSort shared-cache experiment and code |
| `published/input_read_updated_20261104/` | Combined curves replacing 7 compressed ChronoSort points, with provenance audit |
| `archive_manifest.json` | Historical evidence SHA256 hashes; archived code is separate from the portable adaptation |
| `validation/` | This packaging task's real-data 60-second KS4 smoke tests; excluded from the 30-minute curves |

Archive filename strings in historical evidence and scripts have been migrated
to `.ep`. Timing, recording checksums and measurement values are unchanged.
`archive_manifest.json` stores current hashes and the pre-migration hashes of
affected files. `check_integrity.py` verifies both by reversing only the suffix
substitution. English is the default for maintained documentation,
new reports, figure labels, and reproduction instructions. Archived scripts
retain historical absolute paths; use the top-level `benchmark.py` for new runs.
Recordings, decoded files, binary sorting outputs, and environments are not bundled.

```powershell
& $py benchmarks/sorting_bandwidth/check_integrity.py
& $py benchmarks/sorting_bandwidth/preflight.py --output artifacts/bandwidth_preflight
& $py benchmarks/sorting_bandwidth/plot_results.py
```

The last command rebuilds the primary figures and report from repository CSVs
without a GPU or the recording.

Packaging validation passed four complete 60-second KS4 high-bandwidth cases
and one compressed-input case with independent 50 MB/s read/write limits.
Four-process shared budgets, read/write independence, stream/Torch/mapped I/O
accounting, and KS4-style cross-block input checks also passed. These short
tests validate the runner and are not added to the 30-minute curves;
see `validation/validation.json`.
