"""python examples/spikeinterface_ks4.py recording.spc ProbeA.json ks4_si_output"""

import argparse

import numpy as np
import spikeinterface.sorters as ss
from kilosort.io import load_probe

from ephypress.spikeinterface import read_ephypress

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("archive")
parser.add_argument("probe")
parser.add_argument("output")
args = parser.parse_args()
probe = load_probe(args.probe)
with read_ephypress(args.archive) as recording:
    if len(probe["xc"]) != recording.get_num_channels():
        raise ValueError("Use a probe covering every file column or explicitly select electrode channels")
    recording.set_channel_locations(np.column_stack([probe["xc"], probe["yc"]]))
    ss.run_sorter(
        "kilosort4",
        recording,
        folder=args.output,
        use_binary_file=False,
        save_preprocessed_copy=False,
        torch_device="cuda",
        verbose=True,
    )
