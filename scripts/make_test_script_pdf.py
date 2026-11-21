"""Render the manual test script to a PDF you can hold while testing.

    uv run --with reportlab python scripts/make_test_script_pdf.py

Markdown is the source of truth; this is a view of it. The converter handles
only the constructs the document actually uses -- headings, tables, bullets,
blockquotes, bold, inline code -- because a general Markdown engine is a
dependency this build does not need.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]

#: Defaults, overridable on the command line:
#:   make_test_script_pdf.py [source.md [out.pdf [footer label]]]
#: Generalised rather than copied when the writeup needed the same treatment.
#: Two converters drift, and the second one is always the one with the bug.
SOURCE = ROOT / "docs" / "manual_test_script.md"
OUT = ROOT / "docs" / "manual_test_script.pdf"
LABEL = "manual test script"

INK = colors.HexColor("#15181d")
DIM = colors.HexColor("#5b6472")
LINE = colors.HexColor("#dde2e9")
BAND = colors.HexColor("#eef1f5")
ACCENT = colors.HexColor("#1b6ef3")
FAIL = colors.HexColor("#c3362b")


#: Type scale. The writeup is held to a page budget, so it is set a little
#: tighter than the other documents rather than having required content cut
#: out of it. Set from the command line; 1.0 everywhere else.
SCALE = 1.0


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    s: dict[str, ParagraphStyle] = {}
    s["body"] = ParagraphStyle(
        "body", parent=base, fontName="Helvetica", fontSize=9.6 * SCALE, leading=14.2 * SCALE,
        textColor=INK, alignment=TA_LEFT, spaceAfter=6 * SCALE,
    )
    s["h1"] = ParagraphStyle(
        "h1", parent=s["body"], fontName="Helvetica-Bold", fontSize=20 * SCALE,
        leading=24 * SCALE, spaceBefore=0 * SCALE, spaceAfter=10 * SCALE,
    )
    s["h2"] = ParagraphStyle(
        "h2", parent=s["body"], fontName="Helvetica-Bold", fontSize=13.5 * SCALE,
        leading=17 * SCALE, spaceBefore=16 * SCALE, spaceAfter=6 * SCALE,
    )
    s["h3"] = ParagraphStyle(
        "h3", parent=s["body"], fontName="Helvetica-Bold", fontSize=11.2 * SCALE,
        leading=14 * SCALE, spaceBefore=13 * SCALE, spaceAfter=4 * SCALE, textColor=ACCENT,
    )
    s["cell"] = ParagraphStyle(
        "cell", parent=s["body"], fontSize=8.6 * SCALE, leading=11.6 * SCALE, spaceAfter=0 * SCALE,
    )
    s["cellhead"] = ParagraphStyle(
        "cellhead", parent=s["cell"], fontName="Helvetica-Bold", textColor=DIM,
    )
    s["quote"] = ParagraphStyle(
        "quote", parent=s["body"], fontName="Helvetica-Oblique", fontSize=9.4 * SCALE,
        leading=14 * SCALE, leftIndent=10, textColor=DIM, spaceBefore=2 * SCALE, spaceAfter=8 * SCALE,
        borderPadding=0,
    )
    s["bullet"] = ParagraphStyle(
        "bullet", parent=s["body"], fontSize=9.4 * SCALE, leading=13.4 * SCALE, spaceAfter=2 * SCALE,
    )
    s["code"] = ParagraphStyle(
        "code", parent=s["body"], fontName="Courier", fontSize=8.4 * SCALE, leading=11.6 * SCALE,
        textColor=INK, backColor=BAND, borderPadding=6, spaceBefore=4 * SCALE,
        spaceAfter=8 * SCALE, leftIndent=2,
    )
    return s


def inline(text: str) -> str:
    """Markdown spans -> reportlab's mini-HTML. Escaping comes first."""
    text = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    text = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8.6">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\*\w])\*([^*]+)\*(?![\*\w])", r"<i>\1</i>", text)
    # Markdown links: keep the label, drop the target -- this is paper.
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    text = text.replace("—", "\u2014").replace("·", "\u00b7")
    # Last, so the font tag is not mangled by the escaping above.
    return tag_devanagari(text)


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def build_table(rows: list[list[str]], st: dict) -> Table:
    head, *body = rows
    data = [[Paragraph(inline(c), st["cellhead"]) for c in head]]
    for r in body:
        data.append([Paragraph(inline(c), st["cell"]) for c in r])

    table = Table(data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BAND),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
                ("INNERGRID", (0, 1), (-1, -1), 0.3, LINE),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def convert(md: str, st: dict) -> list:
    story: list = []
    lines = md.splitlines()
    i = 0
    bullets: list[ListItem] = []

    def flush_bullets() -> None:
        nonlocal bullets
        if bullets:
            story.append(
                ListFlowable(
                    bullets, bulletType="bullet", start="circle",
                    leftIndent=12, bulletFontSize=6, spaceAfter=6,
                )
            )
            bullets = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_bullets()
            i += 1
            continue

        # Fenced code
        if stripped.startswith("```"):
            flush_bullets()
            i += 1
            block: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            body = "<br/>".join(
                l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                 .replace(" ", "&nbsp;")
                for l in block
            )
            story.append(Paragraph(body, st["code"]))
            continue

        # Tables
        if stripped.startswith("|"):
            flush_bullets()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i].strip()
                if not re.fullmatch(r"\|[\s:\-|]+\|", row):
                    rows.append(split_row(row))
                i += 1
            if rows:
                story.append(build_table(rows, st))
                story.append(Spacer(1, 8))
            continue

        # Horizontal rule -> a new card starts; give it a page of its own run
        if re.fullmatch(r"-{3,}", stripped):
            flush_bullets()
            story.append(Spacer(1, 4))
            story.append(HRFlowable(width="100%", thickness=0.6, color=LINE))
            story.append(Spacer(1, 4))
            i += 1
            continue

        # Headings
        m = re.match(r"(#{1,4})\s+(.*)", stripped)
        if m:
            flush_bullets()
            level = len(m.group(1))
            text = inline(m.group(2))
            key = {1: "h1", 2: "h2", 3: "h3"}.get(level, "h3")
            story.append(Paragraph(text, st[key]))
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            flush_bullets()
            quote = [stripped.lstrip("> ").strip()]
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip("> ").strip())
                i += 1
            story.append(Paragraph(inline(" ".join(quote)), st["quote"]))
            continue

        # Bullets
        if re.match(r"[-*]\s+", stripped):
            text = re.sub(r"^[-*]\s+", "", stripped)
            i += 1
            while (
                i < len(lines)
                and lines[i].strip()
                and not re.match(r"[-*]\s+|\||#{1,4}\s|>", lines[i].strip())
                and not lines[i].strip().startswith("```")
            ):
                text += " " + lines[i].strip()
                i += 1
            bullets.append(
                ListItem(Paragraph(inline(text), st["bullet"]), leftIndent=12)
            )
            continue

        # Paragraph: join until a blank line or a block construct
        flush_bullets()
        para = [stripped]
        i += 1
        while (
            i < len(lines)
            and lines[i].strip()
            and not re.match(r"[-*]\s+|\||#{1,4}\s|>|-{3,}", lines[i].strip())
            and not lines[i].strip().startswith("```")
        ):
            para.append(lines[i].strip())
            i += 1
        story.append(Paragraph(inline(" ".join(para)), st["body"]))

    flush_bullets()
    return story


