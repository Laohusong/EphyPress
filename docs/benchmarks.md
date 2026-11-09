# Measured performance

[README](../README.md) · [Full sorting benchmark and reproduction](../benchmarks/sorting_bandwidth/README.md)

## Lossless compression

The following are measurements on real Neuropixels 1.0 AP recordings, using
EphyPress 0.2.0 with temporal prediction, FSE, 60000-sample blocks and four
encoding workers. Ratios are original bytes divided by the complete archive size.

| Recording | Raw size | Archive size | Compression ratio | Evidence |
| --- | ---: | ---: | ---: | --- |
| ProbeA, 60 seconds, 384 channels, 30 kHz | 1.3824 GB | 0.7087 GB | **1.9507×** | [Public-API benchmark, three runs](../benchmarks/decompression/windows_60s.json) |
| ProbeB, 30 minutes, 384 channels, 30 kHz | 41.472 GB | 23.227 GB | **1.7855×** | [Compression record](../benchmarks/sorting_bandwidth/fixture/compression.json) |

Sizes use decimal GB. The 30-minute archive passed a
[full comparison against the original recording](../benchmarks/sorting_bandwidth/fixture/verification.json),
and the restoration below reproduced its original SHA256. The 60-second public
API runs also verified that restored bytes matched the source SHA256.
Compression ratio varies with the signal.

## Sorting from compressed data

KS4 reads `.ep` samples through EphyPress's on-demand reader, without an
explicit decompression step or a full raw disk copy. This reduces input bytes
and can improve total sorting time when storage reads are the bottleneck.

For the same 30-minute ProbeB recording, with **input reads limited to 100 MB/s**:

| KS4 input | Complete sorting time |
| --- | ---: |
| Original raw recording | 1965.11 s (32.75 min) |
| EphyPress archive | 1149.72 s (19.16 min) |

That is **1.71× faster**, or **41.5% less time**, including final export.
See the [timing CSV](../benchmarks/sorting_bandwidth/summary/timings.csv),
[computed comparisons](../benchmarks/sorting_bandwidth/summary/comparisons.json),
and original results for the
[raw run](../benchmarks/sorting_bandwidth/published/ks4_read_write_20261104/runs/input_read_only_ks4_raw_0100MBps/result.json)
and [compressed run](../benchmarks/sorting_bandwidth/published/ks4_read_write_20261104/runs/input_read_only_ks4_compressed_0100MBps/result.json).

The benchmark uses application-level logical-byte delivery ceilings, including
OS cache hits; it is not a physical HDD measurement. It illustrates the benefit
for slow-read storage such as HDDs, rather than predicting a particular drive's
runtime. Each point is one complete run. At high bandwidth, decoding overhead
can make compressed sorting slower. Hardware, software, I/O accounting and
reproduction commands are in the [benchmark protocol](../benchmarks/sorting_bandwidth/README.md).

## Decompression

A new public-API measurement on **2026-11-09** used the same complete
**30-minute Neuropixels 1.0 ProbeB-AP recording**: 54,000,000 samples,
384 channels, 30 kHz, 41,472,000,000 raw bytes and a 23,227,387,437-byte archive.

| Operation | Elapsed time | Raw-byte throughput |
| --- | ---: | ---: |
| Stream all decoded blocks to memory, discarding each block | **39.25 s** | 1057 MB/s |
| Restore the complete recording to disk with `ep.decompress` | **46.53 s** | 891 MB/s |

The disk-restoration time includes archive reading, decoding, SHA256
verification, output writes, `flush`, `fsync`, and atomic publication. The
restored file had the expected size and source SHA256:
`b3f6ffaf23681be08af594a485aad7809aa2e7c37a5befb78656b2a436425499`.

- [Original timing and verification JSON](../benchmarks/decompression/neuropixels1_30min_windows.json)
- [Recording, CPU and storage provenance](../benchmarks/decompression/recording_metadata.json)
- [Reproduction script](../benchmarks/decompression/benchmark.py)

Environment: Windows 10 19045, Intel Core Ultra 7 270K Plus (24 logical CPUs),
Python 3.11.14, EphyPress 0.2.0, NumPy 1.26.4 and Zstandard 0.25.0.
The archive was on a KIOXIA KCMYXRUG30T7 SSD; output was on a Samsung SSD 980 PRO.
This is a **single run per operation**, with default readers, normal OS file
caching, no cache eviction and no bandwidth cap. Restoration ran after the
complete decode-to-memory pass, so its input could benefit from the OS cache.
Imports and deletion of the temporary restored file are outside the timers.
These numbers describe this machine and cache policy.

To measure your own archive, run from the repository root with EphyPress installed.
Allow enough scratch space for the full raw recording. Each temporary restored
file is removed after its verification; the input archive is unchanged.

```bash
python benchmarks/decompression/benchmark.py recording.ep --scratch artifacts/decompression --output artifacts/decompression-results.json
```

Use `--repeats 3` for repeated measurements; the JSON includes each run and
medians. Choose a new output JSON path. The archived
[60-second benchmark script](../benchmarks/decompression/benchmark_60s.py)
and [results](../benchmarks/decompression/windows_60s.json) provide the earlier
three-run compression measurements used above; they are not extrapolated to
produce the 30-minute timings.
