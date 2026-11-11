# EphyPress 0.3

The maintained implementation uses production v3 delta/rANS archives only.
Existing production v3 recordings remain readable and the rANS block format is
unchanged. The cleanup removes alternate prediction/entropy backends and
experimental readers, along with their API and CLI selection parameters.

Calls should use `compress(..., block_samples=60000, workers=4)` and
`open_recording(..., cache_blocks=64, prefetch_blocks=32)` as needed. Removed
options include `prediction`, `entropy_backend`, `zstd_level`, `reader_mode`
and `pool_frames`. For v1/v2 or prototype archives, use the matching previous
implementation to restore raw bytes, verify them, then compress with this version.

The main branch no longer contains patent experiments, plotting code or copied
third-party source. The patent branch carries reproduction instructions and
historical evidence. Those measured timings are not newly measured results of
the cleaned implementation. No raw electrophysiology recording is distributed.
