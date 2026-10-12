# EphyPress 0.2.0

Named lossless prediction and native desktop support.

- `temporal` (default): reversible prediction from the previous sample.
- `spatiotemporal`: additionally predict from neighboring channel residuals.
- Descriptive coefficients and prediction rules replace experiment identifiers.
- Native Windows wheels and MSVC source builds, with binary file handling,
  synchronized positioned reads and statically linked C++ runtime.
- Linux, macOS and Windows default readers, threaded compression/prefetch,
  direct native KS4 and SpikeInterface integrations.
- x86_64/ARM64 ABI3 wheels and a source distribution with platform CI.

The new EphyPress v1 container intentionally does not read previous file formats.
Recompress the original int16 data. The extension remains `.spc` and both modes
are completely lossless. Native ARM64 Windows requires ARM64 Python 3.11+.

See the English/Chinese guides and `docs/validation.md` for setup and test scope.
GPU sorting still requires appropriate PyTorch/CUDA and real probe geometry.
