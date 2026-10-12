# Changelog

## 0.2.0

- Replace experiment identifiers with temporal/spatiotemporal prediction names.
- Remove the old predictor registry, quantization paths and compatibility branches.
- Introduce a descriptive EphyPress v1 container; older files require recompression.
- Add native Windows MSVC builds, exported codec functions, binary file handling,
  thread-safe positioned reads and exclusive file publication.
- Default compression, decompression, prefetch and integrations work on Linux,
  macOS and native Windows; publish x86_64 and ARM64 wheels.
- Extend real-platform CI, Unicode/control-byte tests and Windows KS4 CPU tests.

## 0.1.0

- Initial standalone lossless codec, CLI, bounded readers and sorting integrations.
