"""Linux RAM mapping primitives; other platforms use the portable block reader."""

import ctypes
import mmap
import os
import sys

PAGE = mmap.PAGESIZE
_LIBC = None
if sys.platform == "linux":
    _LIBC = ctypes.CDLL(None, use_errno=True)
    _LIBC.mmap.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_long,
    ]
    _LIBC.mmap.restype = ctypes.c_void_p
    if hasattr(_LIBC, "memfd_create"):
        _LIBC.memfd_create.argtypes = [ctypes.c_char_p, ctypes.c_uint]
        _LIBC.memfd_create.restype = ctypes.c_int
_SHARED_AVAILABLE = sys.platform == "linux" and (
    hasattr(os, "memfd_create") or hasattr(_LIBC, "memfd_create")
)


def _memory_fd():
    fd = (
        os.memfd_create("spc-decode-window", 1)
        if hasattr(os, "memfd_create")
        else _LIBC.memfd_create(b"spc-decode-window", 1)
    )
    if fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return fd
