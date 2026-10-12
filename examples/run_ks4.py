"""python examples/run_ks4.py recording.spc ProbeA.json ks4_output"""

import argparse

from kilosort.io import load_probe

import ephypress as ep

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("archive")
parser.add_argument("probe")
parser.add_argument("output")
args = parser.parse_args()
ep.run_kilosort(args.archive, probe=load_probe(args.probe), results_dir=args.output, torch_thread_lim=8)
