# Contributing

Use a dedicated branch and install an editable development build:

```bash
python -m pip install -e '.[dev,all]'
python -m pytest -q
python -m ruff check src tests tools setup.py examples
```

Rebuild the extension after C++ changes. Keep the public API, format specification
and tests consistent. Changes to entropy coding must retain the golden-packet
checks or explicitly introduce a new format version. Include meaningful tests
for lossless reconstruction, malformed input and buffer ownership when changing
those behaviors. Never silently overwrite an existing output file.

The main branch contains production code only. Keep patent plotting, performance
experiment scripts and their evidence on the patent branch. Install third-party
libraries through their packages; do not copy their source trees into this repo.
Do not commit raw recordings, build products, virtual environments or machine-local
configuration. Document experiment data hashes and settings separately from code.
