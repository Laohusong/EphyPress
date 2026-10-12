"""Build the native kernel and vendored FSE; never compile on first import."""

import os
import sys
from pathlib import Path

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

ROOT = Path(__file__).parent


class BuildCodec(build_ext):
    def build_extensions(self):
        if sys.platform == "win32":
            raise RuntimeError("EphyPress currently supports Linux and macOS. Use Linux/WSL2 on Windows.")
        openmp = sys.platform.startswith("linux") and os.environ.get("EPHYPRESS_OPENMP", "1") != "0"
        for extension in self.extensions:
            extension.extra_compile_args = ["-O3"] + (["-fopenmp"] if openmp else [])
            extension.extra_link_args = ["-fopenmp"] if openmp else []
        # Mixed C/C++ extension: apply the language standard only to C++ files.
        original = self.compiler._compile

        def compile_object(obj, src, ext, cc_args, extra_postargs, pp_opts):
            flags = list(extra_postargs)
            if ext in (".cpp", ".cc", ".cxx"):
                flags.append("-std=c++17")
            return original(obj, src, ext, cc_args, flags, pp_opts)

        self.compiler._compile = compile_object
        try:
            super().build_extensions()
        finally:
            self.compiler._compile = original


setup(
    ext_modules=[
        Extension(
            "ephypress._codec",
            sources=[
                "src/ephypress/_module.cpp",
                "src/ephypress/_kernel.cpp",
                "vendor/fse/fse_compress.c",
                "vendor/fse/fse_decompress.c",
                "vendor/fse/entropy_common.c",
                "vendor/fse/hist.c",
            ],
            include_dirs=["src/ephypress", "vendor/fse"],
            language="c++",
            define_macros=[("Py_LIMITED_API", "0x030A0000"), ("FSE_DLL_EXPORT", "1")],
            py_limited_api=True,
        )
    ],
    cmdclass={"build_ext": BuildCodec},
    options={"bdist_wheel": {"py_limited_api": "cp310"}},
)
