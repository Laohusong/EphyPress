"""Versioned EphyPress container with independent lossless blocks and a checked index."""

import hashlib
import json
import math
import os
import queue
import struct
import tempfile
import threading
import time
import zlib
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from ._io import PositionedFile, publish_file
from ._native import library
from ._rans import PARAMETERS as RANS_PARAMETERS
from ._rans import Decoder as RansDecoder
from ._rans import encode as encode_rans

MAGIC = b"EPHYPRS\0"
FORMAT_VERSION = 3
DELTA_PARAMETERS = {"temporal_numerator": 1, "temporal_denominator": 1}
PREFIX = struct.Struct("<8sQQ")


def _encode_frame(data):
    frame = encode_rans(data)
    return frame, zlib.crc32(frame)


def write_blocks(
    get_block,
    destination,
    shape,
    *,
    sampling_frequency=30000.0,
    block_samples=60000,
    workers=4,
    extra_metadata=None,
    progress=None,
):
    """Stream immutable blocks from a callback, never materializing the entire recording."""
    samples, channels = shape
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
                    digest.update(memoryview(data).cast("B"))
                    future = executor.submit(_encode_frame, data)
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
                prediction="delta",
                prediction_parameters=dict(DELTA_PARAMETERS),
                low_bits=0,
                residual_layout="channel_int16",
                block_samples=block_samples,
                source_bytes=samples * channels * 2,
                source_sha256=digest.hexdigest(),
                entropy_backend="rans",
                blocks=entries,
            )
            metadata["rans_parameters"] = dict(RANS_PARAMETERS)
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
        prediction="delta",
        entropy_backend="rans",
    )


