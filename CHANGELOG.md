# Changelog

## 0.3.0

- Use one production pipeline: reversible int16 temporal differences and four-lane rANS.
- Read and write v3 archives with block CRC32, index SHA256 and source SHA256.
- Reuse decoder workspaces and output buffers while preserving returned-array ownership.
- Support direct SpikeInterface and Kilosort4 access without a full raw intermediate.
- Remove obsolete codec backends, experimental containers and copied repository sources.
- Move patent experiments and figures to the dedicated patent branch.

See [release notes](RELEASE_NOTES.md) for migration requirements.
