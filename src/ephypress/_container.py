"""Versioned EphyPress container with independent lossless blocks and a checked index."""

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
from ._io import PositionedFile, publish_file
from ._native import decode_channels, decode_planes, encode_planes, library
from ._prediction import prediction_parameters

MAGIC = b"EPHYPRS\0"
FORMAT_VERSION = 1
PREFIX = struct.Struct("<8sQQ")
FRAME = struct.Struct("<III")
LENGTH = struct.Struct("<I")


def _encode_frame(data, prediction, zstd_level, entropy_backend):
    low, high = encode_planes(data, prediction)
    if entropy_backend == "fse":
        count, padded = data.size, high.size // 2
        planes = np.ascontiguousarray(high[:count].reshape(data.shape).T)
        packets = []
        for symbols in planes:
            packet = encode_bytes(symbols)
            packets.extend([LENGTH.pack(len(packet)), packet])
        primary = b"".join(packets)
        upper = zstd.ZstdCompressor(level=zstd_level).compress(high[padded:])
    else:
        primary = zstd.ZstdCompressor(level=zstd_level).compress(high)
        upper = b""
    frame = FRAME.pack(low.nbytes, len(primary), len(upper)) + low.tobytes() + primary + upper
    return frame, zlib.crc32(frame)


def write_blocks(
    get_block,
    destination,
    shape,
    *,
    sampling_frequency=30000.0,
    prediction="temporal",
    block_samples=60000,
    workers=4,
    entropy_backend="fse",
    zstd_level=3,
    extra_metadata=None,
    progress=None,
):
    """Stream immutable blocks from a callback, never materializing the entire recording."""
    samples, channels = shape
    parameters = prediction_parameters(prediction)
    if (
        type(samples) is not int
        or type(channels) is not int
        or samples < 1
        or not 1 <= channels < 2**32
        or type(block_samples) is not int
        or block_samples < 1
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
            output.write(PREFIX.pack(MAGIC, 0, 0))
            pending, submit = OrderedDict(), 0
            for block in range(blocks):
                while submit < min(blocks, block + workers):
                    a, b = (
                        submit * block_samples,
                        min(samples, (submit + 1) * block_samples),
                    )
                    source = np.asarray(get_block(a, b))
                    if source.dtype.kind != "i" or source.dtype.itemsize != 2:
                        raise ValueError("Source blocks must contain unscaled int16 samples")
                    data = np.array(source, dtype="<i2", order="C", copy=True)
                    if data.shape != (b - a, channels):
                        raise ValueError("Source returned an unexpected block shape")
                    core_stop = min(samples, (submit + 1) * block_samples)
                    digest.update(memoryview(data[submit * block_samples - a : core_stop - a]).cast("B"))
                    future = executor.submit(_encode_frame, data, prediction, zstd_level, entropy_backend)
                    pending[submit] = (a, b, future)
                    submit += 1
                a, b, future = pending.pop(block)
                payload, crc = future.result()
                entries.append([output.tell(), len(payload), a, b, crc])
                output.write(payload)
                if progress:
                    progress(block + 1, blocks, output.tell(), time.perf_counter() - start)
            metadata = dict(
                format="ephypress",
                format_version=FORMAT_VERSION,
                shape=[samples, channels],
                dtype="<i2",
                sampling_frequency=float(sampling_frequency),
                prediction=prediction,
                prediction_parameters=parameters,
                low_bits=4,
                block_samples=block_samples,
                zstd_level=zstd_level,
                source_bytes=samples * channels * 2,
                source_sha256=digest.hexdigest(),
                entropy_backend=entropy_backend,
                blocks=entries,
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
            output.write(PREFIX.pack(MAGIC, offset, len(index)))
            output.flush()
            os.fsync(output.fileno())
        # Exclusive atomic publication: a concurrently created destination is never replaced.
        publish_file(temporary, destination)
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
        prediction=prediction,
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
        self._file = PositionedFile(self.path)
        try:
            size = self._file.size
            prefix = self._file.read_at(PREFIX.size, 0)
            if len(prefix) != PREFIX.size:
                raise ValueError("Truncated EphyPress prefix")
            magic, offset, length = PREFIX.unpack(prefix)
            if magic != MAGIC:
                raise ValueError("Unsupported EphyPress archive format")
            if offset < PREFIX.size or not 0 < length <= 16 * 1024**2 or offset + length + 32 != size:
                raise ValueError("Invalid index bounds or truncated archive")
            index = self._file.read_at(length, offset)
            if hashlib.sha256(index).digest() != self._file.read_at(32, offset + length):
                raise ValueError("Archive index checksum mismatch")
            self.metadata = metadata = json.loads(index)
            if metadata.get("format") != "ephypress" or metadata.get("format_version") != FORMAT_VERSION:
                raise ValueError("Unsupported EphyPress format version")
            self._prediction = metadata["prediction"]
            if (
                metadata["prediction_parameters"] != prediction_parameters(self._prediction)
                or metadata["low_bits"] != 4
            ):
                raise ValueError("Prediction parameters or residual layout do not match the codec")
            self.shape, self.dtype = tuple(metadata["shape"]), np.dtype("<i2")
            self._batch, self._entries = metadata["block_samples"], metadata["blocks"]
            self._halo = 0
            self._entropy_backend = metadata["entropy_backend"]
            if (
                len(self.shape) != 2
                or any(type(value) is not int or value < 1 for value in self.shape)
                or self.shape[1] >= 2**32
                or type(self._batch) is not int
                or self._batch < 1
                or metadata["dtype"] != "<i2"
                or metadata["source_bytes"] != self.shape[0] * self.shape[1] * 2
                or not math.isfinite(metadata["sampling_frequency"])
                or metadata["sampling_frequency"] <= 0
            ):
                raise ValueError("Invalid recording dimensions or sampling frequency")
            self.ndim, self.size = 2, self.shape[0] * self.shape[1]
            if self._entropy_backend not in ("fse", "zstd"):
                raise ValueError("Invalid entropy backend")
            if len(self._entries) != (self.shape[0] + self._batch - 1) // self._batch:
                raise ValueError("Invalid block count")
            previous = PREFIX.size
            for block, entry in enumerate(self._entries):
                if len(entry) != 5 or any(type(value) is not int for value in entry):
                    raise ValueError("Invalid block entry")
                position, size, first, last, checksum = entry
                if (
                    position != previous
                    or size < FRAME.size
                    or position + size > offset
                    or not 0 <= checksum <= 2**32 - 1
                    or first != block * self._batch
                    or last != min(self.shape[0], (block + 1) * self._batch)
                ):
                    raise ValueError("Invalid block bounds")
                previous = position + size
            if previous != offset:
                raise ValueError("Invalid payload end")
            source_sha = metadata["source_sha256"]
            if (
                not isinstance(source_sha, str)
                or len(source_sha) != 64
                or len(bytes.fromhex(source_sha)) != 32
            ):
                raise ValueError("Invalid source SHA256")
            library()
        except BaseException:
            self._file.close()
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
        started = time.perf_counter()
        position, size, first, last, checksum = self._entries[block]
        payload = self._file.read_at(size, position)
        if len(payload) != size or (self._verify_crc and zlib.crc32(payload) != checksum):
            raise ValueError(f"Block {block} checksum mismatch or truncation")
        rows, channels = last - first, self.shape[1]
        count = rows * channels
        padded = (count + 7) // 8 * 8
        low_length, primary_length, upper_length = FRAME.unpack_from(payload)
        if low_length != padded // 2 or FRAME.size + low_length + primary_length + upper_length != size:
            raise ValueError("Invalid residual frame lengths")
        low = memoryview(payload)[FRAME.size : FRAME.size + low_length]
        primary = memoryview(payload)[FRAME.size + low_length : FRAME.size + low_length + primary_length]
        if self._entropy_backend == "fse":
            upper = zstd.ZstdDecompressor().decompress(
                memoryview(payload)[FRAME.size + low_length + primary_length :], max_output_size=padded
            )
            if len(upper) != padded:
                raise ValueError("Invalid upper plane length")
            high = np.empty(padded * 2, dtype="u1")
            high[padded:], high[count:padded] = np.frombuffer(upper, dtype="u1"), 0
            decode_channels(primary, rows, channels, high[:count])
        else:
            if upper_length:
                raise ValueError("Unexpected upper plane in a Zstd frame")
            high = zstd.ZstdDecompressor().decompress(primary, max_output_size=padded * 2)
        data = decode_planes(low, high, (rows, channels), self._prediction, out=out)
        data.flags.writeable = False
        with self._lock:
            self._stats["decoded_blocks"] += 1
            self._stats["bytes_read"] += size
            self._stats["decode_seconds"] += time.perf_counter() - started
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
                reader_mode="blocks",
                full_recording_materialized=False,
                raw_disk_cache=False,
            )

    def close(self):
        if not self._closed:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._pending.clear()
            self._cache.clear()
            self._file.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