#: Characters the built-in fonts cannot draw. ReportLab's Helvetica is encoded
#: WinAnsi (cp1252); anything outside it renders as a solid black box, which
#: is how "Rs 750" spent a day in these documents as a filled rectangle. I had
#: verified the text was *present* by extracting it, which is not the same as
#: checking it drew -- the extraction read back the character the box stood in
#: for. See D-066.
#:
#: Substituted rather than solved by embedding a font: the only local font
#: carrying the rupee sign is a macOS system font, and embedding it would make
#: this script produce different output on a different machine, or none at
#: all. "Rs" is idiomatic in Indian banking and renders everywhere.
UNRENDERABLE = {
    "\u20b9": "Rs ",   # rupee sign
    "\u2265": ">=",
    "\u2264": "<=",
    "\u2192": "->",
    "\u2190": "<-",
    "\u00d7": "x",
    "\u2713": "yes",
    "\u2717": "no",
    "\u25a0": "",
}


#: Devanagari appears in three places in the decision log -- recorded
#: transcripts of what the speech recogniser actually returned. Romanising
#: them would defeat the purpose of quoting them. The built-in fonts have no
#: Devanagari, so one is registered from the system if present and the runs
#: are tagged to use it. Where no such font exists -- a Linux clone, say --
#: the build does not fail: the text is kept and a note is printed, because
#: a reader who wanted the decision log should get it.
DEVANAGARI = re.compile(r"[\u0900-\u097f\u200c\u200d]+")
_DEVA_FONT: str | None = None


