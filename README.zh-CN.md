# EphyPress 中文用户指南

[English](README.md) · [发行版本](https://github.com/Laohusong/EphyPress/releases) · [文件格式](docs/format.md) · [验证记录](docs/validation.md)

EphyPress 将电生理 `int16` 原始记录无损压缩为一个带索引的 `.spc` 文件。
它支持完整还原、按需读取任意时间窗口，以及让 KS4 和 SpikeInterface 直接读取压缩后的采样值。
读取器只在内存中保存有界的解码缓存，不自动生成完整原始数据副本。

默认使用 **temporal（时间预测）**，可选 **spatiotemporal（时间与跨通道预测）**。
两者都采用可逆整数预测、Zigzag、四个低位直接打包、逐通道 FSE 和极高位 Zstd，完整保留每个 int16 ADC 值。文件头记录预测方式与明确的系数，不再使用实验编号。FSE 随包分发。

## 1. Linux、macOS、原生 Windows 安装

三种桌面系统均默认支持相同的压缩、解压、窗口读取、SpikeInterface 和 KS4 接口。
使用 64 位 CPython 3.10+。Windows 直接使用原生 Python，在 PowerShell 或命令提示符运行即可；无需 Linux 子系统。
默认读取器自动选择适合系统的实现：Linux 可用 RAM 页映射，Windows/macOS 使用线程安全的块读取。并行压缩块和预取在三种系统都可用。

在 [GitHub Release](https://github.com/Laohusong/EphyPress/releases/tag/v0.2.0) 下载与操作系统及架构匹配的 wheel：

```bash
python -m pip install /path/to/ephypress-0.2.0-...whl
```

提供 Linux、macOS、Windows 的 x86_64/ARM64 包。Windows wheel 静态链接 C++ 运行库，不需要用户另装编译器运行库。
Windows ARM64 请使用原生 ARM64 Python 3.11+ 和 ARM64 wheel；其他架构使用对应的 64 位 Python。

源码安装需要原生编译器：Linux 的 GCC/Clang 与 Python 开发头文件、macOS 的 Xcode Command Line Tools、Windows 的 Microsoft Visual C++ Build Tools（C++ 工作负载）。

```bash
python -m pip install "ephypress @ git+https://github.com/Laohusong/EphyPress.git@v0.2.0"
python -m pip install "ephypress[spikeinterface] @ git+https://github.com/Laohusong/EphyPress.git@v0.2.0"
python -m pip install "ephypress[ks4] @ git+https://github.com/Laohusong/EphyPress.git@v0.2.0"
python -m pip install "ephypress[all] @ git+https://github.com/Laohusong/EphyPress.git@v0.2.0"
```

KS4 的 GPU 排序还需要适合显卡的 PyTorch/CUDA 环境和实际探针配置；见 [KS4 指南](https://github.com/MouseLand/Kilosort#instructions) 和 [PyTorch 安装页面](https://pytorch.org/get-started/locally/)。本版本从 GitHub 分发。

### 新文件格式

0.2 版本使用 EphyPress v1 文件格式，预测器名称直接表达算法含义。旧格式不再读取，请从原始 int16 数据重新压缩。扩展名仍为 `.spc`。

## 2. 原始数据要求

命令行输入必须是**无文件头、小端、有符号 int16、时间 × 通道顺序**：

```text
时间0通道0、时间0通道1、……、时间1通道0、时间1通道1、……
```

必须提供文件真实列数和采样率。含同步列的 385 列文件应填 `--channels 385`，即使排序只用 384 个电极通道。
文件字节数应能被 `2 × 通道数` 整除。浮点、24 位、其他端序或带文件头的数据，应先用对应的 SpikeInterface extractor 读取；本包不会把浮点采样静默量化为整数。

## 3. 压缩、校验与解压

```bash
ephypress compress continuous.dat recording.spc --channels 384 --fs 30000 --workers 4
ephypress info recording.spc
ephypress verify recording.spc --original continuous.dat
ephypress decompress recording.spc restored.dat
```

也可使用 `python -m ephypress`。输出是 JSON，失败时退出码非零。目标文件必须不存在，写入成功后才原子发布；失败会清理临时文件。

`info` 只读取并核对索引。`verify` 解码全部采样并核对原始 SHA-256；提供 `--original` 时还逐值比较原文件。`decompress` 在发布还原文件前完成完整 SHA-256 核对。这些操作保留块 CRC 和索引校验。

Python 接口：

```python
import ephypress as ep

report = ep.compress("continuous.dat", "recording.spc", n_channels=384,
                     sampling_frequency=30000, workers=4)
print(report["ratio"])  # 原始字节数 / 完整压缩文件字节数
ep.verify("recording.spc", original="continuous.dat")
ep.decompress("recording.spc", "restored.dat")
```

默认压缩块为 60000 点，不必与后续 sorting 的 batch 大小相同。
默认 `prediction="temporal"`。使用时间与跨通道预测时，传入 `prediction="spatiotemporal"` 或 `--prediction spatiotemporal`。两种模式均不存储重复 halo。
高位全部使用 Zstd 时用 `entropy_backend="zstd"` 或 `--entropy zstd`，仍完全无损。

## 4. 不展开整个文件，直接读取窗口

```python
with ep.open_recording("recording.spc") as recording:
    print(recording.shape, recording.dtype, recording.metadata["sampling_frequency"])
    traces = recording[100000:160000, :]
    selected = recording[100000:160000, [0, 2, 7]]
    batch = recording.read_batch(100000, 65536, halo=(2000, 2000), pad="edge")
    print(batch.shape)  # (69536, 通道数)
    print(recording.statistics())
```

默认 `reader_mode="auto"` 在 Linux 上选页映射，其余平台用块拼接；`reader_mode="blocks"` 可显式选择普通读取器。
默认缓存两帧、最多预取四帧，并在 Linux 上复用四个空闲背板。`prefetch=False` 关闭预取；`prefetch_blocks` 可为 1、2、4、8。
返回数组只读，在后续读取或关闭后仍保持原值。调用者长期保留很多数组时，这部分内存不属于内部缓存预算。
用 `with` 或 `close()` 释放读取器资源；多个并发消费者应各开读取器或自行加锁。

## 5. 用原生 KS4 直接排序压缩文件

便利接口自动读取文件中的采样率和通道数：

```python
from kilosort.io import load_probe
import ephypress as ep

result = ep.run_kilosort(
    "recording.spc", probe=load_probe("ProbeA.json"),
    results_dir="ks4_output", settings={"batch_size": 60000},
    torch_thread_lim=8,
)
```

使用实际探针几何和通道映射，输出目录须为新目录或空目录。其余 KS4 参数会原样传递；返回值就是 KS4 原始结果元组。
如果显式设置的 `fs` 或 `n_chan_bin` 与文件冲突，接口会报错。

也可直接调用 KS4 的原有接口：

```python
from kilosort import run_kilosort
from kilosort.io import load_probe

with ep.open_recording("recording.spc") as recording:
    result = run_kilosort(
        settings={"n_chan_bin": recording.shape[1], "fs": recording.metadata["sampling_frequency"]},
        probe=load_probe("ProbeA.json"), filename="recording.spc",
        file_object=recording, data_dtype="int16", results_dir="ks4_output",
        save_preprocessed_copy=False,
    )
```

关键是 `file_object=recording`；仅把 `.spc` 路径交给 KS4 不会自动选择解码器。
无需修改安装的 KS4 源码，但 KS4 GUI 不会自动识别 `.spc`。时间子集沿用 KS4 的 `tmin`、`tmax` 参数。

## 6. 用 SpikeInterface 读取

```python
from ephypress.spikeinterface import read_ephypress

recording = read_ephypress("recording.spc")
traces = recording.get_traces(start_frame=0, end_frame=30000)
subset = recording.select_channels(recording.get_channel_ids()[:32])
recording.dump_to_json("recording.json")

from spikeinterface.core import load
reloaded = load("recording.json")
reloaded.close()
```

它是标准 `BaseRecording`，可用于 SI 的切片、预处理、SortingAnalyzer 和 sorter 接口。入口由 EphyPress 提供，不要求修改或注册到上游 `spikeinterface.extractors`。
JSON 保存压缩文件路径，不嵌入原始采样；新进程需安装 EphyPress，并能访问同一文件。移动文件后请更新或重新生成路径引用。

### 探针和微伏单位

原始二进制本身没有探针或增益信息，请按设备元数据补齐：

```python
recording.set_channel_locations(channel_positions_um)  # (通道数, 2或3)
recording.set_channel_gains(gain_to_uV)
recording.set_channel_offsets(offset_to_uV)
traces_uV = recording.get_traces(start_frame=0, end_frame=30000, return_in_uV=True)
```

也可通过 `set_probe(probe)` 附加 ProbeInterface 探针，device channel indices 要匹配压缩文件列顺序。
若文件含同步列而探针只有电极接触点，先 `select_channels` 排除同步列。

### 直接压缩已有 SI Recording

```python
from ephypress.spikeinterface import write_recording

compressed = write_recording(source_recording, "recording.spc", workers=4)
compressed.close()
```

输入须为单 segment、均匀采样的 int16 recording。写入按块进行，不生成完整 raw 中间文件。
通道 ID、位置、增益、偏移、分组、常数时间起点、滤波标记和完整连接的探针会保存在校验索引中。
任意自定义注释不保存；显式时间向量和多 segment 会报错。多 segment 请分别压缩，或按 SI 的明确语义处理后再写。
`keep_metadata=False` 可只保存采样及基础信息。浮点 recording 不会被隐式转换为有损 int16。

多进程工作使用 `spawn`，每个进程通过序列化描述重新加载私有读取器；不要继承已经启动预取的活动读取器。

### 通过 SpikeInterface 直接运行 KS4

```python
import spikeinterface.sorters as ss
from ephypress.spikeinterface import read_ephypress

recording = read_ephypress("recording.spc")
recording.set_channel_locations(channel_positions_um)
sorting = ss.run_sorter(
    "kilosort4", recording, folder="ks4_si_output",
    use_binary_file=False, save_preprocessed_copy=False,
    torch_device="cuda", verbose=True,
)
recording.close()
```

`use_binary_file=False` 强制走 SI 数组读取接口，`save_preprocessed_copy=False` 关闭额外预处理副本。
若用 `write_recording` 保存了探针/位置，可直接复用这些信息。

## 7. Phy 波形查看

本包不安装 Phy 的 `.spc` 解码器。需要查看 raw 波形时，显式解压到 `restored.dat`，并在 KS4 输出的 `params.py` 中把 `dat_path` 改为其绝对路径；dtype、采样率和**完整文件列数**须正确。
也可设置 `save_preprocessed_copy=True` 让 KS4 导出预处理数据，但会生成额外文件。

## 8. 验证、性能和开发

压缩率依赖信号，吞吐依赖硬件及读取配置。已验证无损、损坏检测、跨块窗口、两种具名预测、数组生命周期、CLI、SI 元数据重载和 KS4 padding；还对真实 60 秒记录完成了原生 KS4 与 SI KS4 的完整运行。具体版本、范围和限制见 [验证记录](docs/validation.md)。

`workers` 只控制并行压缩块，Linux OpenMP 内核每阶段还可使用两个线程；预取线程与 Torch/BLAS 线程分别配置。构建时设置 `EPHYPRESS_OPENMP=0` 可生成单线程原生内核。

```bash
git clone https://github.com/Laohusong/EphyPress.git
cd EphyPress
python -m pip install -e '.[dev,spikeinterface]'
pytest
python -m build
python -m twine check dist/*
```

GitHub CI 自动构建和测试；版本标签构建 Linux/macOS/Windows wheel 与源码包。
`tools/validate_real_recording.py` 可用用户自己的真实数据进行 GPU 验证，数据和结果保留在本地。
主体代码 MIT 许可，FSE 为 BSD-2-Clause；详见 [第三方声明](THIRD_PARTY_NOTICES.md)。
