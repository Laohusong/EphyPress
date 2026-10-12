"""Lossless SPC1/SPC3 blocks and checked indexes, compatible with Level1 archives."""

import hashlib
import json
import math
import os
import struct
import tempfile
import threading
import time
import zlib
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import zstandard as zstd

from ._entropy import encode_bytes
from ._native import decode_groups, decode_planes, encode_planes, library
from ._predictors import REGISTRY

MAGIC = b"SPKC01\x00\x00"
MAGIC_FSE = b"SPKC03\x00\x00"
PREFIX = struct.Struct("<8sQQ")
FRAME = struct.Struct("<II")
FRAME_FSE = struct.Struct("<III")
LENGTH = struct.Struct("<I")


def _validate_codec(quantum, predictor, low_bits):
    if not (
        type(quantum) is int
        and quantum == 1
        and type(predictor) is int
        and (0 <= predictor <= 8 or predictor in (13, 14, 15) or predictor in REGISTRY)
        and type(low_bits) is int
        and 1 <= low_bits <= 8
    ):
        raise ValueError("Only supported lossless Level1 predictors and quantum=1 are accepted")


def _encode_frame(data, predictor, low_bits, zstd_level, entropy_backend, entropy_group_channels):
    low, high = encode_planes(data, 1, predictor, low_bits)
    if entropy_backend == "fse":
        width = data.shape[1] + (predictor == 14)
        n, m = data.shape[0] * width, high.size // 2
        symbols = high[:n].reshape(data.shape[0], width)
        planes = np.ascontiguousarray(symbols.T) if entropy_group_channels == 1 else None
        packets = []
        for c in range(0, width, entropy_group_channels):
            packet = encode_bytes(
                planes[c] if planes is not None else symbols[:, c : c + entropy_group_channels]
            )
            packets.extend([LENGTH.pack(len(packet)), packet])
        primary = b"".join(packets)
        upper = zstd.ZstdCompressor(level=zstd_level).compress(high[m:])
        frame = FRAME_FSE.pack(low.nbytes, len(primary), len(upper)) + low.tobytes() + primary + upper
    else:
        high = zstd.ZstdCompressor(level=zstd_level).compress(high)
        frame = FRAME.pack(low.nbytes, len(high)) + low.tobytes() + high
    return frame, zlib.crc32(frame)


