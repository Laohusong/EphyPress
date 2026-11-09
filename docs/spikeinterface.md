# SpikeInterface

[README](../README.md) · [User guide](user-guide.md)

Install the `spikeinterface` extra; use the `all` extra for KS4 through SpikeInterface. See [installation](user-guide.md#installation-on-linux-macos-and-native-windows).

EphyPress supplies a serializable `BaseRecording` extractor. It works with
SpikeInterface's trace access, channel/time slicing, preprocessing, analyzers
and sorter interfaces; registration into upstream `spikeinterface.extractors`
is not required.

```python
from ephypress.spikeinterface import read_ephypress

recording = read_ephypress("recording.ep")
traces = recording.get_traces(start_frame=0, end_frame=30000)
subset = recording.select_channels(recording.get_channel_ids()[:32])
recording.dump_to_json("recording.json")

# Works in a new process after EphyPress is installed there:
from spikeinterface.core import load
reloaded = load("recording.json")
reloaded.close()
```

The JSON references the archive path; it does not embed traces. Keep the archive
accessible and update/recreate that reference if you move it.

## Geometry and physical units

Files compressed from raw binary contain ADC values, file channel count and
sample rate. Supply the actual geometry and calibration before using operations
that require them:

```python
recording.set_channel_locations(channel_positions_um)  # shape (n_channels, 2 or 3)
recording.set_channel_gains(gain_to_uV)                   # device-specific, per channel or scalar
recording.set_channel_offsets(offset_to_uV)
traces_uV = recording.get_traces(start_frame=0, end_frame=30000, return_in_uV=True)
```

Alternatively attach a real ProbeInterface probe with `recording.set_probe(probe)`.
Device channel indices must correspond to the archive's column order. Remove a
sync channel with `select_channels` before attaching a probe containing only
electrode contacts. No gain or geometry is invented from a channel count.

## Compress an existing SpikeInterface recording

```python
from ephypress.spikeinterface import write_recording

# source_recording can be any uniformly sampled, one-segment int16 BaseRecording
compressed = write_recording(source_recording, "recording.ep", workers=4)
compressed.close()
```

The writer streams unscaled blocks directly; it does not write a full binary
intermediate. It stores channel IDs, positions, gains, offsets, groups, the
constant time origin, filtered annotation, and fully connected probe metadata
in the checked archive index. Arbitrary annotations and explicit timestamp
vectors are not stored. Explicit time vectors and multi-segment inputs are
rejected; write each segment to its own file. `keep_metadata=False` omits optional
metadata. Float recordings are rejected so no hidden lossy conversion occurs.

For multiprocessing, install EphyPress in each worker environment and use the
`spawn` start method. The extractor opens a private decoder lazily in each
process; do not fork a process with an active prefetch reader.

## Run KS4 through SpikeInterface without a raw copy

```python
import spikeinterface.sorters as ss
from ephypress.spikeinterface import read_ephypress

recording = read_ephypress("recording.ep")
recording.set_channel_locations(channel_positions_um)
sorting = ss.run_sorter(
    "kilosort4", recording, folder="ks4_si_output",
    use_binary_file=False, save_preprocessed_copy=False,
    torch_device="cuda", verbose=True,
)
recording.close()
```

`use_binary_file=False` forces SpikeInterface's array wrapper rather than a
binary export. `save_preprocessed_copy=False` avoids the optional processed
data copy. Probe/calibration metadata embedded by `write_recording` can be reused.
See the [SpikeInterface documentation](https://spikeinterface.readthedocs.io/en/stable/)
for quality metrics, analyzers and additional sorter settings.

