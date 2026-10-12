"""Build the bundled codec with native Unix or Windows compilers."""

import os
import sys

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

FSE_SOURCES = [
    f"vendor/fse/{name}.c" for name in ("fse_compress", "fse_decompress", "entropy_common", "hist")
]


class BuildCodec(build_ext):
    def build_extensions(self):
        msvc = self.compiler.compiler_type == "msvc"
        openmp = sys.platform.startswith("linux") and os.environ.get("EPHYPRESS_OPENMP", "1") != "0"
        if msvc:
            # Allocator ownership stays within this DLL. Static CRT linking avoids
            # a separate MSVC C++/OpenMP runtime installation for wheel users.
            self.compiler.initialize()
            for name in ("compile_options", "compile_options_debug"):
                setattr(
                    self.compiler, name, [flag.replace("/MD", "/MT") for flag in getattr(self.compiler, name)]
                )
            c_flags, cpp_flags, link_flags = ["/O2", "/std:c11"], ["/O2", "/std:c++17"], []
        else:
            c_flags = ["-O3"]
            cpp_flags = ["-O3", "-std=c++17"] + (["-fopenmp"] if openmp else [])
            link_flags = ["-fopenmp"] if openmp else []
        for extension in self.extensions:
            objects = self.compiler.compile(
                FSE_SOURCES,
                output_dir=self.build_temp,
                include_dirs=extension.include_dirs,
                macros=extension.define_macros,
                extra_postargs=c_flags,
                debug=self.debug,
            )
            extension.extra_objects = objects
            extension.extra_compile_args = cpp_flags
            extension.extra_link_args = link_flags
        super().build_extensions()


setup(
    ext_modules=[
        Extension(
            "ephypress._codec",
            sources=["src/ephypress/_module.cpp", "src/ephypress/_kernel.cpp"],
            include_dirs=["src/ephypress", "vendor/fse"],
            language="c++",
            define_macros=[("Py_LIMITED_API", "0x030A0000"), ("FSE_DLL_EXPORT", "1"), ("NOMINMAX", "1")],
            depends=FSE_SOURCES + ["src/ephypress/_prediction.h"],
            py_limited_api=True,
        )
    ],
    cmdclass={"build_ext": BuildCodec},
    options={"bdist_wheel": {"py_limited_api": "cp310"}},
)
