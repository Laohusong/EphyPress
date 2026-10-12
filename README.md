# EphyPress

[![CI](https://github.com/Laohusong/EphyPress/actions/workflows/ci.yml/badge.svg)](https://github.com/Laohusong/EphyPress/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Lossless electrophysiology compression, with direct SpikeInterface and Kilosort4 access.**

[中文用户指南](README.zh-CN.md) · [Releases](https://github.com/Laohusong/EphyPress/releases) · [File format](docs/format.md) · [Validation](docs/validation.md)

EphyPress turns headerless `int16` recordings into a single indexed `.spc` file.
You can restore the original bytes, read arbitrary sample windows, or run sorting
directly on compressed data. Decoded blocks are cached in bounded RAM; reading
does not create a full raw data file.

The default **temporal** predictor uses the previous sample in each channel.
The optional **spatiotemporal** predictor also uses neighboring-channel residuals.
Both preserve every int16 ADC value with integer prediction, Zigzag mapping,
four packed low bits, per-channel FSE and a Zstd upper plane. Prediction names
and explicit coefficients are stored in the checked index. FSE is bundled.

## Installation on Linux, macOS and native Windows

Use 64-bit CPython 3.10 or newer. The same CLI, Python, SpikeInterface and KS4
interfaces run natively on all three desktop operating systems. Default readers
select Linux RAM page remapping when available and portable block assembly on
Windows/macOS. Threaded block encoding and prefetch are available everywhere.

[GitHub Releases](https://github.com/Laohusong/EphyPress/releases/tag/v0.2.0)
provides Linux, macOS and native Windows wheels for x86_64 and ARM64. Choose the
wheel for your Python/OS architecture and install it without a compiler:

```bash
python -m pip install /path/to/ephypress-0.2.0-...whl
```

On Windows use a native Python installation and run the same command in
PowerShell or Command Prompt; no Linux subsystem is required. Windows wheels
statically link the compiler C++ runtime. ARM64 Windows requires a native ARM64
Python release (3.11+); select the ARM64 wheel rather than the x86_64 wheel.

### Install from the version tag

Source builds require a native C/C++ compiler: GCC/Clang and Python development
headers on Linux, `xcode-select --install` on macOS, or Microsoft Visual C++ Build
Tools with the C++ workload on Windows.

```bash
python -m pip install "ephypress @ git+https://github.com/Laohusong/EphyPress.git@v0.2.0"
python -m pip install "ephypress[spikeinterface] @ git+https://github.com/Laohusong/EphyPress.git@v0.2.0"
python -m pip install "ephypress[ks4] @ git+https://github.com/Laohusong/EphyPress.git@v0.2.0"
python -m pip install "ephypress[all] @ git+https://github.com/Laohusong/EphyPress.git@v0.2.0"
```

The initial distribution is hosted on GitHub, so the commands use an explicit
repository URL. GPU sorting additionally needs a compatible PyTorch/CUDA build
and real probe geometry; follow the [Kilosort guide](https://github.com/MouseLand/Kilosort#instructions)
and [PyTorch selector](https://pytorch.org/get-started/locally/).

### Format version

Version 0.2 uses the EphyPress v1 container and descriptive prediction names.
Earlier archive layouts are unsupported; recompress the original int16 data.
The file extension remains `.spc`.

## Input format

The raw file must have no header and contain **little-endian signed 16-bit ADC
samples in time × channel order**:

```text
time0/channel0, time0/channel1, ..., time1/channel0, time1/channel1, ...
```

Supply the actual file channel count and sample rate. A 385-column Neuropixels
file with a synchronization channel requires `--channels 385`, even if only 384
channels are sorted. The file size must be divisible by `2 × channels`.
Float, 24-bit, big-endian or header-bearing files require an appropriate input
extractor; EphyPress never silently quantizes float traces.

## Compress, verify and decompress

### Command line

```bash
ephypress compress continuous.dat recording.spc --channels 384 --fs 30000 --workers 4
ephypress info recording.spc
ephypress verify recording.spc --original continuous.dat
ephypress decompress recording.spc restored.dat
```

`python -m ephypress` accepts the same commands. Commands print JSON and return
nonzero on failure. Output files must not already exist; completed files are
published atomically. A failed operation removes its temporary output.

`verify` reads every sample and checks the stored source SHA256. With `--original`
it also compares every sample with that raw file. `decompress` performs the full
SHA256 check before publishing its output. Both operations check block CRCs and
the index checksum. Metadata inspection does not decode the recording.

### Python

```python
import ephypress as ep

report = ep.compress("continuous.dat", "recording.spc", n_channels=384,
                     sampling_frequency=30000, workers=4)
print(report["ratio"])  # raw bytes / complete archive bytes
ep.verify("recording.spc", original="continuous.dat")
ep.decompress("recording.spc", "restored.dat")
```

The default block size is 60000 samples; it does not need to match a future
sorter's batch size. Select spatial prediction with
`prediction="spatiotemporal"` or `--prediction spatiotemporal`.
The default is `prediction="temporal"`. To use Zstd for both high planes,
pass `entropy_backend="zstd"` or `--entropy zstd`. Both modes are lossless and
storage blocks do not include duplicated halos.

## Read compressed windows

```python
import ephypress as ep

with ep.open_recording("recording.spc") as recording:
    print(recording.shape, recording.dtype, recording.metadata["sampling_frequency"])
    traces = recording[100000:160000, :]
    selected = recording[100000:160000, [0, 2, 7]]
    batch = recording.read_batch(100000, 65536, halo=(2000, 2000), pad="edge")
    print(batch.shape)  # (69536, n_channels)
    print(recording.statistics())
```

`reader_mode="auto"` selects Linux page remapping when available, with block
assembly elsewhere. `reader_mode="blocks"` explicitly selects normal assembly.
Defaults are two cached blocks, up to four prefetch blocks and four reusable
Linux backing buffers. `prefetch=False` disables lookahead; `prefetch_blocks`
accepts 1, 2, 4 or 8. Returned arrays are read-only and retain their storage after
subsequent reads or close. Keeping many returned arrays alive adds memory beyond
the internal cache budget. Use a context manager to close descriptors/workers.
Concurrent consumers should use separate readers or an external lock.

## Native Kilosort4: sort the `.spc` directly

### Convenience API

```python
from kilosort.io import load_probe
import ephypress as ep

probe = load_probe("ProbeA.json")  # your actual geometry/channel map
result = ep.run_kilosort(
    "recording.spc", probe=probe, results_dir="ks4_output",
    settings={"batch_size": 60000}, torch_thread_lim=8,
)
```

The helper infers `fs` and `n_chan_bin` from the archive and rejects contradictory
values. Other settings and keyword arguments go to Kilosort. Use a new or empty
results directory. The return value is the original Kilosort result tuple.
No KS4 source modification is required.

### Kilosort's original API

```python
from kilosort import run_kilosort
from kilosort.io import load_probe
import ephypress as ep

with ep.open_recording("recording.spc") as recording:
    result = run_kilosort(
        settings={"n_chan_bin": recording.shape[1], "fs": recording.metadata["sampling_frequency"]},
        probe=load_probe("ProbeA.json"), filename="recording.spc",
        file_object=recording, data_dtype="int16", results_dir="ks4_output",
        save_preprocessed_copy=False,
    )
```

The important argument is `file_object`. Passing only a `.spc` filename to KS4
does not select an EphyPress decoder. The GUI also does not automatically detect
this format. A real probe map is required; channel count does not define geometry.
For partial sorting, use standard `settings={"tmin": ..., "tmax": ...}` options.

## SpikeInterface

EphyPress supplies a serializable `BaseRecording` extractor. It works with
SpikeInterface's trace access, channel/time slicing, preprocessing, analyzers
and sorter interfaces; registration into upstream `spikeinterface.extractors`
is not required.

```python
from ephypress.spikeinterface import read_ephypress

recording = read_ephypress("recording.spc")
traces = recording.get_traces(start_frame=0, end_frame=30000)
subset = recording.select_channels(recording.get_channel_ids()[:32])
recording.dump_to_json("recording.json")

# Works in a new process after EphyPress is installed there:
from spikeinterface.core import load
reloaded = load("recording.json")
reloaded.close()
```

The JSON references the archive path; it does not embed traces. Keep the archive
accessible and update/recreate that reference if you move it.

### Geometry and physical units

Files compressed from raw binary contain ADC values, file channel count and
sample rate. Supply the actual geometry and calibration before using operations
that require them:

```python
recording.set_channel_locations(channel_positions_um)  # shape (n_channels, 2 or 3)
recording.set_channel_gains(gain_to_uV)                   # device-specific, per channel or scalar
recording.set_channel_offsets(offset_to_uV)
traces_uV = recording.get_traces(start_frame=0, end_frame=30000, return_in_uV=True)
```

Alternatively attach a real ProbeInterface probe with `recording.set_probe(probe)`.
Device channel indices must correspond to the archive's column order. Remove a
sync channel with `select_channels` before attaching a probe containing only
electrode contacts. No gain or geometry is invented from a channel count.

### Compress an existing SpikeInterface recording

```python
from ephypress.spikeinterface import write_recording

# source_recording can be any uniformly sampled, one-segment int16 BaseRecording
compressed = write_recording(source_recording, "recording.spc", workers=4)
compressed.close()
```

The writer streams unscaled blocks directly; it does not write a full binary
intermediate. It stores channel IDs, positions, gains, offsets, groups, the
constant time origin, filtered annotation, and fully connected probe metadata
in the checked archive index. Arbitrary annotations and explicit timestamp
vectors are not stored. Explicit time vectors and multi-segment inputs are
rejected; write each segment to its own file. `keep_metadata=False` omits optional
metadata. Float recordings are rejected so no hidden lossy conversion occurs.

For multiprocessing, install EphyPress in each worker environment and use the
`spawn` start method. The extractor opens a private decoder lazily in each
process; do not fork a process with an active prefetch reader.

### Run KS4 through SpikeInterface without a raw copy

```python
import spikeinterface.sorters as ss
from ephypress.spikeinterface import read_ephypress

recording = read_ephypress("recording.spc")
recording.set_channel_locations(channel_positions_um)
sorting = ss.run_sorter(
    "kilosort4", recording, folder="ks4_si_output",
    use_binary_file=False, save_preprocessed_copy=False,
    torch_device="cuda", verbose=True,
)
recording.close()
```

`use_binary_file=False` forces SpikeInterface's array wrapper rather than a
binary export. `save_preprocessed_copy=False` avoids the optional processed
data copy. Probe/calibration metadata embedded by `write_recording` can be reused.
See the [SpikeInterface documentation](https://spikeinterface.readthedocs.io/en/stable/)
for quality metrics, analyzers and additional sorter settings.

## Phy and waveform viewing

Compressed sorting does not install a Phy `.spc` decoder. To view raw waveforms
in Phy, explicitly decompress to `restored.dat` and set `dat_path` in the exported
`params.py` to that absolute path, keeping the correct dtype, sample rate and
**full file channel count**. Alternatively let KS4 export a preprocessed copy
with `save_preprocessed_copy=True`; that creates an additional, processed file.

## Performance and validation

Compression ratio depends on the signal. No universal ratio or sorting speed
is promised. This release is tested for exact reconstruction, corruption
detection, arbitrary cross-block windows, retained-view lifetime, named prediction modes, CLI installation, SpikeInterface metadata/JSON reload, and native KS4
padded batches. Full native KS4 and SpikeInterface KS4 were also run on a real
60-second, 384-channel recording; see [validation details](docs/validation.md).

CPU `workers` controls encoding blocks; a Linux OpenMP kernel can additionally
use two threads per phase. Reader prefetch workers are independent. Control
Torch/BLAS threads separately in a sorting pipeline. `EPHYPRESS_OPENMP=0` at
**build time** produces a serial native extension for reproducible CPU controls.

## Development and release

```bash
git clone https://github.com/Laohusong/EphyPress.git
cd EphyPress
python -m pip install -e '.[dev,spikeinterface]'
pytest
python -m build
python -m twine check dist/*
```

GitHub CI builds and tests the package. Tagged releases build Linux/macOS/Windows wheels
and a source distribution. GPU/real-data validation is opt-in via
`tools/validate_real_recording.py`; recordings and sorting artifacts stay local.
See [CONTRIBUTING](CONTRIBUTING.md) and [CHANGELOG](CHANGELOG.md).

## License and acknowledgments

EphyPress is MIT-licensed. Bundled FiniteStateEntropy is BSD-2-Clause; its source,
license and pinned revision are in `vendor/fse`. Binary Linux wheels may include
the GCC OpenMP runtime under its runtime-library exception. Dependencies retain
their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
