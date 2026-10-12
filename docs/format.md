# EphyPress container v1

Version 0.2 uses one versioned container for both entropy backends. Earlier file
layouts are unsupported. All integer fields are little-endian; files are portable
between native Linux, macOS and Windows installations.

## Layout

1. A 24-byte prefix `<8sQQ>` contains magic `EPHYPRS\0`, index offset and length.
2. Independent compressed blocks follow the prefix, with no duplicated storage halos.
3. A UTF-8 JSON index describes the complete recording.
4. SHA256 of the exact index bytes occupies the final 32 bytes.

The index contains `format="ephypress"`, `format_version=1`, `shape`, `dtype`,
`sampling_frequency`, `block_samples`, `prediction`, `prediction_parameters`,
`entropy_backend`, `low_bits=4`, `source_bytes`, `source_sha256`, and `blocks`.
Each block entry is `[offset, length, first_sample, last_sample, crc32]`.
Index size is limited to 16MiB. Optional `ephypress_metadata` preserves supported
SpikeInterface metadata. The reader checks dimensions, bounds, parameters,
checksums and the version before decoding.

Each frame uses `<III>` lengths for packed low bits, primary payload and upper
payload. FSE uses one length-prefixed packet per channel; packet modes are raw,
FSE-compressed or run-length encoded. The upper residual plane uses Zstd. In the
Zstd backend, both high planes occupy the primary payload and the upper payload
is empty. Internal padding to eight-value groups is never returned as samples.

## Named prediction rules

`temporal` predicts each sample as `floor(5 * previous_sample / 8)` within its
block. The first sample has prediction zero. Signed subtraction and restoration
use reversible 16-bit modular arithmetic, followed by Zigzag mapping. There is
no quantization or signal filtering.

`spatiotemporal` first performs temporal prediction, then predicts residuals
from the previous four channel residuals with weights `[7,11,2,4]/32`, rounded
with integer floor division. All blocks reset prediction state independently.

Coefficients have one definition in `_prediction.h`; the native module exposes
them to Python. Archive metadata stores those meaningful parameters rather than
opaque model identifiers. Reader/encoder use explicitly named native functions.

Source SHA256 validates every restored ADC byte; block CRC and index SHA256
locate corruption. These checksums are integrity checks, not authentication.
Consumer batch sizes and requested context remain independent of storage blocks.
