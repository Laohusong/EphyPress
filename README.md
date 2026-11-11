# EphyPress

This is the **patent** branch. See [专利实验复现](patent/复现.md) for the dataset, configurations, saved evidence and figure commands. The production source matches `main` at `1eca837`.

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

- [User guide](docs/user-guide.md) and [中文指南](docs/guide.zh-CN.md)
- [SpikeInterface integration](docs/spikeinterface.md)
- [Container and codec specification](docs/format.md)
- [Validation](docs/validation.md) and [contributing](CONTRIBUTING.md)

The `main` branch contains the maintained library, examples and tests. Patent
figures, experiment evidence and reproduction instructions live exclusively on
the [patent branch](https://github.com/Laohusong/EphyPress/tree/patent), in
`patent/复现.md`. Experimental performance depends on the recording, reader
configuration, hardware and I/O conditions.

Current readers support production v3 archives. To migrate v1/v2 or experimental
containers, restore their raw bytes with the matching previous implementation,
then compress with the current version. See [release notes](RELEASE_NOTES.md).

## License / 授权协议

EphyPress 采用 **[AGPL-3.0-only](LICENSE)＋付费商业许可**双许可模式。

- **个人及科研用途免费**：须遵守 AGPLv3 的适用条款。
- **需要免除 AGPLv3 义务的商业用途，须额外购买商业授权**，例如需要合同许可的闭源集成或专有分发。
- **遵守 AGPLv3 的商业使用同样可以免费**；AGPLv3 本身不禁止商业使用。

商业授权由 Jiatai Song（[Laohusong](https://github.com/Laohusong)）另行提供，具体范围和费用以双方签署的合同为准。详见[商业授权说明](COMMERCIAL_LICENSE.md)。历史版本已经授予的 MIT 权利不因本次变更而撤销。

Personal and research use is free under AGPLv3. Commercial use that complies with
AGPLv3 is also permitted without a separate license fee. A paid commercial license
is required if you need contractual permission to use EphyPress outside the AGPLv3
terms. The open-source license is version 3 **only**, not “version 3 or later.”

贡献前请阅读 [CLA（贡献者许可协议）](CLA.md)和[贡献指南](CONTRIBUTING.md)。第三方依赖保留各自许可证，见[第三方声明](THIRD_PARTY_NOTICES.md)。
