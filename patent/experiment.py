"""专利实验公共工具；只调用已安装依赖，不包含第三方源码。"""

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def read_config(path):
    path = Path(path).resolve()
    config = load(path)
    for key in ("raw", "archive", "mtscomp", "probe", "output"):
        value = Path(config[key])
        config[key] = str((path.parent / value).resolve()) if not value.is_absolute() else str(value)
    return config


def configure(cpus, numeric_threads):
    import psutil

    process = psutil.Process()
    process.cpu_affinity(cpus)
    if sorted(process.cpu_affinity()) != sorted(cpus):
        raise RuntimeError("无法设置要求的 CPU 亲和性")
    for name in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMBA_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[name] = str(numeric_threads)


def environment(config):
    import psutil

    import ephypress

    packages = {}
    for name in ("ephypress", "mtscomp", "numpy", "torch", "kilosort", "psutil", "threadpoolctl"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    source = Path(ephypress.__file__).parent
    return dict(
        python=sys.version,
        platform=platform.platform(),
        packages=packages,
        config=config,
        cpu_affinity=psutil.Process().cpu_affinity(),
        available_memory=psutil.virtual_memory().available,
        source_sha256={
            p.name: sha256(p) for p in source.iterdir() if p.suffix in {".py", ".cpp", ".pyd", ".so"}
        },
        experiment_sha256={p.name: sha256(p) for p in Path(__file__).parent.glob("*.py")},
    )


def mts_options(threads):
    # Explicit values prevent ~/.mtscomp from silently changing the experiment.
    return dict(
        algorithm="zlib",
        cache_size=10,
        check_after_compress=False,
        check_after_decompress=False,
        chunk_duration=2.0,
        chunk_order="F",
        comp_level=-1,
        do_spatial_diff=False,
        do_time_diff=True,
        n_threads=threads,
        quiet=True,
    )


def warm(paths):
    started, count = time.perf_counter(), 0
    for path in paths:
        with open(path, "rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024**2), b""):
                count += len(block)
    return dict(seconds=time.perf_counter() - started, bytes=count)


class Budget:
    """全部输入线程共享的无突发额度字节交付预算。"""

    def __init__(self, rate):
        self.rate = rate * 1e6
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.next = time.perf_counter()
        self.bytes = self.calls = 0

    def reserve(self, size):
        with self.lock:
            self.bytes += size
            self.calls += 1
            self.next = max(self.next, time.perf_counter()) + (size / self.rate if self.rate else 0)
            return self.next

    @staticmethod
    def deliver(deadline):
        remaining = deadline - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)

    def metrics(self):
        with self.lock:
            return dict(bytes=self.bytes, calls=self.calls)


class MeteredFile:
    def __init__(self, stream, budget):
        self.stream, self.budget = stream, budget

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def read(self, size):
        if size < 0:
            raise ValueError("必须按明确的压缩块长度读取")
        deadline = self.budget.reserve(size)
        data = self.stream.read(size)
        if len(data) != size:
            raise OSError("压缩块读取不完整")
        self.budget.deliver(deadline)
        return data

    def readinto(self, buffer):
        deadline = self.budget.reserve(len(buffer))
        size = self.stream.readinto(buffer)
        if size != len(buffer):
            raise OSError("压缩块读取不完整")
        self.budget.deliver(deadline)
        return size


class RawArray:
    """按连续请求范围收费，再实施通道/步进选择。"""

    def __init__(self, path, shape, budget):
        import numpy as np

        self.path, self.shape, self.budget = path, tuple(shape), budget
        self.dtype, self.ndim, self.size = np.dtype("<i2"), 2, shape[0] * shape[1]

    def __len__(self):
        return self.shape[0]

    def __getitem__(self, key):
        import numpy as np

        rows, cols = key if isinstance(key, tuple) else (key, slice(None))
        scalar = isinstance(rows, (int, np.integer))
        if scalar:
            lo = int(rows) % len(self) if -len(self) <= int(rows) < len(self) else -1
            if lo < 0:
                raise IndexError(rows)
            hi, step = lo + 1, 1
        else:
            lo, hi, step = rows.indices(len(self))
            if step <= 0:
                raise ValueError("实验原始读取器仅支持正步进")
        hi = max(lo, hi)
        size = (hi - lo) * self.shape[1] * 2
        deadline = self.budget.reserve(size)
        with open(self.path, "rb", buffering=0) as stream:
            stream.seek(lo * self.shape[1] * 2)
            data = stream.read(size)
        if len(data) != size:
            raise OSError("原始输入读取不完整")
        self.budget.deliver(deadline)
        array = np.frombuffer(data, dtype=self.dtype).reshape(hi - lo, self.shape[1])[::step]
        return array[0, cols] if scalar else array[:, cols]

    def close(self):
        pass


@contextmanager
def sorting_reader(config, kind, budget):
    """只在实验进程中安装限速钩子，退出时恢复；不改生产源码。"""
    reader = None
    if kind == "rans":
        from ephypress import open_recording
        from ephypress._io import PositionedFile
        from ephypress._rans import Decoder

        original_init, original_read = Decoder.__init__, PositionedFile.read_at

        def initialize(self, path):
            original_init(self, path)
            self.stream = MeteredFile(self.stream, budget)

        def read_at(self, size, offset):
            deadline = budget.reserve(size)
            data = original_read(self, size, offset)
            budget.deliver(deadline)
            return data

        Decoder.__init__, PositionedFile.read_at = initialize, read_at
        try:
            reader = open_recording(
                config["archive"],
                cache_blocks=config["cache_blocks"],
                prefetch_blocks=config["prefetch_blocks"],
            )
            yield reader
        finally:
            if reader is not None:
                reader.close()
            Decoder.__init__, PositionedFile.read_at = original_init, original_read
    else:
        try:
            if kind == "raw":
                reader = RawArray(config["raw"], (config["samples"], config["channels"]), budget)
            else:
                import mtscomp

                reader = mtscomp.Reader(**mts_options(config["numeric_threads"]))
                reader.open(config["mtscomp"], Path(config["mtscomp"]).with_suffix(".ch"))
                reader.cdata = MeteredFile(reader.cdata, budget)
            yield reader
        finally:
            if reader is not None:
                reader.close()
