# Release validation

## Automated tests

The suite checks exact int16 reconstruction including extrema, FSE/Zstd and
temporal/spatiotemporal prediction, storage/consumer boundary mismatches, padding, fancy/reverse
indices, retained views after reader close, corruption detection, atomic output
publication and conflicting output files. It also checks native Windows-compatible positioned I/O, Unicode paths,
binary control bytes, the installed CLI, SpikeInterface metadata and
JSON reload in a fresh process, and native KS4 padded batches.

The 24-test suite passes locally with CPython 3.12 with NumPy 1.26.4 + SpikeInterface 0.103.1 and NumPy
2.5.4 + SpikeInterface 0.105.1, with KS4 4.1.7. CI independently installs/builds
the package on Linux/macOS/Windows and CPython 3.10/3.12/3.13. The Linux and Windows CPU KS4 jobs install a
CPU PyTorch build; real GPU sorting is an opt-in check rather than a CI fixture.

## Real recording and complete sorting

The independent package was used on the same 60-second real ProbeA prefix as the
research comparison: 384 channels, 30kHz, 1800000 rows, 1382400000 raw bytes.
Raw SHA256:
`4ced250fc348bad8317ab1d335077a7da9e0b79722c05b3d3578977c48279252`.

- EphyPress wrote a new temporal-prediction archive and verified every original value and SHA256.
- Raw/native KS4, EphyPress/native KS4 and EphyPress/SpikeInterface KS4 each
  completed the full pipeline on that complete 60s prefix in separate processes.
- Both compressed routes exported 80106 spikes and 118 units, identical to the
  raw run. Direct and SpikeInterface routes each had event F1=1.0 against raw,
  and the exported spike times and cluster labels were exactly equal.
- The SI sorter used `use_binary_file=False` and `save_preprocessed_copy=False`;
  no full `recording.dat` copy was created.

These runs used EphyPress 0.2.0, NumPy 2.5.4, SpikeInterface 0.105.1, KS4 4.1.7,
Torch 2.8.0+cu128, an RTX5090, seed1, batch60000 and eight numeric threads. Each
path was run once as an integration validation; it is not a repeated speed
benchmark or a cross-dataset accuracy certification. The data and large sorting
outputs remain local and are not distributed in this repository.

## Earlier research performance reference

Before packaging, the predecessor implementation was measured on this same
60-second prefix. With NumPy 1.26.4 + KS4 4.1.7, three repetitions produced these
median complete sorting results:

| Input | Complete KS4 seconds | Mean process CPU | Peak RSS GiB | Event F1 vs raw |
| --- | ---: | ---: | ---: | ---: |
| raw | 27.210 | 235.9% | 2.267 | reference |
| temporal prediction / mapped + prefetch4 | 29.344 | 318.1% | 3.012 | 99.9822% |
| mtscomp 1.0.2 / synchronous Reader | 58.252 | 163.8% | 2.631 | 99.9822% |

100% CPU means one logical CPU. The earlier temporal-prediction archive ratio was 1.9507x;
mtscomp was 2.5165x. Those results describe the predecessor and its specific
reader configurations, not a speed guarantee for this package or all possible
mtscomp optimizations. They used warm input caches on a shared host. Raw's own
sorting repeats had F1=99.9822%–100%, indicating small pipeline variability even
without compression. Different NumPy/framework versions can produce different
sorting outputs, so comparisons should keep the entire environment fixed.

## Reproduce with your data

Install the `all` extra and a working GPU runtime. Then use a fresh directory:

```bash
python tools/validate_real_recording.py --raw continuous.dat --probe ProbeA.json \
  --channels 384 --output artifacts/my_validation --duration 60
```

The full supplied file is compressed/verified; `--duration` limits sorting only.
Use an actual 60-second raw prefix to reproduce this scope. The tool records
versions, output counts and per-path logs. Assess sorting agreement within one
environment; equal ADC bytes do not promise deterministic GPU clustering.

Version 0.2 removes the previous file layouts and compatibility fixtures.
Positioned reads explicitly test the Windows seek/read fallback under concurrent
load; platform CI runs native Windows builds and KS4 padded reads. Release
wheels are built and roundtripped on x86_64/ARM64 native runners.