def write_blocks(
    get_block,
    destination,
    shape,
    *,
    sampling_frequency=30000.0,
    profile="level1",
    block_samples=60000,
    workers=4,
    entropy_backend="fse",
    zstd_level=3,
    extra_metadata=None,
    progress=None,
):
    """Stream immutable blocks from a callback, never materializing the entire recording."""
    samples, channels = shape
    if profile not in ("level1", "legacy"):
        raise ValueError("profile must be 'level1' (p53) or 'legacy' (p41)")
    predictor, halo = (53, 0) if profile == "level1" else (41, 61)
    if (
        type(samples) is not int
        or type(channels) is not int
        or samples < 1
        or not 1 <= channels < 2**32
        or type(block_samples) is not int
        or block_samples < max(1, halo)
        or type(workers) is not int
        or workers < 1
    ):
        raise ValueError("Invalid recording dimensions, block size or workers")
    if not math.isfinite(sampling_frequency) or sampling_frequency <= 0:
        raise ValueError("sampling_frequency must be finite and positive")
    if entropy_backend not in ("fse", "zstd"):
        raise ValueError("entropy_backend must be 'fse' or 'zstd'")
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if extra_metadata is not None:
        json.dumps(extra_metadata, allow_nan=False)
    library()
    blocks = (samples + block_samples - 1) // block_samples
    digest, entries = hashlib.sha256(), []
    fd, temporary = tempfile.mkstemp(
        prefix="." + destination.name + ".", suffix=".partial", dir=destination.parent
    )
    temporary = Path(temporary)
    start = time.perf_counter()
    try:
        with os.fdopen(fd, "wb") as output, ThreadPoolExecutor(max_workers=workers) as executor:
            output.write(PREFIX.pack(MAGIC_FSE if entropy_backend == "fse" else MAGIC, 0, 0))
            pending, submit = OrderedDict(), 0
            for block in range(blocks):
                while submit < min(blocks, block + workers):
                    a, b = (
                        max(0, submit * block_samples - halo),
                        min(samples, (submit + 1) * block_samples + halo),
                    )
                    data = np.array(get_block(a, b), dtype="<i2", order="C", copy=True)
                    if data.shape != (b - a, channels):
                        raise ValueError("Source returned an unexpected block shape")
                    core_stop = min(samples, (submit + 1) * block_samples)
                    digest.update(memoryview(data[submit * block_samples - a : core_stop - a]).cast("B"))
                    future = executor.submit(
                        _encode_frame, data, predictor, 4, zstd_level, entropy_backend, 1
                    )
                    pending[submit] = (a, b, future)
                    submit += 1
                a, b, future = pending.pop(block)
                payload, crc = future.result()
                entries.append([output.tell(), len(payload), a, b, crc])
                output.write(payload)
                if progress:
                    progress(block + 1, blocks, output.tell(), time.perf_counter() - start)
            metadata = dict(
                format="SPC3" if entropy_backend == "fse" else "SPC1",
                shape=[samples, channels],
                dtype="<i2",
                fs=float(sampling_frequency),
                quantum=1,
                predictor=predictor,
                low_bits=4,
                batch_samples=block_samples,
                halo=halo,
                zstd_level=zstd_level,
                source_bytes=samples * channels * 2,
                source_sha256=digest.hexdigest(),
                protected_intervals=[],
                calibration_stride=0,
                entropy_backend=entropy_backend,
                entropy_group_channels=1,
                waveform_protection=None,
                blocks=entries,
                predictor_model=REGISTRY[predictor],
            )
            if extra_metadata is not None:
                metadata["ephypress_metadata"] = extra_metadata
            index = json.dumps(metadata, separators=(",", ":"), allow_nan=False).encode()
            if len(index) > 16 * 1024**2:
                raise ValueError("Archive index exceeds the supported 16MiB limit; use larger blocks")
            offset = output.tell()
            output.write(index)
            output.write(hashlib.sha256(index).digest())
            output.seek(0)
            output.write(PREFIX.pack(MAGIC_FSE if entropy_backend == "fse" else MAGIC, offset, len(index)))
            output.flush()
            os.fsync(output.fileno())
        # Exclusive atomic publication: a concurrently created destination is never replaced.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    size = destination.stat().st_size
    return dict(
        path=str(destination),
        source_bytes=samples * channels * 2,
        compressed_bytes=size,
        ratio=samples * channels * 2 / size,
        source_sha256=digest.hexdigest(),
        encode_seconds=time.perf_counter() - start,
        blocks=blocks,
        profile=profile,
        predictor=predictor,
        quantum=1,
        entropy_backend=entropy_backend,
    )


