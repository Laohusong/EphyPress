#!/usr/bin/env python3
"""Opt-in GPU validation on a user-supplied int16 recording; data are never uploaded."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def worker(args):
    import importlib.metadata
    import random

    import numpy as np
    import torch
    from kilosort.io import load_probe

    import ephypress

    torch.set_num_threads(8)
    random.seed(1)
    np.random.seed(1)
    torch.manual_seed(1)
    torch.cuda.manual_seed_all(1)
    probe = load_probe(args.probe)
    archive = args.output / "recording.spc"
    settings = dict(n_chan_bin=args.channels, fs=args.fs, batch_size=60000)
    if args.duration is not None:
        settings["tmax"] = args.duration
    started = time.perf_counter()
    if args.worker == "raw":
        from kilosort import run_kilosort

        run_kilosort(
            settings=settings,
            probe=probe,
            filename=args.raw,
            results_dir=args.output / "raw",
            data_dtype="int16",
            torch_thread_lim=8,
        )
        results = args.output / "raw"
    elif args.worker == "direct":
        ephypress.run_kilosort(
            archive, settings=settings, probe=probe, results_dir=args.output / "direct", torch_thread_lim=8
        )
        results = args.output / "direct"
    else:
        from spikeinterface.sorters import run_sorter

        with ephypress.read_ephypress(archive) as recording:
            recording.set_channel_locations(np.column_stack([probe["xc"], probe["yc"]]))
            params = dict(
                use_binary_file=False,
                save_preprocessed_copy=False,
                torch_device="cuda",
                batch_size=60000,
                verbose=True,
            )
            if args.duration is not None:
                recording = recording.frame_slice(start_frame=0, end_frame=int(args.duration * args.fs))
            run_sorter("kilosort4", recording, folder=args.output / "spikeinterface", **params)
        results = args.output / "spikeinterface/sorter_output"
    torch.cuda.synchronize()
    assert not list(results.rglob("recording.dat")), "An unexpected full raw copy was written"
    report = dict(
        method=args.worker,
        status="success",
        seconds=time.perf_counter() - started,
        spikes=int(np.load(results / "spike_times.npy").size),
        units=int(np.unique(np.load(results / "spike_clusters.npy")).size),
        results=str(results),
        GPU=torch.cuda.get_device_name(0),
        versions={
            name: importlib.metadata.version(name)
            for name in ("ephypress", "numpy", "spikeinterface", "kilosort", "torch")
        },
    )
    (args.output / (args.worker + ".json")).write_text(json.dumps(report, indent=2) + "\n")


def main(args):
    import ephypress

    args.output.mkdir(parents=True, exist_ok=False)
    compressed = ephypress.compress(
        args.raw, args.output / "recording.spc", args.channels, sampling_frequency=args.fs
    )
    verified = ephypress.verify(args.output / "recording.spc", original=args.raw)
    (args.output / "input.json").write_text(
        json.dumps(dict(compression=compressed, verification=verified), indent=2) + "\n"
    )
    environment = dict(
        os.environ,
        **{
            key: "8"
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMBA_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
    )
    for method in ("raw", "direct", "spikeinterface"):
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--raw",
            str(args.raw),
            "--probe",
            str(args.probe),
            "--channels",
            str(args.channels),
            "--fs",
            str(args.fs),
            "--output",
            str(args.output),
            "--worker",
            method,
        ]
        if args.duration is not None:
            command += ["--duration", str(args.duration)]
        with (args.output / (method + ".log")).open("w") as log:
            subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(method + " complete", flush=True)
    print(
        "Validated full native KS4 and SpikeInterface Kilosort4 pipelines. Outputs remain local.", flush=True
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--channels", type=int, required=True)
    parser.add_argument("--fs", type=float, default=30000)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", choices=["raw", "direct", "spikeinterface"])
    args = parser.parse_args()
    args.raw, args.probe, args.output = args.raw.resolve(), args.probe.resolve(), args.output.resolve()
    worker(args) if args.worker else main(args)
