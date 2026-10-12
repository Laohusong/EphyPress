"""The ephypress command line interface."""

import argparse
import json
import sys

from .api import compress, decompress, info, verify


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ephypress", description="Lossless int16 electrophysiology compression"
    )
    parser.add_argument("--version", action="version", version="EphyPress 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)
    encode = sub.add_parser("compress", help="Compress headerless time-major little-endian int16")
    encode.add_argument("source")
    encode.add_argument("destination")
    encode.add_argument("--channels", type=int, required=True)
    encode.add_argument("--fs", type=float, default=30000.0)
    encode.add_argument("--block-samples", type=int, default=60000)
    encode.add_argument("--workers", type=int, default=4)
    encode.add_argument("--profile", choices=["level1", "legacy"], default="level1")
    encode.add_argument("--entropy", choices=["fse", "zstd"], default="fse")
    decode = sub.add_parser("decompress", help="Restore and verify the original int16 bytes")
    decode.add_argument("source")
    decode.add_argument("destination")
    check = sub.add_parser("verify", help="Decode all samples and verify their SHA256")
    check.add_argument("source")
    check.add_argument("--original")
    inspect = sub.add_parser("info", help="Show the checked archive metadata")
    inspect.add_argument("source")
    args = parser.parse_args(argv)
    try:
        if args.command == "compress":
            result = compress(
                args.source,
                args.destination,
                args.channels,
                sampling_frequency=args.fs,
                block_samples=args.block_samples,
                workers=args.workers,
                profile=args.profile,
                entropy_backend=args.entropy,
            )
        elif args.command == "decompress":
            result = decompress(args.source, args.destination)
        elif args.command == "verify":
            result = verify(args.source, original=args.original)
        else:
            result = info(args.source)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, ImportError) as exc:
        print(f"ephypress: {exc}", file=sys.stderr)
        return 1
    return 0
