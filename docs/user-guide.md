# EphyPress user guide

[README](../README.md) · [Benchmark results](benchmarks.md)

**Lossless electrophysiology compression, with direct SpikeInterface and Kilosort4 access.**

[Chinese user guide](guide.zh-CN.md) · [Releases](https://github.com/Laohusong/EphyPress/releases) · [File format](format.md) · [Validation](validation.md)

EphyPress turns headerless `int16` recordings into a single indexed `.ep` file.
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
Archives use the `.ep` extension; existing v1 archives only need to be renamed.

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
ephypress compress continuous.dat recording.ep --channels 384 --fs 30000 --workers 4
ephypress info recording.ep
ephypress verify recording.ep --original continuous.dat
ephypress decompress recording.ep restored.dat
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

report = ep.compress("continuous.dat", "recording.ep", n_channels=384,
                     sampling_frequency=30000, workers=4)
print(report["ratio"])  # raw bytes / complete archive bytes
ep.verify("recording.ep", original="continuous.dat")
ep.decompress("recording.ep", "restored.dat")
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

with ep.open_recording("recording.ep") as recording:
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

## Native Kilosort4: sort the `.ep` directly

### Convenience API

```python
from kilosort.io import load_probe
import ephypress as ep

probe = load_probe("ProbeA.json")  # your actual geometry/channel map
result = ep.run_kilosort(
    "recording.ep", probe=probe, results_dir="ks4_output",
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

with ep.open_recording("recording.ep") as recording:
    result = run_kilosort(
        settings={"n_chan_bin": recording.shape[1], "fs": recording.metadata["sampling_frequency"]},
        probe=load_probe("ProbeA.json"), filename="recording.ep",
        file_object=recording, data_dtype="int16", results_dir="ks4_output",
        save_preprocessed_copy=False,
    )
```

The important argument is `file_object`. Passing only a `.ep` filename to KS4
does not select an EphyPress decoder. The GUI also does not automatically detect
this format. A real probe map is required; channel count does not define geometry.
For partial sorting, use standard `settings={"tmin": ..., "tmax": ...}` options.

## SpikeInterface

See the [SpikeInterface guide](spikeinterface.md) for reading and writing recordings, metadata, and running KS4 without a raw copy.

## Phy and waveform viewing

Compressed sorting does not install a Phy `.ep` decoder. To view raw waveforms
in Phy, explicitly decompress to `restored.dat` and set `dat_path` in the exported
`params.py` to that absolute path, keeping the correct dtype, sample rate and
**full file channel count**. Alternatively let KS4 export a preprocessed copy
with `save_preprocessed_copy=True`; that creates an additional, processed file.

## Performance and validation

Compression ratio depends on the signal. No universal ratio or sorting speed
is promised. This release is tested for exact reconstruction, corruption
detection, arbitrary cross-block windows, retained-view lifetime, named prediction modes, CLI installation, SpikeInterface metadata/JSON reload, and native KS4
padded batches. Full native KS4 and SpikeInterface KS4 were also run on a real
60-second, 384-channel recording; see [validation details](validation.md).

CPU `workers` controls encoding blocks; a Linux OpenMP kernel can additionally
use two threads per phase. Reader prefetch workers are independent. Control
Torch/BLAS threads separately in a sorting pipeline. `EPHYPRESS_OPENMP=0` at
**build time** produces a serial native extension for reproducible CPU controls.

The [sorting bandwidth benchmark](../benchmarks/sorting_bandwidth/README.md) includes
recorded KS4/ChronoSort curves, data and environment provenance, and a standalone
Windows KS4 reproduction runner for input-read and independent read/write caps.
ChronoSort results use 62000-sample cores with context; missing read/write
measurements are explicitly identified.

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
See [CONTRIBUTING](../CONTRIBUTING.md) and [CHANGELOG](../CHANGELOG.md).

## License and acknowledgments

EphyPress is MIT-licensed. Bundled FiniteStateEntropy is BSD-2-Clause; its source,
license and pinned revision are in `vendor/fse`. Binary Linux wheels may include
the GCC OpenMP runtime under its runtime-library exception. Dependencies retain
their own licenses; see [third-party notices](../THIRD_PARTY_NOTICES.md).
