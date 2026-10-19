"""Render the demo corpus (data/demo/source/*.md) into text-based PDFs.

The sources use a deliberately small markup:

    ---               front matter (id, title, author, subject)
    # Heading         document title
    ## / ###          section headings
    - item            bullet list item
    <<<PAGEBREAK>>>   explicit page break

Page breaks are explicit so that page numbers are stable: the evaluation dataset
pins evidence to specific pages, and this script fails if any page overflows
onto an extra page.

Output is deterministic (reportlab "invariant" mode), so re-running the script
produces byte-identical PDFs and the same SHA-256 hashes.

Usage (from the repository root):
    backend/.venv/Scripts/python scripts/build_demo_pdfs.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader
from reportlab import rl_config
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer

rl_config.invariant = 1  # fixed timestamps and document IDs -> reproducible bytes

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "demo" / "source"
OUT_DIR = ROOT / "data" / "demo"
PAGEBREAK = "<<<PAGEBREAK>>>"


def parse_source(text: str) -> tuple[dict[str, str], list[str]]:
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not match:
        raise ValueError("missing front matter")
    meta = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    pages = [p.strip() for p in match.group(2).split(PAGEBREAK)]
    return meta, pages


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body", parent=base["BodyText"], fontName="Helvetica", fontSize=10.5, leading=14.2, spaceAfter=6, alignment=TA_LEFT
    )
    return {
        "title": ParagraphStyle("T", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=4, alignment=TA_LEFT),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13.5, leading=17, spaceBefore=8, spaceAfter=5),
        "h3": ParagraphStyle("H3", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=11.5, leading=15, spaceBefore=6, spaceAfter=3),
        "body": body,
        "bullet": ParagraphStyle("Bullet", parent=body, spaceAfter=2),
    }


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def page_flowables(page: str, styles: dict[str, ParagraphStyle]) -> list:
    flowables: list = []
    bullets: list[str] = []

    def flush_bullets() -> None:
        if bullets:
            items = [ListItem(Paragraph(escape(b), styles["bullet"]), leftIndent=12) for b in bullets]
            flowables.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=12, bulletFontSize=9))
            flowables.append(Spacer(1, 4))
            bullets.clear()

    for block in re.split(r"\n\s*\n", page):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        if all(line.startswith("- ") for line in lines):
            bullets.extend(line[2:].strip() for line in lines)
            continue
        flush_bullets()
        if block.startswith("### "):
            flowables.append(Paragraph(escape(block[4:]), styles["h3"]))
        elif block.startswith("## "):
            flowables.append(Paragraph(escape(block[3:]), styles["h2"]))
        elif block.startswith("# "):
            flowables.append(Paragraph(escape(block[2:]), styles["title"]))
        else:
            flowables.append(Paragraph(escape(" ".join(lines)), styles["body"]))
    flush_bullets()
    return flowables


def render(source: Path) -> dict:
    meta, pages = parse_source(source.read_text(encoding="utf-8"))
    out = OUT_DIR / f"{source.stem}.pdf"
    styles = build_styles()

    def footer(canvas, doc) -> None:  # noqa: ANN001 - reportlab callback signature
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(20 * mm, 12 * mm, "DocuMind demo corpus")
        canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title=meta["title"],
        author=meta.get("author", ""),
        subject=meta.get("subject", ""),
        creator="DocuMind build_demo_pdfs.py",
    )
    story: list = []
    for i, page in enumerate(pages):
        if i:
            story.append(PageBreak())
        story.extend(page_flowables(page, styles))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)

    page_count = len(PdfReader(str(out)).pages)
    if page_count != len(pages):
        raise SystemExit(f"{out.name}: expected {len(pages)} pages but rendered {page_count}; a page overflowed")

    data = out.read_bytes()
    return {
        "id": meta["id"],
        "filename": out.name,
        "title": meta["title"],
        "description": meta.get("subject", ""),
        "pages": page_count,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> int:
    sources = sorted(SOURCE_DIR.glob("*.md"))
    if not sources:
        print(f"no sources in {SOURCE_DIR}", file=sys.stderr)
        return 1
    documents = [render(s) for s in sources]
    manifest = {
        "description": "Original sample documents written for the DocuMind demo. Northwind Analytics and ExamplePay are fictional.",
        "license": "Same license as this repository (MIT).",
        "documents": documents,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for d in documents:
        print(f"{d['filename']:45s} {d['pages']} pages  {d['size_bytes']:>7d} bytes  {d['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
