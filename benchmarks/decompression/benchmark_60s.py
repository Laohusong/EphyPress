"""Measure default EphyPress public operations on the same real recording."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import ephypress as ep
from ephypress import _codec

EXPECTED_SHA = "4ced250fc348bad8317ab1d335077a7da9e0b79722c05b3d3578977c48279252"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = args.raw.stat().st_size
    assert raw_bytes == 1382400000
    # Warm input pages and validate that both hosts use exactly the same bytes.
    digest = hashlib.sha256()
    with args.raw.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(block)
    assert digest.hexdigest() == EXPECTED_SHA
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_logical_count": os.cpu_count(),
        "package": ep.__file__,
        "versions": {name: importlib.metadata.version(name) for name in ("ephypress", "numpy", "zstandard")},
        "openmp_enabled": _codec.openmp_enabled,
        "raw": str(args.raw),
        "raw_bytes": raw_bytes,
        "source_sha256": EXPECTED_SHA,
        "recording_seconds": 60,
        "channels": 384,
        "sampling_frequency": 30000,
        "settings": {"prediction": "temporal", "entropy": "fse", "block_samples": 60000, "workers": 4,
                     "reader_mode": "auto", "prefetch": True, "prefetch_blocks": 4, "cache_blocks": 2},
        "cache_policy": "Warm source pages; archives freshly written/cached. No OS cache eviction. fsync included for compression/restoration. Python startup excluded.",
        "runs": [],
    }
    with tempfile.TemporaryDirectory(prefix="ephypress-speed-", dir=args.scratch) as td:
        directory = Path(td)
        for repeat in range(3):
            archive, restored = directory / "recording.ep", directory / "restored.dat"
            run = {"repeat": repeat + 1}
            started = time.perf_counter()
            compressed = ep.compress(args.raw, archive, 384, sampling_frequency=30000, workers=4)
            run["compress_seconds"] = time.perf_counter() - started
            assert compressed["source_sha256"] == EXPECTED_SHA
            run["archive_bytes"], run["ratio"] = archive.stat().st_size, compressed["ratio"]
            started = time.perf_counter()
            count = 0
            with ep.open_recording(archive) as reader:
                for block in reader.iter_cores():
                    count += block.nbytes
                del block
            run["decode_to_memory_seconds"] = time.perf_counter() - started
            assert count == raw_bytes
            started = time.perf_counter()
            verification = ep.verify(archive)
            run["verify_seconds"] = time.perf_counter() - started
            assert verification["sha256"] == EXPECTED_SHA
            started = time.perf_counter()
            restored_report = ep.decompress(archive, restored)
            run["restore_to_disk_seconds"] = time.perf_counter() - started
            assert restored_report["sha256"] == EXPECTED_SHA
            assert restored.stat().st_size == raw_bytes
            report["runs"].append(run)
            print(json.dumps(run), flush=True)
            archive.unlink()
            restored.unlink()
    report["median"] = {}
    for operation in ("compress", "decode_to_memory", "verify", "restore_to_disk"):
        seconds = statistics.median(r[operation + "_seconds"] for r in report["runs"])
        report["median"][operation] = {
            "seconds": seconds,
            "raw_MB_per_second": raw_bytes / seconds / 1e6,
            "recording_realtime_multiple": 60 / seconds,
        }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["median"], indent=2), flush=True)


if __name__ == "__main__":
    main()
