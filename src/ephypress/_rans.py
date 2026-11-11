"""Packaged delta/rANS bindings and reusable per-worker decode resources."""

import ctypes
import zlib

import numpy as np

from ._native import _check_result, encode_channels16, library

PARAMETERS = dict(scale_bits=14, lanes=4, escape_symbol=1024, model="block_unconditional")
HEADER_BYTES = 2074


def encode(data):
    residual = np.frombuffer(encode_channels16(data), dtype="<i2").astype("=i2", copy=False)
    output = np.empty(residual.size * 4 + HEADER_BYTES, dtype="u1")
    size = library().ephypress_rans_encode(
        residual.ctypes.data, residual.size, output.ctypes.data, output.size
    )
    if size < 0:
        _check_result(size)
    return output[:size].tobytes()


class Decoder:
    """One stream, compressed buffer and native workspace per active worker."""

    def __init__(self, path):
        self.stream = None
        self.context = None
        self.native = library()
        self.context = self.native.ephypress_rans_create()
        if not self.context:
            raise MemoryError("Cannot allocate rANS decoder")
        self.buffer = bytearray()
        try:
            self.stream = open(path, "rb")
        except BaseException:
            self.close()
            raise

    def decode(self, position, size, checksum, shape, verify_crc, out=None):
        if len(self.buffer) < size:
            self.buffer = bytearray(size)
        payload = memoryview(self.buffer)[:size]
        self.stream.seek(position)
        if self.stream.readinto(payload) != size or (verify_crc and zlib.crc32(payload) != checksum):
            raise ValueError("Block checksum mismatch or truncation")
        if out is None:
            out = np.empty(shape, dtype="<i2")
        if (
            not isinstance(out, np.ndarray)
            or out.shape != tuple(shape)
            or out.dtype != np.dtype("<i2")
            or not out.flags.c_contiguous
            or not out.flags.writeable
        ):
            raise ValueError("Invalid decode destination")
        # Native output is int16; byteswap on big-endian hosts for the public <i2 contract.
        pointer = (ctypes.c_uint8 * size).from_buffer(payload)
        _check_result(self.native.ephypress_rans_decode(self.context, pointer, size, *shape, out.ctypes.data))
        if not np.little_endian:
            out.byteswap(inplace=True)
        return out

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        if self.context:
            self.native.ephypress_rans_destroy(self.context)
            self.context = None
        self.buffer = bytearray()

    def __del__(self):
        self.close()
