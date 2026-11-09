"""Time full-recording decoding and verified restoration through the public API."""

import argparse
import importlib.metadata
import json
import os
import platform
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import ephypress as ep


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.repeats < 1 or args.output.exists():
        parser.error("Use positive repeats and a new output JSON path")
    metadata = ep.info(args.archive)
    args.scratch.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_logical_count": os.cpu_count(),
        "package": ep.__file__,
        "versions": {name: importlib.metadata.version(name)
                     for name in ("ephypress", "numpy", "zstandard")},
        "archive": str(args.archive.resolve()),
        "archive_bytes": args.archive.stat().st_size,
        "metadata": {k: v for k, v in metadata.items() if k != "blocks"},
        "scratch": str(args.scratch.resolve()),
        "protocol": (
            "Normal OS file cache; no cache eviction or bandwidth cap. Each repeat first "
            "streams decoded blocks to memory, discarding each block, then restores to disk. "
            "Fresh default reader per operation. Timers include reader construction and "
            "close; exclude imports and output deletion. Restoration includes SHA256 "
            "verification, flush, fsync and atomic publication."
        ),
        "runs": [],
    }
    for repeat in range(args.repeats):
        started = time.perf_counter()
        count = 0
        with ep.open_recording(args.archive) as recording:
            for block in recording.iter_cores():
                count += block.nbytes
            del block
        decode_seconds = time.perf_counter() - started
        assert count == metadata["source_bytes"]
        with tempfile.TemporaryDirectory(prefix="ephypress-decode-", dir=args.scratch) as td:
            destination = Path(td) / "restored.dat"
            started = time.perf_counter()
            restored = ep.decompress(args.archive, destination)
            restore_seconds = time.perf_counter() - started
            assert restored["bytes"] == destination.stat().st_size == count
            assert restored["sha256"] == metadata["source_sha256"]
        run = dict(repeat=repeat + 1, decode_to_memory_seconds=decode_seconds,
                   restore_to_disk_seconds=restore_seconds, verification=restored)
        report["runs"].append(run)
        report["median_seconds"] = {
            key: statistics.median(r[key] for r in report["runs"])
            for key in ("decode_to_memory_seconds", "restore_to_disk_seconds")
        }
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(run), flush=True)


if __name__ == "__main__":
    main()
