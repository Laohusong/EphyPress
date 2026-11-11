# User guide

## Installation on Linux, macOS and native Windows

Use Python 3.10 or newer and a C++17 compiler. From a checkout:

```bash
python -m pip install .
python -m pip install '.[spikeinterface]'  # optional
python -m pip install '.[ks4]'            # optional
```

For CUDA sorting, install the appropriate PyTorch build for your GPU separately.
Windows source builds require MSVC Build Tools; the extension uses a static C++
runtime and has no OpenMP dependency.

## Compress, inspect and restore

```python
from ephypress import compress, decompress, info, verify

result = compress("recording.dat", "recording.ep", n_channels=384,
                  sampling_frequency=30000, block_samples=60000, workers=4)
metadata = info("recording.ep")
verification = verify("recording.ep", original="recording.dat")
decompress("recording.ep", "restored.dat")
```

Input is headerless time-major little-endian int16. There is no filtering,
quantization or scaling. Blocks are independent; the default 60000 samples
represent two seconds at 30 kHz. `workers` controls concurrent compression blocks.
`info` checks the index without decoding samples. `verify` checks every block and
the original-byte SHA256; `original` additionally compares all samples directly.
Restoration performs the same full SHA256 check. Failed writes do not publish
partial output, and existing destinations are never overwritten.

The equivalent CLI commands are `ephypress compress`, `info`, `verify` and
`decompress`; use `--help` on any command for all options.

## Read windows

```python
from ephypress import open_recording

with open_recording("recording.ep", cache_blocks=64, prefetch_blocks=32) as data:
    window = data[59950:60100, :32]  # may cross a storage-block boundary
    every_second = data[100:200:2]
    shape, dtype = data.shape, data.dtype
```

Windows contain exact, read-only time-major samples and remain valid after cache
eviction or reader closure. Cached blocks and per-worker decoding workspaces
consume memory; with 384 channels, 60000 samples per block and the default
64-block cache, cached samples alone can approach 2.95 GB. Active workspaces,
prefetch and caller-retained windows add to this. For less memory, reduce
`cache_blocks` and `prefetch_blocks`, or use `prefetch=False` for synchronous
single-block decoding. A large strided request can still touch many blocks.

Close readers or use a context manager. Each concurrent consumer should own its
reader or use an external lock. For multiprocessing use `spawn` and open readers
inside workers. Integrity checks detect accidental corruption, not malicious
modification. The supported archive format is v3.

## Direct Kilosort4 sorting

```python
from ephypress.kilosort import run_kilosort

run_kilosort("recording.ep", probe=probe,
             settings={"batch_size": 60000}, results_dir="ks4_output",
             reader_options={"cache_blocks": 64, "prefetch_blocks": 32})
```

`probe` must describe the actual electrode geometry and channel mapping.
The adapter uses Kilosort's public `file_object` interface, fills `fs` and
`n_chan_bin` from the archive, and defaults to `save_preprocessed_copy=False`.
Choose a new or empty output directory. Other keyword arguments pass through to
Kilosort. On-demand reading eliminates a full raw intermediate; its speed depends
on compressed size, decoding cost and the access pattern.

For serializable recordings, physical units and preprocessing, see the
[SpikeInterface guide](spikeinterface.md).
