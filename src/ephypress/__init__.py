"""Lossless electrophysiology compression and bounded, on-demand readers."""

from .api import compress, decompress, info, open_recording, verify

__version__ = "0.2.0"
__all__ = [
    "compress",
    "decompress",
    "info",
    "open_recording",
    "verify",
    "read_ephypress",
    "write_recording",
    "run_kilosort",
]


def read_ephypress(*args, **kwargs):
    from .spikeinterface import read_ephypress as read

    return read(*args, **kwargs)


def write_recording(*args, **kwargs):
    from .spikeinterface import write_recording as write

    return write(*args, **kwargs)


def run_kilosort(*args, **kwargs):
    from .kilosort import run_kilosort as run

    return run(*args, **kwargs)
