# EphyPress

**English** | [Chinese](readme_zh.md)

Lossless compression and on-demand reading of electrophysiology recordings.
The current codec uses independent blocks, reversible temporal differences and
four-lane rANS entropy coding. Input and reconstructed samples are exact int16
ADC values. Compressed recordings can be read directly by Kilosort4 and
SpikeInterface without writing a complete raw intermediate file.

## Install

```bash
python -m pip install .
# Optional integrations and development tools:
python -m pip install '.[all,dev]'
```

A C++17 compiler is required when building from source (MSVC Build Tools on
Windows, GCC or Clang on Linux, Xcode Command Line Tools on macOS). NumPy is the
only required Python runtime dependency. Optional tools are installed separately;
this repository contains no vendored source from other repositories.

## Quick start

```python
from ephypress import compress, open_recording, verify

compress("recording.dat", "recording.ep", n_channels=384,
         sampling_frequency=30000, block_samples=60000, workers=4)
with open_recording("recording.ep") as recording:
    samples = recording[30000:60000, :32]
verify("recording.ep", original="recording.dat")
```

```bash
ephypress compress recording.dat recording.ep --channels 384 --fs 30000
ephypress info recording.ep
ephypress verify recording.ep --original recording.dat
ephypress decompress recording.ep restored.dat
```

The source must be headerless, time-major, little-endian int16. Supply the actual
channel count, sampling rate and probe geometry; none is inferred from a filename.
Outputs are created atomically and existing files are never overwritten.

## Documentation

- [User guide](docs/user-guide.md)
- [SpikeInterface integration](docs/spikeinterface.md)
- [Container and codec specification](docs/format.md)
- [Validation](docs/validation.md) and [contributing](CONTRIBUTING.md)

The `main` branch contains the maintained library, examples and tests. Patent
figures, experiment evidence and reproduction instructions live exclusively on
the [patent branch](https://github.com/Laohusong/EphyPress/tree/patent). See its
[reproduction guide (Chinese)](https://github.com/Laohusong/EphyPress/blob/patent/patent/%E5%A4%8D%E7%8E%B0.md).
Experimental performance depends on the recording, reader
configuration, hardware and I/O conditions.

Current readers support production v3 archives. To migrate v1/v2 or experimental
containers, restore their raw bytes with the matching previous implementation,
then compress with the current version. See [release notes](RELEASE_NOTES.md).

## License

EphyPress is dual-licensed under **[AGPL-3.0-only](LICENSE)** and a separately
negotiated **paid commercial license**.

- **Personal and research use is free**, subject to the applicable AGPLv3 terms.
- **Commercial use that complies with AGPLv3 is also free**; AGPLv3 does not prohibit commercial use.
- **A separate paid commercial license is required when you need permission to operate outside AGPLv3 obligations**, such as a proprietary integration or distribution requiring a contractual exception.

Commercial licenses are available from Jiatai Song
([Laohusong](https://github.com/Laohusong)); their scope and fees are governed by
a separately signed agreement. See the [commercial licensing policy](COMMERCIAL_LICENSE.md).
The open-source option is version 3 **only**, not "version 3 or later". Existing
MIT grants for previously released versions remain valid.

Before contributing, read the [Contributor License Agreement](CLA.md) and
[contributing guide](CONTRIBUTING.md). Third-party dependencies retain their own
licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

## Acknowledgements

We thank the developers and contributors of the GitHub projects used by EphyPress:
[NumPy](https://github.com/numpy/numpy) for array operations and memory-mapped input;
[SpikeInterface](https://github.com/SpikeInterface/spikeinterface) for the recording
abstractions used by our extractor and writer;
[ProbeInterface](https://github.com/SpikeInterface/probeinterface) for restoring
stored probe geometry and wiring metadata; and
[Kilosort](https://github.com/MouseLand/Kilosort) for the public Kilosort4 interface
that accepts our on-demand recording reader. These projects make the corresponding
features and integrations possible, and we appreciate their maintainers' work.
