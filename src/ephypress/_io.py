"""Native desktop file operations, including thread-safe Windows positioned reads."""

import os
import threading
from pathlib import Path


class PositionedFile:
    """Read fixed offsets without sharing an unprotected seek cursor between workers."""

    def __init__(self, path):
        self.path = Path(path)
        self._fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        self._pread = getattr(os, "pread", None)
        self._lock = threading.Lock()
        self._closed = False

    @property
    def size(self):
        return os.fstat(self._fd).st_size

    def read_at(self, length, offset):
        if self._closed:
            raise ValueError("File is closed")
        if length < 0 or offset < 0:
            raise ValueError("Read length and offset must be nonnegative")
        if self._pread is not None:
            return self._read_exact(length, offset)
        with self._lock:
            os.lseek(self._fd, offset, os.SEEK_SET)
            return self._read_exact(length, None)

    def _read_exact(self, length, offset):
        parts, remaining = [], length
        while remaining:
            size = min(remaining, 8 * 1024**2)
            block = os.read(self._fd, size) if offset is None else self._pread(self._fd, size, offset)
            if not block:
                break
            parts.append(block)
            remaining -= len(block)
            if offset is not None:
                offset += len(block)
        return b"".join(parts)

    def close(self):
        if not self._closed:
            os.close(self._fd)
            self._closed = True


def publish_file(temporary, destination):
    """Publish a completed file exclusively, preserving a concurrently created target."""
    if os.name == "nt":
        # Windows rename fails if destination exists and works without hard links.
        os.rename(temporary, destination)
    else:
        os.link(temporary, destination)
