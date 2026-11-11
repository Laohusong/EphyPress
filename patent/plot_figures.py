#!/usr/bin/env python
"""生成 EphyPress 专利交底书的四幅中文学术图。

在仓库根目录运行：python patent/plot_figures.py
可用 --figures 1 2 4 仅生成选定图；--font 可指定中文字体文件。
数据均通过本脚本所在目录定位，不依赖当前工作目录。
中文沿用原交底书的微软雅黑，拉丁字母及数字使用Arial，所有图仅用黑白。
每幅图同时导出 400 dpi PNG、嵌入字体的矢量 PDF 和文字转路径的 SVG。
图3采用30分钟Neuropixels记录；图4比较原始、本发明方法与mtscomp输入。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
from matplotlib.ticker import MaxNLocator, ScalarFormatter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "figures"
INK = "#000000"
PAPER = "#FFFFFF"
CJK_FAMILY = "Microsoft YaHei"


def configure(font_path: str | None) -> None:
    """匹配原始AI附图中的微软雅黑系列与Arial字体，所有输出统一样式。"""
    candidates = (
        [Path(font_path)]
        if font_path
        else [
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ]
    )
    selected = next((p for p in candidates if p.is_file()), None)
    if selected is None:
        raise FileNotFoundError("未找到中文字体，请用 --font 指定字体文件。")
    fm.fontManager.addfont(str(selected))
    family = fm.FontProperties(fname=str(selected)).get_name()
    global CJK_FAMILY
    CJK_FAMILY = family
    # 显式注册常规、粗体和斜体；中文由后备家族提供，避免数学公式混入衬线字体。
    for filename in ("msyhbd.ttc", "arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
        path = Path("C:/Windows/Fonts") / filename
        if path.is_file():
            fm.fontManager.addfont(str(path))
    plt.rcParams.update(
        {
            "font.family": ["Arial", family],
            "font.size": 11,
            "axes.titlesize": 12.5,
            "axes.labelsize": 11.5,
            "axes.unicode_minus": False,
            "axes.linewidth": 0.9,
            "axes.edgecolor": INK,
            "axes.facecolor": PAPER,
            "hatch.color": INK,
            "hatch.linewidth": 0.65,
            "text.color": INK,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "legend.fontsize": 10.5,
            "mathtext.fontset": "custom",
            "mathtext.rm": "Arial",
            "mathtext.it": "Arial:italic",
            "mathtext.bf": "Arial:bold",
            "mathtext.bfit": "Arial:bold:italic",
            "mathtext.sf": "Arial",
            "mathtext.tt": "Arial",
            "mathtext.cal": "Arial",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "path",
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
        }
    )


def save(fig: plt.Figure, basename: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        metadata = {"Creator": "EphyPress 专利交底书绘图程序"} if ext == "pdf" else None
        fig.savefig(
            OUT / f"{basename}.{ext}", dpi=400, bbox_inches="tight", pad_inches=0.12, metadata=metadata
        )
    plt.close(fig)
    print(f"已生成：{basename}（PNG、PDF、SVG）")


def canvas(ax, xlim=(0, 10), ylim=(0, 8)):
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.axis("off")


def box(ax, x, y, w, h, label, *, color=PAPER, fontsize=11.5, edge=INK, weight="normal", fontfamily=None):
    patch = FancyBboxPatch(
        (x - w / 2, y - h / 2),
        w,
        h,
        boxstyle="round,pad=0.025,rounding_size=0.08",
        linewidth=1.15,
        edgecolor=edge,
        facecolor=color,
    )
    ax.add_patch(patch)
    extra = {"fontfamily": fontfamily} if fontfamily else {}
    ax.text(
        x, y, label, ha="center", va="center", fontsize=fontsize, linespacing=1.45, fontweight=weight, **extra
    )
    return patch


def arrow(ax, start, end, *, color=INK, style="-", rad=0.0, lw=1.25):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=lw,
        color=color,
        linestyle=style,
        connectionstyle=f"arc3,rad={rad}",
    )
    ax.add_patch(patch)
    return patch


def figure1() -> None:
    """图1：v3差分/rANS编码与按需解码，明确残差恢复和融合重建的边界。"""
    fig, ax = plt.subplots(figsize=(8.5, 7.0))
    fig.subplots_adjust(left=0.02, right=0.98, top=0.98, bottom=0.02)
    canvas(ax, (0, 12), (0, 10))
    ax.text(
        6,
        9.65,
        "多通道电生理数据的差分压缩与按需读取",
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
    )
    xs, ys, w, h = [1.5, 4.5, 7.5, 10.5], [8.15, 5.25, 2.35], 2.48, 1.45
    rows = [
        [
            "多通道原始采样\n时间优先矩阵",
            "独立时间分块\n每块独立初始化",
            "逐通道可逆差分\n16位模减法",
            "通道连续布局\n同一通道残差相邻",
        ],
        [
            "之字形映射\n直接符号／逃逸值",
            "块内单一概率模型\n四路 rANS 编码",
            "压缩块及索引存储\n偏移、采样范围、校验",
            "按请求查找索引\n并行预取相关块",
        ],
        [
            "rANS 与逃逸恢复\n完整残差缓冲区",
            "融合逆差分与转置\n重建时间优先采样",
            "解码块缓存与窗口裁剪\n跨块拼接所需批次",
            "KS4 峰电位分选\n接收无损采样批次",
        ],
    ]
    for row_index, (y, labels) in enumerate(zip(ys, rows)):
        positions = xs if row_index != 1 else xs[::-1]
        for x, label in zip(positions, labels):
            box(ax, x, y, w, h, label, fontsize=10.7)
        for start, end in zip(positions[:-1], positions[1:]):
            direction = 1 if end > start else -1
            arrow(ax, (start + direction * (w / 2 + 0.02), y), (end - direction * (w / 2 + 0.02), y))
    arrow(ax, (xs[-1], ys[0] - h / 2 - 0.02), (xs[-1], ys[1] + h / 2 + 0.02))
    arrow(ax, (xs[0], ys[1] - h / 2 - 0.02), (xs[0], ys[2] + h / 2 + 0.02))
    ax.text(10.18, 6.7, "编码", fontsize=10.5, ha="right")
    ax.text(1.82, 3.8, "按需解码", fontsize=10.5, ha="left")
    ax.text(7.3, 3.8, "仅逆差分与转置融合；熵解码先产生残差缓冲区。", fontsize=9.6, ha="center")
    ax.text(6, 0.73, "独立存储块不重复保存上下文；读取窗口与存储块边界相互独立。", ha="center", fontsize=10.5)
    ax.text(
        6, 0.25, "按需读取避免预先生成完整解压副本；所有原始整数采样值精确还原。", ha="center", fontsize=10.2
    )
    save(fig, "figure_01_overview")


def panel(ax, title):
    canvas(ax, (0, 10), (0, 10))
    ax.add_patch(Rectangle((0.05, 0.05), 9.9, 9.9, facecolor="white", edgecolor=INK, linewidth=0.8))
    ax.text(0.38, 9.47, title, ha="left", va="center", fontsize=12.3, fontweight="bold")


def figure2() -> None:
    """图2：差分、符号/逃逸、单模型四状态及融合重建的当前实现。"""
    fig, axs = plt.subplots(2, 2, figsize=(8.6, 8.2))
    fig.subplots_adjust(left=0.02, right=0.98, top=0.97, bottom=0.03, wspace=0.07, hspace=0.09)
    ax = axs[0, 0]
    panel(ax, "(a) 可逆差分与通道连续布局")
    ax.text(5, 8.3, r"$d_{0,c}=x_{0,c}$", ha="center", fontsize=12)
    ax.text(5, 7.25, r"$d_{t,c}=W_{16}(x_{t,c}-x_{t-1,c})\quad(t>0)$", ha="center", fontsize=10.8)
    box(ax, 2.45, 4.95, 3.55, 2.5, "时间优先采样\n逐行排列各通道\n时间 × 通道", fontsize=10.3)
    box(ax, 7.55, 4.95, 3.55, 2.5, "通道优先残差\n每通道时间连续\n通道 × 时间", fontsize=10.3)
    arrow(ax, (4.28, 4.95), (5.72, 4.95))
    ax.text(5, 2.85, r"线性位置：$i=cR+t$", ha="center", fontsize=10.8, fontfamily=CJK_FAMILY)
    ax.text(
        5, 1.75, "$R$为本块实际采样数；块首以自身为残差。", ha="center", fontsize=9.7, fontfamily=CJK_FAMILY
    )
    ax.text(
        5,
        0.66,
        "$W_{16}$表示16位模运算；不采用跨通道预测。",
        ha="center",
        fontsize=9.7,
        fontfamily=CJK_FAMILY,
    )

    ax = axs[0, 1]
    panel(ax, "(b) 之字形映射与逃逸符号")
    ax.text(5, 8.28, r"$d\geq0:\ u=2d$", ha="center", fontsize=12)
    ax.text(5, 7.25, r"$d<0:\ u=-2d-1$", ha="center", fontsize=12)
    box(ax, 5, 5.85, 4.25, 1.0, "按映射值选择符号", fontsize=11)
    arrow(ax, (3.55, 5.32), (2.5, 4.55))
    arrow(ax, (6.45, 5.32), (7.5, 4.55))
    box(
        ax,
        2.5,
        3.3,
        4.2,
        2.4,
        "$0\\leq u<1024$\n直接符号 $s=u$\n无附加逃逸数据",
        fontsize=10.3,
        fontfamily=CJK_FAMILY,
    )
    box(
        ax,
        7.5,
        3.3,
        4.2,
        2.4,
        "$u\\geq1024$\n逃逸符号 $s=1024$\n另存残差 $d$ 的16位比特",
        fontsize=9.8,
        fontfamily=CJK_FAMILY,
    )
    ax.text(5, 1.25, "逃逸值保存原始残差比特，而非映射值。", ha="center", fontsize=10)
    ax.text(5, 0.48, "直接符号与逃逸路径共同覆盖全部16位残差。", ha="center", fontsize=9.7)

    ax = axs[1, 0]
    panel(ax, "(c) 单一概率模型与四路 rANS")
    box(
        ax,
        5,
        7.6,
        8.55,
        1.5,
        "整块共用1025项频率表\n归一化频率之和为 $2^{14}$",
        fontsize=10.5,
        fontfamily=CJK_FAMILY,
    )
    for state, x in enumerate([1.3, 3.76, 6.22, 8.68]):
        arrow(ax, (x, 6.82), (x, 5.85), lw=1.0)
        box(
            ax,
            x,
            4.95,
            2.05,
            1.75,
            f"状态 $v_{state}$\n$i={state},{state + 4},\\ldots$",
            fontsize=10,
            fontfamily=CJK_FAMILY,
        )
    ax.text(
        5,
        3.38,
        r"线性位置 $i$ 使用状态 $i\ \mathrm{mod}\ 4$。",
        ha="center",
        fontsize=10.6,
        fontfamily=CJK_FAMILY,
    )
    ax.text(5, 2.34, "四状态交错；每轮解码4个符号。", ha="center", fontsize=10.5)
    ax.text(5, 1.3, "共享字节重归一化流及独立逃逸值流。", ha="center", fontsize=10)
    ax.text(5, 0.42, "校验终态，并核对两数据流恰好消费完毕。", ha="center", fontsize=9.6)

    ax = axs[1, 1]
    panel(ax, "(d) 残差恢复与融合重建")
    box(ax, 5, 7.65, 8.55, 1.5, "rANS 解码、逆映射及逃逸值恢复\n写入完整的通道优先残差缓冲区", fontsize=10.2)
    arrow(ax, (5, 6.87), (5, 6.05))
    box(ax, 5, 5.2, 8.55, 1.6, "分块融合逆差分与矩阵转置\n复用工作缓冲区，写入时间优先输出", fontsize=10.2)
    ax.text(5, 3.77, r"$\widehat x_{0,c}=d_{0,c}$", ha="center", fontsize=11.4)
    ax.text(
        5,
        2.84,
        r"$\widehat x_{t,c}=W_{16}(d_{t,c}+\widehat x_{t-1,c})\quad(t>0)$",
        ha="center",
        fontsize=10.4,
    )
    box(ax, 5, 1.4, 8.55, 1.1, "时间优先采样 → 窗口裁剪、拼接与缓存", fontsize=10.3)
    ax.text(5, 0.37, "融合范围仅为逆差分与转置，仍保留残差缓冲区。", ha="center", fontsize=9.4)
    save(fig, "figure_02_prediction_and_coding")


def clean_axes(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(direction="out", length=4, width=0.8)
    ax.set_axisbelow(True)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_color(INK)


def figure3(data_path: Path) -> None:
    """30分钟Neuropixels：倍率与三个吞吐指标分别共享坐标。"""
    data = json.loads(data_path.read_text(encoding="utf-8"))
    threads = {r["profile"]: r for r in data["rows"] if r["dataset"] == "neuropixels"}
    processes = {r["profile"]: r for r in data["process_rows"] if r["dataset"] == "neuropixels"}
    fig, axes = plt.subplots(1, 2, figsize=(8, 4.9), gridspec_kw={"width_ratios": [1, 2.5]})
    fig.subplots_adjust(left=0.09, right=0.98, top=0.79, bottom=0.30, wspace=0.45)
    for j, profile in enumerate(["delta_ans0", "mtscomp"]):
        row, proc = threads[profile], processes[profile]
        assert len(row["decode_runs_s"]) == len(proc["decode_runs_s"]) == 5
        offset = -0.19 if j == 0 else 0.19
        style = dict(width=0.33, facecolor=PAPER, edgecolor=INK, linewidth=1.1, hatch="///" if j == 0 else "")
        axes[0].bar(offset, row["ratio"], **style)
        axes[0].annotate(
            f"{row['ratio']:.3f}",
            (offset, row["ratio"]),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            fontsize=10,
        )
        measurements = [
            [row["raw_bytes"] / row["encode_seconds"] / 1e6],
            [row["raw_bytes"] / v / 1e6 for v in row["decode_runs_s"]],
            [proc["raw_bytes"] / v / 1e6 for v in proc["decode_runs_s"]],
        ]
        for k, values in enumerate(measurements):
            pos = k + offset
            axes[1].bar(pos, np.median(values), **style)
            if k:
                axes[1].scatter(
                    pos + np.linspace(-0.10, 0.10, len(values)),
                    values,
                    s=17,
                    facecolors=PAPER,
                    edgecolors=INK,
                    linewidths=0.7,
                    zorder=4,
                )
            axes[1].annotate(
                f"{np.median(values):.0f}",
                (pos, max(values)),
                xytext=(0, 7),
                textcoords="offset points",
                ha="center",
                fontsize=10,
            )
    axes[0].set_xticks([0], ["压缩倍率"])
    axes[0].set_xlim(-0.65, 0.65)
    axes[0].set_ylim(0, 3.5)
    axes[0].set_ylabel("原始大小／压缩大小")
    axes[0].set_title("(a) 压缩倍率", pad=14)
    axes[1].set_xticks(range(3), ["编码", "8线程解码", "8进程解码"])
    axes[1].set_ylim(0, 3400)
    axes[1].set_xlim(-0.65, 2.65)
    axes[1].set_ylabel("吞吐（兆字节／秒）")
    axes[1].set_title("(b) 不同指标的编解码吞吐", pad=14)
    for ax in axes:
        clean_axes(ax)
        ax.tick_params(labelsize=10)
    handles = [Rectangle((0, 0), 1, 1, facecolor=PAPER, edgecolor=INK, hatch=h) for h in ["///", ""]]
    fig.legend(
        handles,
        ["本发明方法", "mtscomp"],
        loc="upper center",
        bbox_to_anchor=(0.53, 0.98),
        ncol=2,
        frameon=False,
    )
    fig.text(
        0.5,
        0.19,
        "同一段30分钟 Neuropixels 数据；编码单次，解码五次，柱为中位数，点为单次。",
        ha="center",
        fontsize=9.5,
    )
    fig.text(
        0.5, 0.12, "两种方法使用相同8个物理核和2秒块；吞吐按原始采样字节数计算。", ha="center", fontsize=9.5
    )
    fig.text(
        0.5,
        0.05,
        (
            "本发明方法采用正式 v3 实现；8进程不含输出汇合，非冷盘测量。"
            if data.get("implementation") == "cleaned_production_v3"
            else "本发明方法采用相同块码流的实验原型；8进程不含输出汇合，非冷盘测量。"
        ),
        ha="center",
        fontsize=9.5,
    )
    save(fig, "figure_03_codec_comparison")


def figure4(data_path: Path, supplement: Path) -> None:
    """图4：KS4输入读取限速实验；不合并其他限速口径及其他分选器。"""
    if data_path.suffix.lower() == ".json":
        completion_path = data_path.with_name("completion.json")
        with completion_path.open(encoding="utf-8") as handle:
            completion = json.load(handle)
        if completion.get("status") != "complete" or completion.get("runs") != 6:
            raise ValueError("新版KS4的六次完整分选尚未全部完成，不能生成最终图。")
        with data_path.open(encoding="utf-8") as handle:
            original = json.load(handle)
        rows = [
            {
                **row,
                "rate": row["bandwidth_MB_s"],
                "kind": "compressed" if row["kind"] == "rans" else row["kind"],
            }
            for row in original
        ]
    else:
        with data_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    complete = json.loads((supplement / "completion.json").read_text(encoding="utf-8"))
    assert complete["status"] == "complete" and complete["runs"] == 3
    mts = json.loads((supplement / "results.json").read_text(encoding="utf-8"))
    assert len(mts) == 3 and all(r["status"] == "success" for r in mts)
    rows += [{**r, "rate": r["bandwidth_MB_s"]} for r in mts]
    records = [
        row
        for row in rows
        if row.get("sorter", "ks4").lower() == "ks4"
        and row.get("condition", "input_read_only") == "input_read_only"
    ]
    values = {}
    expected = None
    for kind in ("raw", "compressed", "mtscomp"):
        selected = [row for row in records if row["kind"] == kind]
        rates = {float(row["rate"]): float(row["seconds"]) / 60 for row in selected}
        if len(rates) != len(selected) or len(rates) < 2:
            raise ValueError(f"KS4 {kind} 至少需要2个不同带宽的单次完整实测点。")
        if any(rate <= 0 or seconds <= 0 for rate, seconds in rates.items()):
            raise ValueError("带宽与耗时必须为正数。")
        if expected is None:
            expected = sorted(rates)
        elif sorted(rates) != expected:
            raise ValueError("原始输入和压缩输入的带宽集合不一致。")
        values[kind] = np.array([rates[rate] for rate in expected])
    fig, ax = plt.subplots(figsize=(8.0, 5.2))
    fig.subplots_adjust(left=0.115, right=0.97, top=0.87, bottom=0.28)
    ax.plot(
        expected,
        values["raw"],
        "o-",
        color=INK,
        linewidth=1.8,
        markersize=6,
        markerfacecolor="white",
        markeredgewidth=1.5,
        label="原始数据输入",
    )
    ax.plot(
        expected,
        values["compressed"],
        "s--",
        color=INK,
        linewidth=1.8,
        markersize=5.7,
        markerfacecolor=INK,
        markeredgewidth=1.5,
        label="本发明方法",
    )
    ax.plot(
        expected,
        values["mtscomp"],
        "^:",
        color=INK,
        linewidth=1.8,
        markersize=6,
        markerfacecolor=PAPER,
        markeredgewidth=1.3,
        label="mtscomp",
    )
    ax.set_xscale("log")
    ax.set_xticks(expected)
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.minorticks_off()
    ax.set_xlim(expected[0] * 0.85, expected[-1] * 1.18)
    maximum = max(max(series) for series in values.values())
    ax.set_ylim(0, np.ceil(maximum * 1.12 / 10) * 10)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, steps=[1, 2, 5, 10], integer=True))
    ax.set_xlabel("输入读取带宽上限（兆字节／秒，对数坐标）", labelpad=10)
    ax.set_ylabel("KS4 完整分选耗时（分钟）", labelpad=10)
    ax.set_title("不同读取带宽下的 KS4 完整分选耗时", fontsize=14, pad=14)
    ax.legend(loc="upper right", frameon=False, handlelength=2.8)
    clean_axes(ax)
    fig.text(
        0.5,
        0.11,
        "同一段30分钟 Neuropixels 数据与相同分选配置；三种输入，每点一次完整运行。",
        ha="center",
        fontsize=10.1,
    )
    fig.text(
        0.5,
        0.058,
        "应用层逻辑字节限速：操作系统缓存命中仍计费，解码缓存命中不计费。",
        ha="center",
        fontsize=9.2,
        color=INK,
    )
    fig.text(0.5, 0.015, "不等同于实体机械硬盘测量；折线仅连接实测点。", ha="center", fontsize=9.2, color=INK)
    save(fig, "figure_04_ks4_bandwidth")


def main() -> None:
    global OUT
    parser = argparse.ArgumentParser(description="生成专利交底书的全中文学术图")
    parser.add_argument(
        "--figures",
        type=int,
        nargs="+",
        choices=[1, 2, 3, 4],
        default=[1, 2, 3, 4],
        help="需要生成的图号，默认为全部",
    )
    parser.add_argument("--font", help="中文字体文件路径，默认微软雅黑")
    parser.add_argument(
        "--codec-data",
        type=Path,
        default=HERE / "data" / "codec_comparison.json",
        help="图3压缩对比的实测JSON文件",
    )
    parser.add_argument(
        "--timings",
        type=Path,
        default=HERE / "data" / "ks4_v03" / "results.json",
        help="图4新版分选实测JSON或CSV文件",
    )
    parser.add_argument("--mtscomp-timings", type=Path, default=HERE / "data/ks4_mtscomp")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    OUT = args.output
    configure(args.font)
    functions = {
        1: figure1,
        2: figure2,
        3: lambda: figure3(args.codec_data),
        4: lambda: figure4(args.timings, args.mtscomp_timings),
    }
    for number in dict.fromkeys(args.figures):
        functions[number]()


if __name__ == "__main__":
    main()
