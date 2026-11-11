"""Bindings for the packaged delta/rANS codec."""

import ctypes
import threading

import numpy as np

_library = None
_lock = threading.Lock()


def library():
    global _library
    with _lock:
        if _library is not None:
            return _library
        from . import _codec

        native = ctypes.CDLL(_codec.__file__)
        pointer = ctypes.c_void_p
        native.ephypress_encode_delta_channels16.argtypes = [
            pointer,
            ctypes.c_uint64,
            ctypes.c_uint32,
            pointer,
        ]
        native.ephypress_encode_delta_channels16.restype = ctypes.c_int
        native.ephypress_rans_create.argtypes = []
        native.ephypress_rans_create.restype = pointer
        native.ephypress_rans_destroy.argtypes = [pointer]
        native.ephypress_rans_destroy.restype = None
        native.ephypress_rans_decode.argtypes = [
            pointer,
            pointer,
            ctypes.c_uint64,
            ctypes.c_uint64,
            ctypes.c_uint32,
            pointer,
        ]
        native.ephypress_rans_decode.restype = ctypes.c_int
        native.ephypress_rans_encode.argtypes = [pointer, ctypes.c_uint64, pointer, ctypes.c_uint64]
        native.ephypress_rans_encode.restype = ctypes.c_int64
        _library = native
        return native


def _check_result(result):
    if result == -2:
        raise MemoryError("The native codec could not allocate a working buffer")
    if result:
        raise ValueError("Invalid codec parameters or entropy packets")


def encode_channels16(data):
    """Return channel-major, little-endian modular temporal residuals."""
    data = np.ascontiguousarray(data, dtype="=i2")
    if data.ndim != 2 or not data.size or data.shape[1] >= 2**32:
        raise ValueError("Expected a nonempty time ? channel int16 array")
    output = np.empty(data.nbytes, dtype="u1")
    _check_result(
        library().ephypress_encode_delta_channels16(data.ctypes.data, *data.shape, output.ctypes.data)
    )
    return output
