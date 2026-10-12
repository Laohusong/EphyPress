# EphyPress 中文用户指南

[English](README.md) · [发行版本](https://github.com/Laohusong/EphyPress/releases) · [文件格式](docs/format.md) · [验证记录](docs/validation.md)

EphyPress 将电生理 `int16` 原始记录无损压缩为一个带索引的 `.spc` 文件。
它支持完整还原、按需读取任意时间窗口，以及让 KS4 和 SpikeInterface 直接读取压缩后的采样值。
读取器只在内存中保存有界的解码缓存，不自动生成完整原始数据副本。

默认配方为当前 **Level1 p53 / q1 / k4 / FSE / group1 / halo0**：可逆整数时间预测、Zigzag、低位打包、逐通道 FSE，以及极高位 Zstd。所有 ADC 采样值完整保留。
旧版 p41 配方和无损 SPC1/SPC3 文件仍可读取；有损 Level2/Level3 不属于本包。
包内自带 FSE 源码，安装好的 wheel 不需要特殊系统 libzstd，也无需第一次读取时再编译。

## 1. 安装与依赖

需要 CPython 3.10 或更高版本。Linux 支持 OpenMP 和 RAM 页映射；macOS 使用普通块拼接和单线程原生内核。Windows 当前请使用 WSL2/Linux。

从 GitHub 标签安装会编译原生组件，需要 C/C++ 编译器和 Python 开发头文件。Ubuntu/Debian：

```bash
sudo apt-get install build-essential python3-dev
python -m pip install --upgrade pip
python -m pip install "ephypress @ git+https://github.com/Laohusong/EphyPress.git@v0.1.0"
```

macOS 先执行 `xcode-select --install`。也可以在 GitHub Releases 下载与系统、架构匹配的 wheel，执行：

```bash
python -m pip install /path/to/downloaded.whl
```

基础运行依赖为 NumPy 和 zstandard。可选接口分别安装：

```bash
python -m pip install "ephypress[spikeinterface] @ git+https://github.com/Laohusong/EphyPress.git@v0.1.0"
python -m pip install "ephypress[ks4] @ git+https://github.com/Laohusong/EphyPress.git@v0.1.0"
# 两者都需要时
python -m pip install "ephypress[all] @ git+https://github.com/Laohusong/EphyPress.git@v0.1.0"
```

KS4 还需要适合显卡的 PyTorch/CUDA 环境，按 [KS4 官方说明](https://github.com/MouseLand/Kilosort#instructions) 和 [PyTorch 安装页面](https://pytorch.org/get-started/locally/)配置。
本初始版本从 GitHub 分发，以上命令不假定已发布到 PyPI。

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
旧配方用 `profile="legacy"` 或 `--profile legacy`，对应 p41 和 halo61。
高位全部使用 Zstd 时用 `entropy_backend="zstd"` 或 `--entropy zstd`，仍完全无损。

## 4. 不展开整个文件，直接读取窗口

```python
with ep.open_recording("recording.spc") as recording:
    print(recording.shape, recording.dtype, recording.metadata["fs"])
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
        settings={"n_chan_bin": recording.shape[1], "fs": recording.metadata["fs"]},
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

压缩率依赖信号，吞吐依赖硬件及读取配置。已验证无损、损坏检测、跨块窗口、旧配方、数组生命周期、CLI、SI 元数据重载和 KS4 padding；还对真实 60 秒记录完成了原生 KS4 与 SI KS4 的完整运行。具体版本、范围和限制见 [验证记录](docs/validation.md)。

`workers` 只控制并行压缩块，Linux OpenMP 内核每阶段还可使用两个线程；预取线程与 Torch/BLAS 线程分别配置。构建时设置 `EPHYPRESS_OPENMP=0` 可生成单线程原生内核。

```bash
git clone https://github.com/Laohusong/EphyPress.git
cd EphyPress
python -m pip install -e '.[dev,spikeinterface]'
pytest
python -m build
python -m twine check dist/*
```

GitHub CI 自动构建和测试；版本标签构建 Linux/macOS wheel 与源码包。
`tools/validate_real_recording.py` 可用用户自己的真实数据进行 GPU 验证，数据和结果保留在本地。
主体代码 MIT 许可，FSE 为 BSD-2-Clause；详见 [第三方声明](THIRD_PARTY_NOTICES.md)。
