"""ctypes bindings for the packaged C++ codec; no runtime compiler required."""

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

        lib = ctypes.CDLL(_codec.__file__)
        pointer = ctypes.c_void_p
        args = [
            pointer,
            ctypes.c_uint64,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            pointer,
            pointer,
        ]
        lib.spc_encode.argtypes = args
        lib.spc_decode.argtypes = [pointer, pointer, *args[1:6], pointer]
        lib.spc_encode.restype = lib.spc_decode.restype = ctypes.c_int
        lib.spc_decode_groups.argtypes = [
            pointer,
            ctypes.c_uint64,
            ctypes.c_uint64,
            ctypes.c_uint32,
            ctypes.c_uint32,
            pointer,
            pointer,
        ]
        lib.spc_decode_groups.restype = ctypes.c_int
        _library = lib
        return lib


def encode_planes(data, quantum=1, predictor=5, low_bits=6):
    data = np.ascontiguousarray(data, dtype="<i2")
    if data.ndim != 2 or not data.size:
        raise ValueError("Expected a nonempty time × channel array")
    n = data.shape[0] * (data.shape[1] + (predictor == 14))
    m = (n + 7) // 8 * 8
    low = np.empty(m // 8 * low_bits, dtype="u1")
    high = np.empty(m * 2, dtype="u1")
    ret = library().spc_encode(
        data.ctypes.data, *data.shape, quantum, predictor, low_bits, low.ctypes.data, high.ctypes.data
    )
    if ret:
        raise ValueError("Invalid codec parameters")
    return low, high


def decode_planes(low, high, shape, quantum=1, predictor=5, low_bits=6, *, out=None):
    low = np.frombuffer(low, dtype="u1")
    high = np.frombuffer(high, dtype="u1")
    n = int(shape[0]) * (int(shape[1]) + (predictor == 14))
    m = (n + 7) // 8 * 8
    if low.size != m // 8 * low_bits or high.size != m * 2:
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
    ret = library().spc_decode(
        low.ctypes.data, high.ctypes.data, *shape, quantum, predictor, low_bits, out.ctypes.data
    )
    if ret:
        raise ValueError("Invalid codec parameters")
    return out


def decode_groups(primary, rows, width, group, output):
    """Checked batched FSE decode, preserving all existing packet encodings."""
    from ._entropy import library as entropy_library

    primary = np.frombuffer(primary, dtype="u1")
    if (
        not isinstance(rows, int)
        or not isinstance(width, int)
        or not isinstance(group, int)
        or rows < 1
        or width < 1
        or group < 1
        or width > 2**32 - 1
        or group > 2**32 - 1
        or output.dtype != np.dtype("u1")
        or not output.flags.c_contiguous
        or not output.flags.writeable
        or output.size != rows * width
    ):
        raise ValueError("Invalid grouped entropy dimensions or output")
    decoder = ctypes.cast(entropy_library().FSE_decompress, ctypes.c_void_p)
    ret = library().spc_decode_groups(
        primary.ctypes.data, primary.size, rows, width, group, output.ctypes.data, decoder
    )
    if ret:
        raise ValueError("Invalid grouped FSE entropy packets")
