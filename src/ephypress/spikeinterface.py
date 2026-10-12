"""Optional SpikeInterface BaseRecording extractor and streaming writer."""

import os
import threading
from pathlib import Path

import numpy as np

try:
    from spikeinterface.core import BaseRecording, BaseRecordingSegment
except ImportError as exc:
    raise ImportError("Install EphyPress with the spikeinterface extra to use this module") from exc

from ._container import write_blocks
from .api import info, open_recording


class EphyPressRecordingExtractor(BaseRecording):
    """One-segment, serializable recording whose traces are decoded on demand.

    Construction reads only the checked index. Each process lazily creates its
    own reader. For multiprocess jobs use spawn, not fork with active readers.
    """

    def __init__(self, file_path, *, reader_mode="auto", prefetch=True, cache_blocks=2, prefetch_blocks=4):
        path = Path(file_path).expanduser().resolve()
        metadata = info(path)
        extra = metadata.get("ephypress_metadata", {})
        channel_ids = extra.get("channel_ids", list(range(metadata["shape"][1])))
        if len(channel_ids) != metadata["shape"][1]:
            raise ValueError("Stored channel IDs do not match the archive channel count")
        super().__init__(
            sampling_frequency=metadata["sampling_frequency"], channel_ids=channel_ids, dtype="int16"
        )
        options = dict(
            reader_mode=reader_mode,
            prefetch=prefetch,
            cache_blocks=cache_blocks,
            prefetch_blocks=prefetch_blocks,
        )
        self.add_recording_segment(_EphyPressSegment(path, metadata, options))
        if "probegroup" in extra:
            from probeinterface import ProbeGroup

            self.set_probegroup(ProbeGroup.from_dict(extra["probegroup"]), in_place=True)
        for key, values in extra.get("channel_properties", {}).items():
            self.set_property(key, np.asarray(values))
        self._kwargs = dict(file_path=str(path), **options)
        self.annotate(is_filtered=extra.get("is_filtered", False))

    def close(self):
        for segment in self._recording_segments:
            segment.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _EphyPressSegment(BaseRecordingSegment):
    def __init__(self, path, metadata, options):
        super().__init__(
            sampling_frequency=metadata["sampling_frequency"],
            t_start=metadata.get("ephypress_metadata", {}).get("t_start"),
        )
        self.path, self.samples, self.options = str(path), metadata["shape"][0], options
        self._reader = None
        self._pid = os.getpid()
        self._lock = threading.Lock()

    def get_num_samples(self):
        return self.samples

    def get_traces(self, start_frame, end_frame, channel_indices):
        if os.getpid() != self._pid:
            if self._reader is not None:
                raise RuntimeError(
                    "An active EphyPress reader was inherited by fork; use spawn or reload the extractor"
                )
            self._pid, self._lock = os.getpid(), threading.Lock()
        with self._lock:
            if self._reader is None:
                self._reader = open_recording(self.path, **self.options)
            return self._reader[start_frame:end_frame, channel_indices]

    def close(self):
        with self._lock:
            if self._reader is not None:
                self._reader.close()
                self._reader = None

    def __getstate__(self):
        state = self.__dict__.copy()
        state.update(_reader=None, _lock=None, _pid=None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._lock, self._pid = threading.Lock(), os.getpid()


def read_ephypress(file_path, **kwargs):
    """Create an EphyPressRecordingExtractor accepted by SpikeInterface operations."""
    return EphyPressRecordingExtractor(file_path, **kwargs)


def write_recording(
    recording,
    destination,
    *,
    block_samples=60000,
    workers=4,
    prediction="temporal",
    entropy_backend="fse",
    keep_metadata=True,
):
    """Compress an unscaled int16 BaseRecording directly, without a raw intermediate.

    One segment is supported per file. Channel IDs, location, gains, offsets and
    group properties are stored in the checked index. Fully connected probe
    groups are preserved. Nonuniform timestamps and arbitrary annotations are
    not serialized by this initial format.
    """
    if recording.get_num_segments() != 1:
        raise ValueError(
            "Compress each recording segment separately; only one segment per SPC file is supported"
        )
    if np.dtype(recording.get_dtype()).kind != "i" or np.dtype(recording.get_dtype()).itemsize != 2:
        raise ValueError("Lossless Level1 requires unscaled int16 traces; float data are not quantized")
    if recording.has_time_vector(0):
        raise ValueError(
            "Explicit timestamps are not stored; use a uniformly sampled recording without a time vector"
        )
    extra = None
    if keep_metadata:
        extra = dict(
            channel_ids=recording.get_channel_ids().tolist(),
            channel_properties={},
            is_filtered=bool(recording.is_filtered()),
        )
        t_start = recording._recording_segments[0].get_times_kwargs()["t_start"]
        if t_start is not None:
            extra["t_start"] = float(t_start)
        for key in ("location", "gain_to_uV", "offset_to_uV", "group"):
            values = recording.get_property(key)
            if values is not None:
                extra["channel_properties"][key] = np.asarray(values).tolist()
        if recording.has_probe():
            group = recording.get_probegroup()
            indices = np.concatenate([probe.device_channel_indices for probe in group.probes])
            if np.array_equal(np.sort(indices[indices >= 0]), np.arange(recording.get_num_channels())):
                extra["probegroup"] = group.to_dict(array_as_list=True)
    write_blocks(
        lambda a, b: recording.get_traces(start_frame=a, end_frame=b),
        destination,
        (int(recording.get_num_samples()), int(recording.get_num_channels())),
        sampling_frequency=float(recording.get_sampling_frequency()),
        block_samples=block_samples,
        workers=workers,
        prediction=prediction,
        entropy_backend=entropy_backend,
        extra_metadata=extra,
    )
    return read_ephypress(destination)
