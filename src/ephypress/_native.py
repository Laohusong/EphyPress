"""Bindings for the packaged, named lossless prediction kernels."""

import ctypes
import threading

import numpy as np

from ._prediction import PREDICTIONS

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
        for prediction in PREDICTIONS:
            encode = getattr(native, f"ephypress_encode_{prediction}")
            encode.argtypes = [pointer, ctypes.c_uint64, ctypes.c_uint32, pointer, pointer]
            encode.restype = ctypes.c_int
            decode = getattr(native, f"ephypress_decode_{prediction}")
            decode.argtypes = [pointer, pointer, ctypes.c_uint64, ctypes.c_uint32, pointer]
            decode.restype = ctypes.c_int
        native.ephypress_decode_channels.argtypes = [
            pointer,
            ctypes.c_uint64,
            ctypes.c_uint64,
            ctypes.c_uint32,
            pointer,
        ]
        native.ephypress_decode_channels.restype = ctypes.c_int
        _library = native
        return native


def _check_result(result):
    if result == -2:
        raise MemoryError("The native codec could not allocate a working buffer")
    if result:
        raise ValueError("Invalid codec parameters or entropy packets")


def encode_planes(data, prediction="temporal"):
    if prediction not in PREDICTIONS:
        raise ValueError("Unknown prediction mode")
    data = np.ascontiguousarray(data, dtype="<i2")
    if data.ndim != 2 or not data.size:
        raise ValueError("Expected a nonempty time × channel array")
    padded_count = (data.size + 7) // 8 * 8
    low = np.empty(padded_count // 2, dtype="u1")
    high = np.empty(padded_count * 2, dtype="u1")
    encode = getattr(library(), f"ephypress_encode_{prediction}")
    _check_result(encode(data.ctypes.data, *data.shape, low.ctypes.data, high.ctypes.data))
    return low, high


def decode_planes(low, high, shape, prediction="temporal", *, out=None):
    if prediction not in PREDICTIONS:
        raise ValueError("Unknown prediction mode")
    low, high = np.frombuffer(low, dtype="u1"), np.frombuffer(high, dtype="u1")
    count = int(shape[0]) * int(shape[1])
    padded_count = (count + 7) // 8 * 8
    if low.size != padded_count // 2 or high.size != padded_count * 2:
        raise ValueError("Invalid residual plane lengths")
    if out is None:
        out = np.empty(shape, dtype="<i2")
    elif (
        not isinstance(out, np.ndarray)
        or out.dtype != np.dtype("<i2")
        or out.shape != tuple(shape)
        or not out.flags.c_contiguous
        or not out.flags.writeable
    ):
        raise ValueError("Invalid decode destination")
    decode = getattr(library(), f"ephypress_decode_{prediction}")
    _check_result(decode(low.ctypes.data, high.ctypes.data, *shape, out.ctypes.data))
    return out


def decode_channels(primary, rows, channels, output):
    primary = np.frombuffer(primary, dtype="u1")
    if (
        type(rows) is not int
        or type(channels) is not int
        or rows < 1
        or not 1 <= channels < 2**32
        or output.dtype != np.dtype("u1")
        or not output.flags.c_contiguous
        or not output.flags.writeable
        or output.size != rows * channels
    ):
        raise ValueError("Invalid channel packet dimensions or output")
    _check_result(
        library().ephypress_decode_channels(
            primary.ctypes.data, primary.size, rows, channels, output.ctypes.data
        )
    )
