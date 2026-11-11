"""将中文正文、原始测量和四幅附图组装为含可编辑公式的交底书。

依赖：python-docx、Pandoc。先运行 plot_figures.py，再运行本程序。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
from document_content import CAPTIONS, NAMES


def font(style, size, chinese="宋体", bold=False):
    style.font.name = "Times New Roman"
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor(0, 0, 0)
    rf = style.element.get_or_add_rPr().get_or_add_rFonts()
    for key, value in (("ascii", "Times New Roman"), ("hAnsi", "Times New Roman"), ("eastAsia", chinese)):
        rf.set(qn("w:" + key), value)


def reference_document():
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin, sec.bottom_margin = Cm(2.2), Cm(2.0)
    sec.left_margin, sec.right_margin = Cm(2.3), Cm(2.3)
    sec.header_distance, sec.footer_distance = Cm(0.9), Cm(0.9)
    normal = doc.styles["Normal"]
    font(normal, 11.5)
    pf = normal.paragraph_format
    pf.line_spacing = 1.35
    pf.space_after = Pt(6)
    pf.first_line_indent = Cm(0.81)
    pf.widow_control = True
    for name, size in (("Title", 20), ("Heading 1", 15), ("Heading 2", 12.5)):
        st = doc.styles[name]
        font(st, size, "黑体", True)
        st.paragraph_format.first_line_indent = Cm(0)
        st.paragraph_format.space_before = Pt(13 if name != "Title" else 0)
        st.paragraph_format.space_after = Pt(7)
        st.paragraph_format.keep_with_next = True
    # 清除基础模板自带的主题色标题下划线。
    for border in list(doc.styles.element.xpath(".//w:pBdr")):
        border.getparent().remove(border)
    font(doc.styles["Caption"], 10.5, "宋体", False)
    doc.styles["Caption"].paragraph_format.first_line_indent = Cm(0)
    doc.styles["Caption"].paragraph_format.space_after = Pt(7)
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.paragraph_format.first_line_indent = Cm(0)
    footer.add_run("第 ")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    footer._p.append(fld)
    footer.add_run(" 页")
    for run in footer.runs:
        run.font.size = Pt(9)
    doc.core_properties.title = "一种电生理数据无损压缩及按需读取方法"
    doc.core_properties.subject = "计算机类发明技术交底书"
    doc.core_properties.author = ""
    doc.core_properties.keywords = "电生理；无损压缩；差分；rANS；按需解码；峰电位分选"
    return doc


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT / "rebuilt")
    args = parser.parse_args()
    text = (ROOT / "交底书正文.txt").read_text(encoding="utf-8")
    equations = re.findall(r"\$\$\s*(.*?)\s*\$\$", text, flags=re.S)
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError("请先安装Pandoc，以生成可编辑公式")
    with tempfile.TemporaryDirectory(prefix="ephypress-patent-formulas-") as tmp:
        source, target = Path(tmp) / "公式.txt", Path(tmp) / "公式.docx"
        source.write_text("\n\n".join("$$\n" + e + "\n$$" for e in equations), encoding="utf-8")
        subprocess.run(
            [pandoc, "--from", "markdown", "--to", "docx", str(source), "-o", str(target)], check=True
        )
        formulas = [deepcopy(p._p) for p in Document(target).paragraphs if p._p.xpath(".//m:oMath")]
    assert len(formulas) == len(equations)
    doc = reference_document()
    plain, eqi = [], 0
    for block in text.strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("# "):
            p = doc.add_paragraph(block[2:], "Title")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(14)
        elif block.startswith("### "):
            doc.add_paragraph(block[4:], "Heading 2")
        elif block.startswith("## "):
            p = doc.add_paragraph(block[3:], "Heading 1")
            if block[3:] == "参考资料":
                p.paragraph_format.page_break_before = True
        elif block.startswith("$$"):
            element = formulas[eqi]
            eqi += 1
            doc._body._body.insert(len(doc._body._body) - 1, element)
            ppr = element.find(qn("w:pPr"))
            if ppr is None:
                ppr = OxmlElement("w:pPr")
                element.insert(0, ppr)
            spacing = OxmlElement("w:spacing")
            spacing.set(qn("w:before"), "80")
            spacing.set(qn("w:after"), "100")
            ppr.append(spacing)
            ind = OxmlElement("w:ind")
            ind.set(qn("w:firstLine"), "0")
            ppr.append(ind)
        elif re.fullmatch(r"【图[1-4]】", block):
            number = int(block[2])
            stem, title = NAMES[number]
            p = doc.add_paragraph(f"图{number} {title}", "Heading 2")
            p.paragraph_format.page_break_before = number != 1
            path = ROOT / "figures" / (stem + ".png")
            assert path.is_file(), path
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Cm(0)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.keep_with_next = True
            p.add_run().add_picture(str(path), width=Cm(16.4))
            p = doc.add_paragraph(CAPTIONS[number], "Caption")
            p.paragraph_format.line_spacing = 1.3
            block = f"图{number} {title}\n{CAPTIONS[number]}"
        else:
            p = doc.add_paragraph(block)
            if block.endswith("："):
                p.paragraph_format.keep_with_next = True
            if block.startswith("["):
                p.paragraph_format.first_line_indent = Cm(0)
                p.paragraph_format.line_spacing = 1.2
                for run in p.runs:
                    run.font.size = Pt(10)
        plain.append(block)
    destination = args.output
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "EphyPress专利技术交底书.docx"
    doc.save(target)
    (destination / "EphyPress专利技术交底书.txt").write_text("\n\n".join(plain) + "\n", encoding="utf-8")
    assert not re.search(r"【(?:图|编解码|无损|KS4)", "\n".join(plain))
    print(
        json.dumps(
            {
                "文档": str(target),
                "公式数": eqi,
                "表格数": len(doc.tables),
                "附图数": len(doc.inline_shapes),
                "内部稿": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
