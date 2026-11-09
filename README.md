# EphyPress

[![CI](https://github.com/Laohusong/EphyPress/actions/workflows/ci.yml/badge.svg)](https://github.com/Laohusong/EphyPress/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md) | [简体中文](docs/guide.zh-CN.md)

Lossless electrophysiology compression with on-demand access for spike sorting.

## Highlights

- **Nearly 2× lossless compression.** Real Neuropixels recordings achieved **1.8–2×** compression, preserving every `int16` sample. [Measured results](docs/benchmarks.md#lossless-compression)
- **Sort directly from compressed data.** KS4 decodes blocks on demand, without an explicit decompression step or a full raw copy. This can significantly speed up sorting on slow storage, such as HDDs: at a **100 MB/s input-read ceiling**, complete KS4 took **1150 s instead of 1965 s (1.71× faster)**. [Sorting benchmark](docs/benchmarks.md#sorting-from-compressed-data)
- **Fast decompression.** A **30-minute Neuropixels 1.0 recording** (384 channels, 30 kHz; 41.47 GB raw) restored to disk in **46.5 s** in our Windows SSD test, including SHA256 verification and file synchronization. [Decompression benchmark](docs/benchmarks.md#decompression)

## Installation

Use 64-bit Python 3.10+ on Linux, macOS or Windows. Download a matching wheel from
[GitHub Releases](https://github.com/Laohusong/EphyPress/releases/tag/v0.2.0) and install it:

```bash
python -m pip install /path/to/ephypress-0.2.0-...whl
```

For direct KS4 support, install the wheel with the `ks4` extra:

```bash
python -m pip install "/path/to/ephypress-0.2.0-...whl[ks4]"
```

KS4 also needs a compatible [PyTorch/CUDA environment](https://pytorch.org/get-started/locally/)
and your probe geometry. See [source installation and optional integrations](docs/user-guide.md#installation-on-linux-macos-and-native-windows).

## Quick start

### Python: compress and decompress

```python
import ephypress as ep

ep.compress(
    "continuous.dat", "recording.ep",
    n_channels=384, sampling_frequency=30000, workers=4,
)
ep.decompress("recording.ep", "restored.dat")
```

Raw input must be headerless, time-major, little-endian `int16`. Use the actual
file channel count, including any sync channel. Output files must not already exist.

### Command line: compress and decompress

```bash
ephypress compress continuous.dat recording.ep --channels 384 --fs 30000
ephypress decompress recording.ep restored.dat
```

`python -m ephypress` accepts the same commands.

### Python: run KS4 directly on compressed data

```python
import ephypress as ep
from kilosort.io import load_probe

result = ep.run_kilosort(
    "recording.ep",
    probe=load_probe("ProbeA.json"),  # your actual geometry and channel map
    results_dir="ks4_output",
    settings={"batch_size": 60000},
    save_preprocessed_copy=False,
)
```

Samples are decoded into bounded RAM buffers as KS4 requests them. The helper
reads the sample rate and channel count from the archive. Use a new or empty
results directory. This runs sorting on an existing `.ep` file.

## Documentation

- [Full user guide](docs/user-guide.md): installation, verification, window reads, native KS4 API and Phy
- [SpikeInterface guide](docs/spikeinterface.md): reading, writing, metadata and KS4
- [Benchmark results](docs/benchmarks.md) and [sorting benchmark reproduction](benchmarks/sorting_bandwidth/README.md)
- [File format](docs/format.md) · [Validation](docs/validation.md) · [Contributing](CONTRIBUTING.md)

MIT licensed. See [third-party notices](THIRD_PARTY_NOTICES.md) for bundled components.

## Acknowledgments

We thank the authors and contributors of the following open-source projects:

- [mtscomp](https://github.com/int-brain-lab/mtscomp), used as a reference for electrophysiology compression comparisons.
- [FiniteStateEntropy](https://github.com/Cyan4973/FiniteStateEntropy), whose bundled FSE implementation provides entropy coding.
- [Zstandard](https://github.com/meta/zstd), used for upper-plane compression.
- [SpikeInterface](https://github.com/SpikeInterface/spikeinterface), which provides the recording and sorting interfaces used by our integration.
- [Kilosort](https://github.com/MouseLand/Kilosort), whose public KS4 interface enables direct sorting from compressed recordings.
