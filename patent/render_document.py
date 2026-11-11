"""使用Windows Word导出PDF，并用PyMuPDF生成逐页校对图。

不改写DOCX。只读打开本任务生成的文档。Word实例独立且不显示窗口。
"""

import argparse
import json
from pathlib import Path

import pymupdf


def main():
    parser = argparse.ArgumentParser(description="导出交底书并生成校对图")
    parser.add_argument("--qa-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="默认渲染最终交底书；可指定临时校对稿")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    source = (args.source or root / "output/rebuilt/EphyPress专利技术交底书.docx").resolve()
    pdf = source.with_suffix(".pdf")
    import win32com.client

    app = win32com.client.DispatchEx("Word.Application")
    quit_word = app.Quit
    app.Visible = False
    app.DisplayAlerts = 0
    doc = None
    exported = False
    try:
        doc = app.Documents.Open(str(source), ReadOnly=True, AddToRecentFiles=False)
        doc.ExportAsFixedFormat(str(pdf), 17)
        exported = True
    finally:
        if doc is not None:
            doc.Close(False)
        try:
            quit_word()
        except Exception as error:
            # 部分Word版本在关闭最后一个文档后已退出，随后Quit会报告RPC断开。
            # 只在导出已成功且属于服务器退出错误时忽略，不掩盖导出失败。
            if not exported or getattr(error, "hresult", None) not in (-2147023170, -2147023174):
                raise
    args.qa_dir.mkdir(parents=True, exist_ok=True)
    rendered = pymupdf.open(pdf)
    pages = []
    for i, page in enumerate(rendered):
        target = args.qa_dir / f"page-{i + 1:02d}.png"
        page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(target)
        pages.append({"页": i + 1, "文字数": len(page.get_text()), "图片": str(target)})
    (args.qa_dir / "pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"PDF": str(pdf), "页数": len(rendered), "校对图目录": str(args.qa_dir)}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
