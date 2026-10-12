# EphyPress 0.1.0

The first standalone release of the Level1 p53 lossless electrophysiology codec.

- CLI and Python compression, exact restoration and SHA256 verification.
- Bundled BSD FSE and compiled C++ codec; no special system FSE dependency.
- Bounded on-demand windows, Linux page remapping and asynchronous prefetch.
- Compatible decoding of previous lossless SPC1/SPC3 p53/p41 archives.
- Native Kilosort4 integration and a serializable SpikeInterface extractor/writer.
- Detailed English and Chinese installation, compression and sorting guides.

Platform assets include Linux x86_64, macOS arm64/x86_64 ABI3 wheels and a source
distribution. CPython 3.10+ is required. Windows users can use WSL2/Linux.
Install optional SpikeInterface/Kilosort dependencies as described in the README.
PyTorch/CUDA and real probe geometry must be supplied for GPU sorting.

Exact codec tests, legacy compatibility and metadata serialization were checked
locally with NumPy 1.x/2.x. Both direct KS4 and SpikeInterface KS4 completed on
the same real 60s recording without a full raw copy. See `docs/validation.md` for
the tested versions and scope. This is a GitHub release, not a PyPI publication.