class CompressedRecording:
    """Bounded, read-only array interface accepted by KS4's file_object argument.

    Caller-retained arrays can outlive the reader and consume additional RAM.
    Concurrent consumers should use separate readers or an external lock.
    """

    def __init__(self, path, *, prefetch=True, cache_blocks=None, prefetch_blocks=None, verify_crc=True):
        if cache_blocks is not None and (type(cache_blocks) is not int or cache_blocks < 1):
            raise ValueError("cache_blocks must be a positive integer")
        if prefetch_blocks is not None and (
            type(prefetch_blocks) is not int or not 1 <= prefetch_blocks <= 256
        ):
            raise ValueError("prefetch_blocks must be an integer from 1 to 256")
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
            if (
                metadata.get("format") != "ephypress"
                or type(metadata.get("format_version")) is not int
                or metadata["format_version"] != FORMAT_VERSION
            ):
                raise ValueError("Unsupported EphyPress format version; expected v3")
            if (
                metadata.get("prediction") != "delta"
                or metadata.get("entropy_backend") != "rans"
                or metadata.get("rans_parameters") != RANS_PARAMETERS
                or metadata.get("prediction_parameters") != DELTA_PARAMETERS
                or metadata.get("low_bits") != 0
                or metadata.get("residual_layout") != "channel_int16"
            ):
                raise ValueError("Invalid delta/rANS format parameters")
            self.shape, self.dtype = tuple(metadata["shape"]), np.dtype("<i2")
            self._batch, self._entries = metadata["block_samples"], metadata["blocks"]
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
            if len(self._entries) != (self.shape[0] + self._batch - 1) // self._batch:
                raise ValueError("Invalid block count")
            previous = PREFIX.size
            for block, entry in enumerate(self._entries):
                if len(entry) != 5 or any(type(value) is not int for value in entry):
                    raise ValueError("Invalid block entry")
                position, size, first, last, checksum = entry
                if (
                    position != previous
                    or size < 2074
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
        # Copy returned windows before recycling output blocks; retained user views stay valid.
        cache_blocks = 64 if cache_blocks is None else cache_blocks
        prefetch_blocks = 32 if prefetch_blocks is None else prefetch_blocks
        self._cache_limit, self._prefetch_enabled = cache_blocks, prefetch
        self._prefetch_blocks, self._verify_crc = prefetch_blocks, verify_crc
        self._executor = ThreadPoolExecutor(max_workers=prefetch_blocks, thread_name_prefix="ephypress")
        self._lock = threading.Lock()
        self._local = threading.local()
        self._decoders = []
        self._online_frames = OrderedDict()
        self._free_outputs = queue.LifoQueue(maxsize=prefetch_blocks)
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
            output_buffer_reuses=0,
        )
        self._closed = False

    def _decode_rans(self, block, out):
        if not hasattr(self._local, "decoder"):
            decoder = RansDecoder(self.path)
            self._local.decoder = decoder
            with self._lock:
                self._decoders.append(decoder)
        position, size, first, last, checksum = self._entries[block]
        shape = (last - first, self.shape[1])
        if out is None:
            try:
                candidate = self._free_outputs.get_nowait()
                if candidate.shape == shape:
                    out = candidate
                    out.flags.writeable = True
                    with self._lock:
                        self._stats["output_buffer_reuses"] += 1
            except queue.Empty:
                pass
        return self._local.decoder.decode(position, size, checksum, shape, self._verify_crc, out)

    def _decode(self, block, *, out=None):
        started = time.perf_counter()
        position, size, first, last, checksum = self._entries[block]
        data = self._decode_rans(block, out)
        data.flags.writeable = False
        with self._lock:
            self._stats["decoded_blocks"] += 1
            self._stats["bytes_read"] += size
            self._stats["decode_seconds"] += time.perf_counter() - started
        return data

    def __len__(self):
        return self.shape[0]

    def _read(self, start, stop):
        if start >= stop:
            return np.empty((0, self.shape[1]), dtype=self.dtype)
        data = np.empty((stop - start, self.shape[1]), dtype=self.dtype)
        first_block, last_block = start // self._batch, (stop - 1) // self._batch
        for block in range(first_block, last_block + 1):
            decoded = self._online_block(block)
            a, b = self._entries[block][2:4]
            lo, hi = max(a, start), min(b, stop)
            data[lo - start : hi - start] = decoded[lo - a : hi - a]
        data.flags.writeable = False
        with self._lock:
            self._stats["cross_block_requests"] += int(first_block != last_block)
            self._stats["assembled_bytes"] += data.nbytes
        return data

    def _online_block(self, block):
        width = self._prefetch_blocks if self._prefetch_enabled else 1
        wanted = range(block, min(len(self._entries), block + width))
        limit = max(self._cache_limit, width)
        for nxt in wanted:
            if nxt in self._online_frames:
                continue
            while len(self._online_frames) >= limit:
                victim = next(i for i in self._online_frames if i not in wanted)
                future = self._online_frames.pop(victim)
                if not future.cancel():
                    discarded = future.result()
                    try:
                        self._free_outputs.put_nowait(discarded)
                    except queue.Full:
                        pass
            self._online_frames[nxt] = self._executor.submit(self._decode, nxt)
        future = self._online_frames[block]
        if future.done():
            self._stats["cache_hits"] += 1
        start = time.perf_counter()
        data = future.result()
        self._stats["caller_wait_seconds"] += time.perf_counter() - start
        self._online_frames.move_to_end(block)
        with self._lock:
            self._stats["max_pending_blocks"] = max(self._stats["max_pending_blocks"], width)
            used = sum(
                f.result().nbytes for f in self._online_frames.values() if f.done() and not f.cancelled()
            )
            self._stats["max_decoded_cache_bytes"] = max(self._stats["max_decoded_cache_bytes"], used)
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
        if self._closed:
            raise ValueError("Recording is closed")
        for i in range(len(self._entries)):
            data = self._online_block(i).copy()
            data.flags.writeable = False
            yield data

    def statistics(self):
        with self._lock:
            return dict(
                self._stats,
                cache_blocks=self._cache_limit,
                effective_cache_blocks=max(self._cache_limit, self._prefetch_blocks)
                if self._prefetch_enabled
                else self._cache_limit,
                worker_contexts=len(self._decoders),
                speculative_blocks_limit=self._prefetch_blocks,
                prefetch_enabled=self._prefetch_enabled,
                full_recording_materialized=False,
                raw_disk_cache=False,
            )

    def close(self):
        if not self._closed:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._online_frames.clear()
            for decoder in self._decoders:
                decoder.close()
            self._decoders.clear()
            while not self._free_outputs.empty():
                self._free_outputs.get_nowait()
            self._file.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
