# Third-party notices

EphyPress's original Python and C++ code is distributed under the MIT license.
The Level1 core was extracted from the author's SpikeCompressor research
implementation; source fingerprints are recorded in `docs/provenance.json`.

## FiniteStateEntropy

- Upstream: https://github.com/Cyan4973/FiniteStateEntropy
- Pinned commit: `9f30e0918f87bd835fa040d922a208d7b219e50b`
- Copyright: Yann Collet; component headers also credit Facebook, Inc.
- Selected license: BSD-2-Clause. Upstream's alternative GPL option is not selected.
- Original license: `vendor/fse/LICENSE`; file hashes: `vendor/fse/UPSTREAM.json`.

The necessary upstream C/header files are included unchanged. Source and binary
distributions include the BSD license and copyright notices.

## GNU OpenMP runtime

Linux wheels repaired by auditwheel can include `libgomp`. This library is
copyright the Free Software Foundation and distributed under GPLv3 with the
GCC Runtime Library Exception 3.1. License/exception texts are included under
`LICENSES/`. This runtime exception permits eligible compiled applications to
retain their own licenses. macOS/serial builds do not link libgomp.

NumPy, zstandard, SpikeInterface, Kilosort and PyTorch are separately installed
dependencies with their own licenses. EphyPress does not redistribute their
Python source or model weights.