class CompressedRecording:
    """Bounded, read-only array interface accepted by KS4's file_object argument.

    Caller-retained arrays can outlive the reader and consume additional RAM.
    Concurrent consumers should use separate readers or an external lock.
    """

    def __init__(self, path, *, prefetch=True, cache_blocks=2, prefetch_blocks=4, verify_crc=True):
        if type(cache_blocks) is not int or cache_blocks < 1:
            raise ValueError("cache_blocks must be a positive integer")
        if prefetch_blocks not in (1, 2, 4, 8):
            raise ValueError("prefetch_blocks must be 1, 2, 4 or 8")
        self.path = Path(path)
        self._fd = os.open(self.path, os.O_RDONLY)
        try:
            size = os.fstat(self._fd).st_size
            prefix = os.pread(self._fd, PREFIX.size, 0)
            if len(prefix) != PREFIX.size:
                raise ValueError("Truncated SPC prefix")
            magic, offset, length = PREFIX.unpack(prefix)
            if magic not in (MAGIC, MAGIC_FSE):
                raise ValueError("Only lossless SPC1/SPC3 archives are supported")
            if offset < PREFIX.size or not 0 < length <= 16 * 1024**2 or offset + length + 32 != size:
                raise ValueError("Invalid SPC index bounds or truncated archive")
            index = os.pread(self._fd, length, offset)
            if hashlib.sha256(index).digest() != os.pread(self._fd, 32, offset + length):
                raise ValueError("SPC index checksum mismatch")
            self.metadata = m = json.loads(index)
            _validate_codec(m["quantum"], m["predictor"], m["low_bits"])
            if m["predictor"] in REGISTRY and m.get("predictor_model") != REGISTRY[m["predictor"]]:
                raise ValueError("Predictor definition mismatch")
            self.shape, self.dtype = tuple(m["shape"]), np.dtype("<i2")
            self.ndim, self.size = 2, int(np.prod(self.shape))
            self._batch, self._halo, self._entries = m["batch_samples"], m["halo"], m["blocks"]
            self._entropy_backend = m.get("entropy_backend", "zstd")
            self._entropy_group_channels = m.get("entropy_group_channels", 8)
            if (
                len(self.shape) != 2
                or any(type(v) is not int or v < 1 for v in self.shape)
                or self.shape[1] >= 2**32
                or type(self._batch) is not int
                or self._batch < 1
                or type(self._halo) is not int
                or not 0 <= self._halo <= self._batch
                or m["dtype"] != "<i2"
                or m["source_bytes"] != self.shape[0] * self.shape[1] * 2
                or not math.isfinite(m["fs"])
                or m["fs"] <= 0
            ):
                raise ValueError("Invalid SPC dimensions or sampling frequency")
            if (
                self._entropy_backend not in ("fse", "zstd")
                or type(self._entropy_group_channels) is not int
                or self._entropy_group_channels < 1
                or (magic == MAGIC_FSE) != (self._entropy_backend == "fse")
                or m["format"] != ("SPC3" if magic == MAGIC_FSE else "SPC1")
            ):
                raise ValueError("Invalid SPC entropy format")
            if len(self._entries) != (self.shape[0] + self._batch - 1) // self._batch:
                raise ValueError("Invalid SPC block count")
            previous = PREFIX.size
            for i, entry in enumerate(self._entries):
                if len(entry) != 5 or any(type(v) is not int for v in entry):
                    raise ValueError("Invalid SPC block entry")
                pos, n, a, b, crc = entry
                if (
                    pos != previous
                    or n < FRAME.size
                    or pos + n > offset
                    or not 0 <= crc <= 2**32 - 1
                    or a != max(0, i * self._batch - self._halo)
                    or b != min(self.shape[0], (i + 1) * self._batch + self._halo)
                ):
                    raise ValueError("Invalid SPC block bounds")
                previous = pos + n
            if previous != offset:
                raise ValueError("Invalid SPC payload end")
            source_sha = m["source_sha256"]
            if not isinstance(source_sha, str) or len(source_sha) != 64:
                raise ValueError("Invalid source SHA256")
            bytes.fromhex(source_sha)
            library()
        except BaseException:
            os.close(self._fd)
            raise
        self._cache, self._pending = OrderedDict(), {}
        self._cache_limit, self._prefetch_enabled = cache_blocks, prefetch
        self._prefetch_blocks, self._verify_crc = prefetch_blocks, verify_crc
        self._executor = ThreadPoolExecutor(max_workers=prefetch_blocks, thread_name_prefix="ephypress")
        self._lock = threading.Lock()
        self._stats = dict(
            decoded_blocks=0,
            cache_hits=0,
            bytes_read=0,
            decode_seconds=0.0,
            caller_wait_seconds=0.0,
            requests=0,
            max_decoded_cache_bytes=0,
            cross_block_requests=0,
            assembled_bytes=0,
            max_pending_blocks=0,
        )
        self._last, self._stride, self._closed = None, 1, False

    def _decode(self, block, *, out=None):
        start = time.perf_counter()
        pos, n, a, b, crc = self._entries[block]
        payload = os.pread(self._fd, n, pos)
        if len(payload) != n or (self._verify_crc and zlib.crc32(payload) != crc):
            raise ValueError(f"SPC block {block} checksum mismatch or truncation")
        width = self.shape[1] + (self.metadata["predictor"] == 14)
        count, m = (b - a) * width, ((b - a) * width + 7) // 8 * 8
        if self._entropy_backend == "fse":
            nl, np_, nu = FRAME_FSE.unpack_from(payload)
            if nl != m // 8 * self.metadata["low_bits"] or FRAME_FSE.size + nl + np_ + nu != n:
                raise ValueError("Invalid FSE frame lengths")
            low = memoryview(payload)[FRAME_FSE.size : FRAME_FSE.size + nl]
            primary = memoryview(payload)[FRAME_FSE.size + nl : FRAME_FSE.size + nl + np_]
            upper = zstd.ZstdDecompressor().decompress(
                memoryview(payload)[FRAME_FSE.size + nl + np_ :], max_output_size=m
            )
            if len(upper) != m:
                raise ValueError("Invalid FSE upper plane length")
            high = np.empty(m * 2, dtype="u1")
            high[m:], high[count:m] = np.frombuffer(upper, dtype="u1"), 0
            decode_groups(primary, b - a, width, self._entropy_group_channels, high[:count])
        else:
            nl, nh = FRAME.unpack_from(payload)
            if nl != m // 8 * self.metadata["low_bits"] or FRAME.size + nl + nh != n:
                raise ValueError("Invalid SPC frame lengths")
            low = memoryview(payload)[FRAME.size : FRAME.size + nl]
            high = zstd.ZstdDecompressor().decompress(
                memoryview(payload)[FRAME.size + nl :], max_output_size=m * 2
            )
        data = decode_planes(
            low,
            high,
            (b - a, self.shape[1]),
            1,
            self.metadata["predictor"],
            self.metadata["low_bits"],
            out=out,
        )
        data.flags.writeable = False
        with self._lock:
            self._stats["decoded_blocks"] += 1
            self._stats["bytes_read"] += n
            self._stats["decode_seconds"] += time.perf_counter() - start
        return data

    def __len__(self):
        return self.shape[0]

    def _block(self, block):
        if block in self._cache:
            self._stats["cache_hits"] += 1
            self._cache.move_to_end(block)
            return self._cache[block]
        start = time.perf_counter()
        future = self._pending.pop(block, None)
        data = self._decode(block) if future is None else future.result()
        self._stats["caller_wait_seconds"] += time.perf_counter() - start
        self._cache[block] = data
        while len(self._cache) > self._cache_limit:
            self._cache.popitem(last=False)
        used = sum(v.nbytes for v in self._cache.values())
        self._stats["max_decoded_cache_bytes"] = max(used, self._stats["max_decoded_cache_bytes"])
        return data

    def _queue_blocks(self, wanted):
        wanted = list(dict.fromkeys(wanted))[: self._prefetch_blocks]
        for old in list(self._pending):
            if old not in wanted:
                self._pending.pop(old).cancel()
        for nxt in wanted:
            if 0 <= nxt < len(self._entries) and nxt not in self._cache and (nxt not in self._pending):
                self._pending[nxt] = self._executor.submit(self._decode, nxt)
        with self._lock:
            self._stats["max_pending_blocks"] = max(self._stats["max_pending_blocks"], len(self._pending))

    def _prime_blocks(self, needed):
        if not self._prefetch_enabled:
            return
        wanted = [block for block in needed if block not in self._cache]
        wanted.extend(range(needed[-1] + 1, needed[-1] + 1 + self._prefetch_blocks))
        self._queue_blocks(wanted)

    def _prefetch(self, block, *, contiguous=False):
        if not self._prefetch_enabled:
            return
        if contiguous:
            self._stride = 1
        elif self._last is not None:
            delta = block - self._last
            if delta > 0:
                self._stride = delta
            elif delta < 0:
                self._stride = 1
        self._last = block
        self._queue_blocks([block + self._stride * i for i in range(1, self._prefetch_blocks + 1)])

    def _read(self, start, stop):
        if start >= stop:
            return np.empty((0, self.shape[1]), dtype=self.dtype)
        block = min((start + self._halo) // self._batch, len(self._entries) - 1)
        a, b = self._entries[block][2:4]
        if start >= a and stop <= b:
            data = self._block(block)[start - a : stop - a]
            self._prefetch(block)
            return data
        segments = []
        pos = start
        while pos < stop:
            block = min((pos + self._halo) // self._batch, len(self._entries) - 1)
            a, b = self._entries[block][2:4]
            end = min(stop, b)
            segments.append((block, a, pos, end))
            pos = end
        data = np.empty((stop - start, self.shape[1]), dtype=self.dtype)
        for i, (block, a, lo, hi) in enumerate(segments):
            self._prime_blocks([s[0] for s in segments[i : i + self._prefetch_blocks]])
            decoded = self._block(block)
            data[lo - start : hi - start] = decoded[lo - a : hi - a]
        self._prefetch(block, contiguous=True)
        data.flags.writeable = False
        with self._lock:
            self._stats["cross_block_requests"] += 1
            self._stats["assembled_bytes"] += data.nbytes
        return data

    def read_batch(self, start, batch_samples, *, halo=0, pad="edge", channels=slice(None)):
        """Read an arbitrary consumer batch, independent of storage frames.

        ``start`` is the core's sample index. Halo can be a symmetric integer
        or a (before, after) pair. ``pad=None`` clips to the recording; edge or
        zero padding returns the requested length, including a partial tail.
        Channel indexing follows NumPy semantics. Returned data are read-only.
        """
        integers = (int, np.integer)
        if not isinstance(start, integers) or not 0 <= start < self.shape[0]:
            raise IndexError("Batch start outside recording")
        if not isinstance(batch_samples, integers) or batch_samples < 1:
            raise ValueError("batch_samples must be a positive integer")
        before, after = (halo, halo) if isinstance(halo, integers) else halo
        if any(not isinstance(h, integers) or h < 0 for h in (before, after)):
            raise ValueError("Halo sizes must be nonnegative integers")
        if pad not in (None, "edge", "zero"):
            raise ValueError("pad must be edge, zero, or None")
        lo = max(0, int(start) - int(before))
        hi = min(self.shape[0], int(start) + int(batch_samples) + int(after))
        data = self[lo:hi, channels]
        if pad is None:
            return data
        left = lo - (int(start) - int(before))
        right = int(start) + int(batch_samples) + int(after) - hi
        if left or right:
            widths = [(left, right)] + [(0, 0)] * (data.ndim - 1)
            data = (
                np.pad(data, widths, mode="edge")
                if pad == "edge"
                else np.pad(data, widths, mode="constant", constant_values=0)
            )
            data.flags.writeable = False
        return data

    def _index(self, key):
        if self._closed:
            raise ValueError("Recording is closed")
        self._stats["requests"] += 1
        if key is Ellipsis:
            key = slice(None)
        if not isinstance(key, tuple):
            key = (key, slice(None))
        if len(key) != 2:
            raise IndexError("Expected time and channel indices")
        rows, cols = key
        if rows is Ellipsis:
            rows = slice(None)
        if isinstance(rows, (int, np.integer)):
            row = int(rows)
            if row < 0:
                row += self.shape[0]
            if not 0 <= row < self.shape[0]:
                raise IndexError("Sample index out of bounds")
            return self._read(row, row + 1)[0, cols]
        if isinstance(rows, slice):
            start, stop, step = rows.indices(self.shape[0])
            if step > 0:
                return self._read(start, stop)[::step, cols]
            indices = np.arange(start, stop, step)
        else:
            indices = np.asarray(rows)
            if indices.dtype.kind == "b":
                if indices.ndim != 1 or indices.size != self.shape[0]:
                    raise IndexError("Invalid time mask")
                indices = np.flatnonzero(indices)
            elif indices.dtype.kind not in "iu":
                raise IndexError("Time indices must be integers")
            indices = indices.astype(np.int64)
            indices = np.where(indices < 0, indices + self.shape[0], indices)
            if np.any((indices < 0) | (indices >= self.shape[0])):
                raise IndexError("Sample index out of bounds")
        if indices.size == 0:
            return np.empty((0, self.shape[1]), dtype=self.dtype)[:, cols]
        lo, hi = (int(indices.min()), int(indices.max()))
        data = self._read(lo, hi + 1)
        return data[indices - lo][:, cols] if isinstance(rows, slice) else data[indices - lo, cols]

    def __getitem__(self, key):
        result = self._index(key)
        if isinstance(result, np.ndarray):
            result.flags.writeable = False
        return result

    def iter_cores(self):
        for i in range(len(self._entries)):
            a, b = self._entries[i][2:4]
            start = i * self._batch
            stop = min(self.shape[0], start + self._batch)
            data = self._block(i)[start - a : stop - a]
            self._prefetch(i)
            yield data

    def statistics(self):
        with self._lock:
            return dict(
                self._stats,
                cache_blocks=self._cache_limit,
                speculative_blocks_limit=self._prefetch_blocks,
                prefetch_enabled=self._prefetch_enabled,
                full_recording_materialized=False,
                raw_disk_cache=False,
            )

    def close(self):
        if not self._closed:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._pending.clear()
            self._cache.clear()
            os.close(self._fd)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
