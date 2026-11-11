"""Build the original EphyPress C++ codec without vendored source dependencies."""

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


class BuildCodec(build_ext):
    def build_extensions(self):
        msvc = self.compiler.compiler_type == "msvc"
        if msvc:
            self.compiler.initialize()
            for name in ("compile_options", "compile_options_debug"):
                setattr(
                    self.compiler, name, [flag.replace("/MD", "/MT") for flag in getattr(self.compiler, name)]
                )
        for extension in self.extensions:
            extension.extra_compile_args = ["/O2", "/std:c++17"] if msvc else ["-O3", "-std=c++17"]
        super().build_extensions()


setup(
    ext_modules=[
        Extension(
            "ephypress._codec",
            sources=["src/ephypress/_module.cpp", "src/ephypress/_kernel.cpp", "src/ephypress/_rans.cpp"],
            language="c++",
            define_macros=[("Py_LIMITED_API", "0x030A0000"), ("NOMINMAX", "1")],
            py_limited_api=True,
        )
    ],
    cmdclass={"build_ext": BuildCodec},
    options={"bdist_wheel": {"py_limited_api": "cp310"}},
)
