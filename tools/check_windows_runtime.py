"""Check that a Windows codec wheel needs no separately installed C++/OpenMP DLLs."""

import sys


def main():
    if sys.platform != "win32":
        return
    import pefile

    from ephypress import _codec

    with pefile.PE(_codec.__file__) as image:
        dependencies = [entry.dll.decode("ascii").lower() for entry in image.DIRECTORY_ENTRY_IMPORT]
    print("Native codec DLL imports:", dependencies)
    extra_runtimes = ("msvcp", "vcomp", "libomp", "libiomp", "concrt")
    if any(name.startswith(extra_runtimes) for name in dependencies):
        raise RuntimeError("Codec depends on an unbundled C++/OpenMP runtime")
    assert _codec.openmp_enabled == 0


if __name__ == "__main__":
    main()
