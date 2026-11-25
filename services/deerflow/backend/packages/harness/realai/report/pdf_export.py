"""Export report Markdown to PDF (Chinese-capable via system fonts)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\msyh.ttf"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
    Path(r"C:\Windows\Fonts\SIMSUN.TTC"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
]


def _find_cjk_font() -> Path | None:
    for p in _FONT_CANDIDATES:
        if p.is_file():
            return p
    return None


def markdown_to_pdf(markdown: str, *, title: str = "RealAi Report") -> bytes:
    """Convert simple Markdown to PDF bytes. Raises RuntimeError if fonts unavailable."""
    try:
        from fpdf import FPDF
    except ImportError as e:
        raise RuntimeError("未安装 fpdf2，无法导出 PDF。请在后端环境安装 fpdf2。") from e

    font_path = _find_cjk_font()
    if not font_path:
        raise RuntimeError("未找到可用中文字体（如微软雅黑），无法导出 PDF。")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    family = "RealAiCJK"
    try:
        pdf.add_font(family, fname=str(font_path))
    except Exception:
        # Some TTC need explicit style registration
        pdf.add_font(family, style="", fname=str(font_path))
    pdf.set_font(family, size=16)
    pdf.multi_cell(0, 10, title)
    pdf.ln(4)
    pdf.set_font(family, size=11)

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            pdf.ln(4)
            continue
        text = _strip_md(line)
        if line.startswith("# "):
            pdf.set_font(family, size=15)
            pdf.multi_cell(0, 9, text[2:].strip() if text.startswith("#") else text)
            pdf.set_font(family, size=11)
            pdf.ln(2)
        elif line.startswith("## "):
            pdf.set_font(family, size=13)
            pdf.multi_cell(0, 8, re.sub(r"^##\s*", "", text))
            pdf.set_font(family, size=11)
            pdf.ln(1)
        elif line.startswith("### "):
            pdf.set_font(family, size=12)
            pdf.multi_cell(0, 7, re.sub(r"^###\s*", "", text))
            pdf.set_font(family, size=11)
        else:
            pdf.multi_cell(0, 6.5, text)
    out = pdf.output()
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    return bytes(out)


def _strip_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text
