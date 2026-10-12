"""Byte entropy packets backed by the bundled, BSD-licensed FSE implementation."""

import ctypes
import threading

import numpy as np

_lib = None
_lock = threading.Lock()


def library():
    global _lib
    with _lock:
        if _lib is not None:
            return _lib
        from . import _codec

        lib = ctypes.CDLL(_codec.__file__)
        ptr, size = ctypes.c_void_p, ctypes.c_size_t
        for name in ["FSE_compress", "FSE_decompress"]:
            fn = getattr(lib, name)
            fn.argtypes = [ptr, size, ptr, size]
            fn.restype = size
        lib.FSE_compress2.argtypes = [ptr, size, ptr, size, ctypes.c_uint, ctypes.c_uint]
        lib.FSE_compress2.restype = size
        lib.FSE_compressBound.argtypes = [size]
        lib.FSE_compressBound.restype = size
        lib.FSE_isError.argtypes = [size]
        lib.FSE_isError.restype = ctypes.c_uint
        lib.FSE_getErrorName.argtypes = [size]
        lib.FSE_getErrorName.restype = ctypes.c_char_p
        _lib = lib
        return lib


def _check(lib, n):
    if lib.FSE_isError(n):
        raise ValueError("FSE: " + lib.FSE_getErrorName(n).decode())


def encode_bytes(data):
    data = np.ascontiguousarray(data, dtype="u1").ravel()
    if not data.size:
        return b"\x00"
    lib = library()
    bound = lib.FSE_compressBound(data.size)
    _check(lib, bound)
    out = np.empty(bound, dtype="u1")
    n = lib.FSE_compress2(out.ctypes.data, out.size, data.ctypes.data, data.size, 0, 12)
    _check(lib, n)
    if n == 0:
        return b"\x00" + data.tobytes()
    if n == 1:
        return b"\x02" + bytes([int(data[0])])
    return b"\x01" + out[:n].tobytes()


def decode_bytes(packet, count):
    packet = np.frombuffer(packet, dtype="u1")
    if not packet.size or count < 0:
        raise ValueError("Invalid entropy packet")
    mode = int(packet[0])
    if mode == 0:
        if packet.size != count + 1:
            raise ValueError("Invalid raw entropy packet length")
        return packet[1:].copy()
    if mode == 2:
        if packet.size != 2:
            raise ValueError("Invalid RLE entropy packet length")
        return np.full(count, packet[1], dtype="u1")
    if mode != 1 or packet.size < 3:
        raise ValueError("Invalid FSE entropy packet")
    lib = library()
    out = np.empty(count, dtype="u1")
    n = lib.FSE_decompress(out.ctypes.data, count, packet[1:].ctypes.data, packet.size - 1)
    _check(lib, n)
    if n != count:
        raise ValueError("FSE output length mismatch")
    return out
