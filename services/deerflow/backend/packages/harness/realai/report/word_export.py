"""Export report Markdown to Word (.docx)."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document


def markdown_to_docx(markdown: str, *, title: str = "RealAi Report") -> bytes:
    doc = Document()
    doc.add_heading(title, level=0)
    for line in markdown.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("# "):
            doc.add_heading(text[2:].strip(), level=1)
        elif text.startswith("## "):
            doc.add_heading(text[3:].strip(), level=2)
        elif text.startswith("### "):
            doc.add_heading(text[4:].strip(), level=3)
        elif text.startswith("**") and text.endswith("**"):
            p = doc.add_paragraph()
            p.add_run(text.strip("*")).bold = True
        else:
            doc.add_paragraph(_strip_md(text))
    from io import BytesIO

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _strip_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text
