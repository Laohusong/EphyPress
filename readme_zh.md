# EphyPress

[English](README.md) | **简体中文**

当前为 **patent** 分支，除生产库外，还包含专利附图、实验证据和复现脚本。数据、配置及运行命令见[专利实验复现说明](patent/复现.md)。

EphyPress 用于电生理记录的无损压缩与按需读取。当前编码器采用独立存储块、可逆时间差分和四路 rANS 熵编码，精确保留原始 int16 ADC 采样值。Kilosort4 和 SpikeInterface 可直接读取压缩记录，无需先写出完整原始中间文件。

## 安装

```bash
python -m pip install .
# 可选：安装集成接口和开发工具
python -m pip install '.[all,dev]'
```

从源码构建需要 C++17 编译器：Windows 使用 MSVC Build Tools，Linux 使用 GCC 或 Clang，macOS 使用 Xcode Command Line Tools。NumPy 是唯一必需的 Python 运行时依赖。可选工具另行安装；仓库不附带其他项目的源码副本。

## 快速开始

```python
from ephypress import compress, open_recording, verify

compress("recording.dat", "recording.ep", n_channels=384,
         sampling_frequency=30000, block_samples=60000, workers=4)
with open_recording("recording.ep") as recording:
    samples = recording[30000:60000, :32]
verify("recording.ep", original="recording.dat")
```

```bash
ephypress compress recording.dat recording.ep --channels 384 --fs 30000
ephypress info recording.ep
ephypress verify recording.ep --original recording.dat
ephypress decompress recording.ep restored.dat
```

输入必须是无文件头、时间优先排列的小端 int16 数据。请提供实际通道数、采样率及探针几何，程序不会根据文件名推断这些信息。输出文件以原子方式创建，不覆盖已有文件。

## 文档

- [中文使用指南](docs/guide.zh-CN.md)与[英文使用指南](docs/user-guide.md)
- [SpikeInterface 集成](docs/spikeinterface.md)
- [容器与编码格式规范](docs/format.md)
- [验证说明](docs/validation.md)与[贡献指南](CONTRIBUTING.md)

`main` 分支保存维护中的生产库、示例和测试。专利附图、实验证据和复现说明集中在 [patent 分支](https://github.com/Laohusong/EphyPress/tree/patent)，详见[专利实验复现说明](https://github.com/Laohusong/EphyPress/blob/patent/patent/复现.md)。实验性能取决于记录、读取器配置、硬件及输入输出条件。

当前读取器支持正式 v3 存档。迁移 v1/v2 或实验容器时，请先使用匹配的旧版本恢复原始字节，再用当前版本重新压缩，详见[版本说明](RELEASE_NOTES.md)。

## 授权协议

EphyPress 采用 **[AGPL-3.0-only](LICENSE)＋另行签署的付费商业许可**双许可模式。

- **个人及科研用途免费**，须遵守 AGPLv3 的适用条款。
- **遵守 AGPLv3 的商业使用同样可以免费**；AGPLv3 本身不禁止商业使用。
- **需要免除 AGPLv3 义务的商业用途，须额外购买商业授权**，例如需要合同许可的闭源集成或专有分发。

商业授权由 Jiatai Song（[Laohusong](https://github.com/Laohusong)）另行提供，具体范围和费用以双方签署的合同为准，详见[商业授权说明](COMMERCIAL_LICENSE.md)。开源许可限定为第 3 版，不包含“第 3 版或任何后续版本”的选项。历史版本已经授予的 MIT 权利不因本次变更而撤销。

贡献前请阅读 [CLA（贡献者许可协议）](CLA.md)和[贡献指南](CONTRIBUTING.md)。第三方依赖保留各自许可证，见[第三方声明](THIRD_PARTY_NOTICES.md)。

## 致谢

感谢 EphyPress 所使用的 GitHub 项目的开发者与贡献者：[NumPy](https://github.com/numpy/numpy) 提供数组运算和内存映射输入；[SpikeInterface](https://github.com/SpikeInterface/spikeinterface) 提供读取器和写入器所使用的记录抽象；[ProbeInterface](https://github.com/SpikeInterface/probeinterface) 用于恢复存档中的探针几何及接线元数据；[Kilosort](https://github.com/MouseLand/Kilosort) 的公开 Kilosort4 接口支持接入本项目的按需读取器。这些项目支持了相应功能和集成，感谢其维护者的工作。
