"""python examples/compress_and_read.py continuous.dat recording.spc --channels 384"""

import argparse

import ephypress as ep

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source")
parser.add_argument("destination")
parser.add_argument("--channels", type=int, required=True)
parser.add_argument("--fs", type=float, default=30000)
args = parser.parse_args()
print(ep.compress(args.source, args.destination, args.channels, sampling_frequency=args.fs))
print(ep.verify(args.destination, original=args.source))
with ep.open_recording(args.destination) as recording:
    print(recording[: min(30000, recording.shape[0])].shape)
