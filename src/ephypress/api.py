"""Public, lossless-only file API."""

import hashlib
import os
import tempfile
from pathlib import Path

import numpy as np

from ._container import CompressedRecording, write_blocks


def compress(
    source,
    destination,
    n_channels,
    *,
    sampling_frequency=30000.0,
    block_samples=60000,
    workers=4,
    profile="level1",
    entropy_backend="fse",
    zstd_level=3,
    progress=None,
):
    """Compress headerless, time-major little-endian int16 without quantization.

    ``level1`` is p53/q1/k4/FSEgroup1/halo0; ``legacy`` is p41 with halo61.
    workers controls concurrent storage blocks; OpenMP kernels use two threads
    per phase on Linux builds with OpenMP enabled.
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
            profile=profile,
            entropy_backend=entropy_backend,
            zstd_level=zstd_level,
            progress=progress,
        )
    finally:
        data._mmap.close()


def open_recording(
    path,
    *,
    reader_mode="auto",
    prefetch=True,
    cache_blocks=2,
    prefetch_blocks=4,
    verify_crc=True,
    pool_frames=4,
):
    """Open an array-like, read-only reader without expanding the full recording.

    auto selects Linux RAM page remapping when available, otherwise normal block
    assembly. Use a context manager or close() to release descriptors and workers.
    """
    if reader_mode not in ("auto", "blocks", "mapped"):
        raise ValueError("reader_mode must be 'auto', 'blocks' or 'mapped'")
    from ._mapping import _SHARED_AVAILABLE

    if reader_mode == "mapped" and not _SHARED_AVAILABLE:
        raise ValueError("Mapped mode requires Linux memfd/mmap; use auto or blocks")
    kwargs = dict(
        prefetch=prefetch, cache_blocks=cache_blocks, prefetch_blocks=prefetch_blocks, verify_crc=verify_crc
    )
    if reader_mode == "mapped" or (reader_mode == "auto" and _SHARED_AVAILABLE):
        from ._mapped import MappedRecording

        return MappedRecording(path, pool_frames=pool_frames, **kwargs)
    return CompressedRecording(path, **kwargs)


def info(path):
    """Return the checked archive metadata, without decoding any samples."""
    with CompressedRecording(path, prefetch=False) as reader:
        return dict(reader.metadata)


def verify(path, *, original=None, reader_mode="auto"):
    """Decode every core sample, verify SHA256, and optionally compare the source."""
    digest, count = hashlib.sha256(), 0
    source = None
    try:
        with open_recording(path, reader_mode=reader_mode) as reader:
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


def decompress(source, destination, *, reader_mode="auto"):
    """Restore headerless int16 bytes atomically and verify the original SHA256."""
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
        with os.fdopen(fd, "wb") as output, open_recording(source, reader_mode=reader_mode) as reader:
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
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(path=str(destination), bytes=count, sha256=digest.hexdigest(), exact_equal=True)
