# Contributing

Use a dedicated environment with a C++17 compiler. Install `pip install -e
'.[dev,spikeinterface]'`, run `pytest` and `ruff check src tests tools setup.py`.
Install a CPU PyTorch build followed by `.[ks4]` to run KS4's padded batch test.
GPU sorting tests require your own recording and probe geometry:

```bash
python tools/validate_real_recording.py --raw continuous.dat --probe ProbeA.json \
  --channels 384 --output artifacts/my_validation --duration 60
```

The tool compresses the supplied file, checks all values, and launches fresh
processes for raw/native KS4, compressed/native KS4 and compressed/SI KS4.
It never uploads data. Use a new output directory. Compression covers the entire
supplied file; `--duration` limits sorting only.

Preserve predictor IDs, floor/wrap arithmetic, SPC framing and retained-array
lifetimes. Tests should cover consumer windows spanning storage boundaries and
both FSE/Zstd. New format changes need versioning and compatibility fixtures.
Keep runtime dependencies minimal; optional integrations belong in extras.
Do not commit real recordings, machine credentials or large sorting outputs.

## Release checklist

1. Update the version in pyproject, `__init__`, CLI, CITATION and CHANGELOG.
2. Run tests, build an sdist and wheel, and run `twine check dist/*`.
3. Install the wheel in a fresh environment outside the source checkout.
4. Push the reviewed commit and let CI pass.
5. Tag `vX.Y.Z` and push it. The release workflow builds and tests repaired ABI3
   wheels, builds an sdist and publishes assets to GitHub Releases.

PyPI publishing is not configured; adding it requires an explicit publisher
account and trusted-publishing setup. Bug reports should include package/runtime
versions, archive metadata and a synthetic reproducer rather than private data.
