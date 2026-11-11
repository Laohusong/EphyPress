# Validation

Run the maintained suite from a built checkout:

```bash
python -m pip install '.[dev,all]'
python -m pytest -q
python -m ruff check src tests tools setup.py examples
python -m build
python -m twine check dist/*
```

Tests cover modular int16 differences, rANS distributions and tail shapes,
byte-exact golden packets, malformed streams, index checks, archive corruption,
atomic output publication, cross-block/strided windows and returned-array
ownership. Optional integration tests cover SpikeInterface serialization,
metadata and Kilosort's public input interface. Tests that require an unavailable
optional package are skipped; a skip is not evidence that integration passed.

CI runs on Windows, Linux and macOS, with a separate CPU Kilosort job. Windows
wheels are inspected by `tools/check_windows_runtime.py` to reject dependencies
on separately installed C++ or OpenMP DLLs.

For real recordings, run `ephypress verify recording.ep --original recording.dat`
to check all source bytes. Unit tests do not establish compression or sorting
performance. Patent experiment protocols, saved measurements and figure scripts
are maintained on the `patent` branch; historical measurements are explicitly
separated from new runs.
