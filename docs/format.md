# EphyPress v3 format

All wire integers are little-endian. Current writers and readers use production
v3 only. The filename extension is `.ep`.

## Container

1. A 24-byte prefix `<8sQQ>` stores magic `EPHYPRS\0`, JSON index offset and length.
2. Independent compressed blocks follow, with no duplicated storage halos.
3. The UTF-8 JSON index describes the recording and each block.
4. SHA256 of the exact index bytes occupies the final 32 bytes.

The index includes `format="ephypress"`, `format_version=3`, `shape`, `dtype="<i2"`,
`sampling_frequency`, `block_samples`, `source_bytes`, `source_sha256`, and `blocks`.
Each block entry is `[offset, length, first_sample, last_sample, crc32]`, with an
exclusive last sample. The index is limited to 16 MiB. Optional
`ephypress_metadata` stores supported SpikeInterface metadata. Readers validate
bounds, dimensions, contiguous coverage and checksums before exposing data.

Fixed codec fields are `prediction="delta"`,
`prediction_parameters={"temporal_numerator":1,"temporal_denominator":1}`,
`entropy_backend="rans"`, `residual_layout="channel_int16"`, `low_bits=0`, and
`rans_parameters={"scale_bits":14,"lanes":4,"escape_symbol":1024,
"model":"block_unconditional"}`.

## Prediction and symbols

For each channel within an independent block, `d[0]=x[0]` and
`d[t]=x[t]-x[t-1]` using reversible 16-bit modular arithmetic. The residuals are
serialized channel-first. Signed residuals are Zigzag-mapped; values 0 through
1023 become direct symbols, while all others emit escape symbol 1024 and the
original 16-bit residual pattern. Escape values are stored in forward order.

A single 1025-symbol histogram is normalized to a total of 16384. Each observed
symbol receives at least one frequency unit. The encoder distributes deficits
to the most frequent symbol and reduces excess in descending count order.

## Block packet

1. `<II>`: model count (1), escape byte count (even).
2. 1025 uint16 normalized frequencies totaling 16384.
3. Four uint32 rANS states in `[2^23, 2^31)`.
4. The interleaved byte-renormalization stream.
5. Escaped residual bit patterns as little-endian uint16.

The fixed overhead is 2074 bytes. Symbol index `i` uses state `i % 4`. Encoding
traverses symbols in reverse order; decoding consumes them forwards. Byte
renormalization uses a lower state bound of `2^23`. All four terminal states
must equal that bound, and both byte streams must be consumed exactly.

The decoder maintains per-worker frequency tables, input and residual buffers.
A tiled inverse-difference/transpose pass produces time-major int16 samples.
Requested windows are copied before cached output buffers are recycled, so
caller-held windows remain valid. Consumer batch sizes are independent of
storage blocks. Block CRC32 and index/source SHA256 detect accidental corruption;
they are not authentication mechanisms.
