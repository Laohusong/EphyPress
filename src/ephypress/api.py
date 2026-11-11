"""Public, lossless-only file API."""

import hashlib
import os
import tempfile
from pathlib import Path

import numpy as np

from ._container import CompressedRecording, write_blocks
from ._io import publish_file


def compress(
    source,
    destination,
    n_channels,
    *,
    sampling_frequency=30000.0,
    block_samples=60000,
    workers=4,
    progress=None,
):
    """Compress headerless, time-major little-endian int16 to an .ep archive.

    Each block uses reversible temporal differences and four-lane rANS.
    workers controls concurrent storage blocks. No quantization occurs.
    """
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("Input and output must differ")
    if type(n_channels) is not int or n_channels < 1:
        raise ValueError("n_channels must be a positive integer")
    size = source.stat().st_size
    if not size or size % (n_channels * 2):
        raise ValueError("Input must contain whole, nonempty int16 channel frames")
    data = np.memmap(source, dtype="<i2", mode="r", shape=(size // (n_channels * 2), n_channels))
    try:
        return write_blocks(
            lambda a, b: data[a:b],
            destination,
            data.shape,
            sampling_frequency=sampling_frequency,
            block_samples=block_samples,
            workers=workers,
            progress=progress,
        )
    finally:
        data._mmap.close()


def open_recording(path, *, prefetch=True, cache_blocks=None, prefetch_blocks=None, verify_crc=True):
    """Open a read-only, on-demand v3 recording.

    Defaults to 32 workers/lookahead blocks and 64 retained blocks. Returned
    arrays own their samples and remain valid after the reader is closed.
    Use a context manager or close() to release descriptors and workers.
    """
    return CompressedRecording(
        path,
        prefetch=prefetch,
        cache_blocks=cache_blocks,
        prefetch_blocks=prefetch_blocks,
        verify_crc=verify_crc,
    )


def info(path):
    """Return the checked archive metadata, without decoding any samples."""
    with CompressedRecording(path, prefetch=False) as reader:
        return dict(reader.metadata)


def verify(path, *, original=None):
    """Decode every core sample, verify SHA256, and optionally compare the source."""
    digest, count = hashlib.sha256(), 0
    source = None
    try:
        with open_recording(path) as reader:
            if original is not None:
                if Path(original).stat().st_size != reader.size * 2:
                    raise ValueError("Original file size differs from archive shape")
                source = np.memmap(original, mode="r", dtype="<i2", shape=reader.shape)
            for block in reader.iter_cores():
                if source is not None:
                    start = count // (reader.shape[1] * 2)
                    if not np.array_equal(block, source[start : start + len(block)]):
                        raise ValueError("Reconstructed samples differ from original")
                raw = memoryview(np.ascontiguousarray(block)).cast("B")
                digest.update(raw)
                count += len(raw)
            if (
                count != reader.metadata["source_bytes"]
                or digest.hexdigest() != reader.metadata["source_sha256"]
            ):
                raise ValueError("Lossless reconstruction SHA256 mismatch")
    finally:
        if source is not None:
            source._mmap.close()
    return dict(
        path=str(path),
        bytes=count,
        sha256=digest.hexdigest(),
        exact_equal=True,
        max_abs_error=0,
        original_compared=original is not None,
    )


def decompress(source, destination):
    """Restore an .ep archive to int16 bytes atomically and verify the source SHA256."""
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("Input and output must differ")
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix="." + destination.name + ".", suffix=".partial", dir=destination.parent
    )
    temporary = Path(temporary)
    digest, count = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as output, open_recording(source) as reader:
            for block in reader.iter_cores():
                raw = memoryview(np.ascontiguousarray(block)).cast("B")
                digest.update(raw)
                count += output.write(raw)
            if (
                count != reader.metadata["source_bytes"]
                or digest.hexdigest() != reader.metadata["source_sha256"]
            ):
                raise ValueError("Lossless restoration SHA256 mismatch")
            output.flush()
            os.fsync(output.fileno())
        publish_file(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(path=str(destination), bytes=count, sha256=digest.hexdigest(), exact_equal=True)
