# EphyPress 使用指南

EphyPress 对电生理 int16 采样值进行无损压缩，并为 SpikeInterface 和
Kilosort4 提供按需读取接口。当前实现采用块内一阶时间差分、通道优先残差
排列和四路 rANS 熵编码；每个存储块独立解码。

## 安装

要求 Python 3.10 以上及 C++17 编译器。Windows 使用 MSVC Build Tools，
Linux 使用 GCC/Clang，macOS 使用 Xcode Command Line Tools。

```bash
python -m pip install .
python -m pip install '.[all]'  # 可选：SpikeInterface 和 Kilosort4
```

基础依赖只有 NumPy。GPU 分选另行安装适配设备的 PyTorch/CUDA 版本。
第三方依赖通过包管理器安装，仓库不附带其他项目的源码。

## 压缩与验证

```python
from ephypress import compress, info, verify, decompress

compress("recording.dat", "recording.ep", n_channels=384,
         sampling_frequency=30000, block_samples=60000, workers=4)
print(info("recording.ep"))
print(verify("recording.ep", original="recording.dat"))
decompress("recording.ep", "restored.dat")
```

输入必须为无文件头、时间优先、小端 int16 数据。通道数和采样率需正确指定。
默认每块 60000 个时间采样点；30 kHz 下对应两秒。压缩不做量化、滤波或幅值缩放。
`workers` 控制并行压缩的块数。校验会检查所有块和完整原始字节 SHA256；
指定 `original` 后还会逐块比较采样值。文件通过临时文件原子发布，不覆盖已有目标。

```bash
ephypress compress recording.dat recording.ep --channels 384 --fs 30000
ephypress info recording.ep
ephypress verify recording.ep --original recording.dat
ephypress decompress recording.ep restored.dat
```

## 按需读取

```python
from ephypress import open_recording

with open_recording("recording.ep", cache_blocks=64, prefetch_blocks=32) as data:
    window = data[59950:60100, :32]
```

支持跨块窗口与步进切片，返回的数组只读，缓存淘汰或关闭读取器后仍有效。
默认保留 64 块并最多预取 32 块。以 60000×384×2 字节计算，缓存采样值本身
可接近 2.95 GB，另有工作区、预取和用户保留的窗口。内存有限时调小
`cache_blocks`、`prefetch_blocks`，或设置 `prefetch=False`。

使用上下文管理器及时关闭读取器。并发消费者应分别打开读取器或使用外部锁；
多进程采用 `spawn`，在子进程中创建读取器。

## 分选与 SpikeInterface

```python
from ephypress.kilosort import run_kilosort

run_kilosort("recording.ep", probe=probe,
             settings={"batch_size": 60000}, results_dir="ks4_output")
```

`probe` 必须使用真实探针几何和通道映射。通过 Kilosort4 公开的 `file_object`
接口按需获取采样值，默认不保存预处理数据副本。结果目录必须为空或尚不存在。

```python
from ephypress.spikeinterface import read_ephypress, write_recording
recording = read_ephypress("recording.ep")
traces = recording.get_traces(start_frame=0, end_frame=30000)
recording.close()
# 从单段、均匀采样的 int16 BaseRecording 写入：
compressed = write_recording(source_recording, "new_recording.ep")
compressed.close()
```

元数据与物理单位设置见 [SpikeInterface 文档](spikeinterface.md)。
当前读取器只支持正式 v3 格式。旧格式需用对应旧版本先恢复原始数据再重新压缩。
专利附图及实验复现资料集中在 `patent` 分支的 `patent/复现.md`。
