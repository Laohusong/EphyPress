# Third-party notices

EphyPress source is distributed under the [MIT license](LICENSE). The maintained
source tree does not vendor third-party implementations or repository snapshots.

NumPy is installed separately. SpikeInterface, ProbeInterface, SciPy, Kilosort
and PyTorch are optional, separately installed dependencies with their own
licenses. Patent experiments additionally use separately installed mtscomp and
plotting/document packages. Their source, model weights and runtime distributions
are not included in this repository.

The native codec implements temporal differencing and range asymmetric numeral
systems (rANS). Naming an algorithm does not imply redistribution of another
project's implementation. Source builds require a system C++17 toolchain;
Windows uses the static MSVC runtime, and the codec does not link OpenMP.