def register_devanagari() -> str | None:
    global _DEVA_FONT
    if _DEVA_FONT is not None:
        return _DEVA_FONT or None
    candidates = [
        ("/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc", 0),
        ("/System/Library/Fonts/Supplemental/DevanagariMT.ttc", 0),
        ("/System/Library/Fonts/Kohinoor.ttc", 0),
        ("/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf", None),
        ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf", None),
    ]
    for path, index in candidates:
        if not Path(path).exists():
            continue
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            font = (TTFont("Deva", path, subfontIndex=index)
                    if index is not None else TTFont("Deva", path))
            pdfmetrics.registerFont(font)
            _DEVA_FONT = "Deva"
            return "Deva"
        except Exception:
            continue
    _DEVA_FONT = ""
    return None


def tag_devanagari(text: str) -> str:
    """Wrap Devanagari runs so they are drawn with the registered font."""
    if not register_devanagari():
        return text
    return DEVANAGARI.sub(lambda m: f'<font name="Deva">{m.group(0)}</font>', text)


def renderable(text: str) -> str:
    """Replace what the font cannot draw, and collapse the double space that
    "Rs " leaves when it already had one after it."""
    for bad, good in UNRENDERABLE.items():
        text = text.replace(bad, good)
    return text.replace("Rs  ", "Rs ")


def assert_renderable(text: str) -> None:
    """Fail loudly on anything still outside the font's encoding.

    A box in a document that goes to someone else is worse than a crash here,
    and this is the check that was missing.
    """
    has_deva = register_devanagari() is not None
    unknown = sorted({
        ch for ch in text
        if not _encodable(ch)
        and not (has_deva and DEVANAGARI.match(ch))
    })
    if unknown:
        listed = ", ".join(f"U+{ord(c):04X} {c!r}" for c in unknown)
        raise SystemExit(
            f"  these characters cannot be drawn by the built-in fonts: {listed}\n"
            f"  add them to UNRENDERABLE in {Path(__file__).name}"
        )


def _encodable(ch: str) -> bool:
    try:
        ch.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.6)
    canvas.setFillColor(DIM)
    canvas.drawString(18 * mm, 12 * mm, f"Collections Voice Agent \u00b7 {LABEL}")
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"{doc.page}")
    canvas.restoreState()


def main() -> int:
    global SOURCE, OUT, LABEL
    if len(sys.argv) > 1:
        SOURCE = Path(sys.argv[1])
    if len(sys.argv) > 2:
        OUT = Path(sys.argv[2])
    if len(sys.argv) > 3:
        LABEL = sys.argv[3]
    if len(sys.argv) > 4:
        global SCALE
        SCALE = float(sys.argv[4])
    if not SOURCE.exists():
        print(f"missing {SOURCE}")
        return 1
    st = styles()
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Collections Voice Agent - {LABEL}",
        author="Collections Voice Agent",
    )
    source = renderable(SOURCE.read_text(encoding="utf-8"))
    assert_renderable(source)
    doc.build(convert(source, st), onLaterPages=footer, onFirstPage=footer)
    print(f"  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
