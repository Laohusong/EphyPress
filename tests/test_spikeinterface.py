import subprocess
import sys

import numpy as np
import pytest

si = pytest.importorskip("spikeinterface")
from spikeinterface.core import NumpyRecording, load

from ephypress import verify
from ephypress.spikeinterface import write_recording


def test_lazy_scaled_channels_serialization_and_probe_metadata(tmp_path):
    from probeinterface import Probe

    data = np.random.default_rng(71).integers(-1000, 1000, (6501, 4), dtype=np.int16)
    source = NumpyRecording(data, 20000, t_starts=[4.2], channel_ids=["a", "b", "c", "d"])
    probe = Probe(ndim=2)
    probe.set_contacts(
        np.array([[0, 0], [0, 20], [20, 0], [20, 20]]), shapes="circle", shape_params={"radius": 5}
    )
    probe.set_device_channel_indices(np.arange(4))
    source.set_probe(probe, in_place=True)
    source.set_channel_gains([1.0, 2.0, 3.0, 4.0])
    source.set_channel_offsets([0.0, 1.0, 2.0, 3.0])
    archive = tmp_path / "test.spc"
    recording = write_recording(source, archive, block_samples=2048, workers=2)
    assert recording._recording_segments[0]._reader is None
    assert recording.get_channel_ids().tolist() == source.get_channel_ids().tolist()
    assert np.array_equal(recording.get_channel_locations(), source.get_channel_locations())
    assert recording.get_times()[0] == source.get_times()[0]
    assert np.array_equal(
        recording.get_traces(start_frame=2000, end_frame=6100, channel_ids=["d", "a"]),
        data[2000:6100, [3, 0]],
    )
    assert np.array_equal(
        recording.get_traces(start_frame=1, end_frame=100, return_in_uV=True),
        source.get_traces(start_frame=1, end_frame=100, return_in_uV=True),
    )
    description = recording.to_dict()
    loaded = load(description)
    assert np.array_equal(loaded.get_traces(start_frame=4000, end_frame=5000), data[4000:5000])
    dumped = tmp_path / "recording.json"
    recording.dump_to_json(dumped)
    code = (
        "import sys; from spikeinterface.core import load; "
        "r=load(sys.argv[1]); d=r.get_traces(start_frame=2000,end_frame=6100); "
        "print(d.shape); assert d.shape==(4100,4); r.close()"
    )
    subprocess.run([sys.executable, "-c", code, str(dumped)], check=True, capture_output=True)
    loaded.close()
    recording.close()
    assert verify(archive)["exact_equal"]


def test_streaming_writer_refuses_float_and_multiple_segments(tmp_path):
    with pytest.raises(ValueError, match="int16"):
        write_recording(NumpyRecording(np.zeros((100, 2), dtype="f4"), 30000), tmp_path / "float.spc")
    with pytest.raises(ValueError, match="segment"):
        write_recording(NumpyRecording([np.zeros((100, 2), dtype="i2")] * 2, 30000), tmp_path / "multi.spc")
