"""Optional direct KS4 integration through its public file_object interface."""

from pathlib import Path

from .api import open_recording


def run_kilosort(path, *, settings=None, probe=None, results_dir=None, reader_options=None, **kwargs):
    """Run full KS4 on compressed samples without a raw or preprocessed disk copy.

    Install the ks4 extra and an appropriate PyTorch/CUDA build. Supply real probe
    geometry through probe, probe_name or settings['probe_path']. The returned
    tuple is the original Kilosort result. All other kwargs pass through to KS4.
    """
    try:
        from kilosort import run_kilosort as run
    except ImportError as exc:
        raise ImportError("Install EphyPress with the ks4 extra to run Kilosort4") from exc
    if any(key in kwargs for key in ("file_object", "filename", "data_dtype", "data_dir")):
        raise ValueError("The compressed source determines file_object, filename, data_dtype and data_dir")
    path = Path(path).resolve()
    results_dir = Path(results_dir) if results_dir is not None else path.parent / "kilosort4"
    if results_dir.exists() and any(results_dir.iterdir()):
        raise FileExistsError("Use an empty results directory to preserve existing sorting output")
    with open_recording(path, **(reader_options or {})) as reader:
        options = dict(settings or {})
        if options.get("n_chan_bin", reader.shape[1]) != reader.shape[1]:
            raise ValueError("n_chan_bin differs from the archive channel count")
        if options.get("fs", reader.metadata["sampling_frequency"]) != reader.metadata["sampling_frequency"]:
            raise ValueError("fs differs from the archive sampling frequency")
        options.update(n_chan_bin=reader.shape[1], fs=reader.metadata["sampling_frequency"])
        kwargs.setdefault("save_preprocessed_copy", False)
        return run(
            settings=options,
            probe=probe,
            filename=path,
            file_object=reader,
            results_dir=results_dir,
            data_dtype="int16",
            **kwargs,
        )
