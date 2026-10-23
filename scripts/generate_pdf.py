from __future__ import annotations

import html
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "docs" / "项目总结.md"
OUTPUT = PROJECT_ROOT / "VoiceBoard项目总结.pdf"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")
FONT_NAME = "VoiceBoardChinese"
ACCENT = colors.HexColor("#0F766E")
DARK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#475569")
SURFACE = colors.HexColor("#F1F5F9")


def register_fonts() -> None:
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"缺少中文字体：{FONT_PATH}")
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
    pdfmetrics.registerFontFamily(
        FONT_NAME,
        normal=FONT_NAME,
        bold=FONT_NAME,
        italic=FONT_NAME,
        boldItalic=FONT_NAME,
    )


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "VoiceBoardTitle",
            parent=base["Title"],
            fontName=FONT_NAME,
            fontSize=30,
            leading=38,
            textColor=DARK,
            alignment=TA_CENTER,
            spaceAfter=12 * mm,
        ),
        "subtitle": ParagraphStyle(
            "VoiceBoardSubtitle",
            parent=base["Heading2"],
            fontName=FONT_NAME,
            fontSize=16,
            leading=24,
            textColor=ACCENT,
            alignment=TA_CENTER,
            spaceAfter=8 * mm,
        ),
        "h1": ParagraphStyle(
            "VoiceBoardH1",
            parent=base["Heading1"],
            fontName=FONT_NAME,
            fontSize=20,
            leading=28,
            textColor=ACCENT,
            spaceBefore=4 * mm,
            spaceAfter=5 * mm,
        ),
        "h2": ParagraphStyle(
            "VoiceBoardH2",
            parent=base["Heading2"],
            fontName=FONT_NAME,
            fontSize=14,
            leading=21,
            textColor=DARK,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "VoiceBoardBody",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=10.5,
            leading=18,
            textColor=DARK,
            wordWrap="CJK",
            alignment=TA_LEFT,
            spaceAfter=2.5 * mm,
        ),
        "bullet": ParagraphStyle(
            "VoiceBoardBullet",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=10.5,
            leading=17,
            leftIndent=6 * mm,
            firstLineIndent=-4 * mm,
            textColor=DARK,
            wordWrap="CJK",
            spaceAfter=1.5 * mm,
        ),
        "quote": ParagraphStyle(
            "VoiceBoardQuote",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=12,
            leading=21,
            leftIndent=8 * mm,
            rightIndent=8 * mm,
            borderColor=ACCENT,
            borderWidth=2,
            borderPadding=8,
            backColor=SURFACE,
            textColor=DARK,
            wordWrap="CJK",
            spaceBefore=4 * mm,
            spaceAfter=6 * mm,
        ),
        "code": ParagraphStyle(
            "VoiceBoardCode",
            parent=base["Code"],
            fontName=FONT_NAME,
            fontSize=9.5,
            leading=16,
            leftIndent=5 * mm,
            rightIndent=5 * mm,
            borderColor=colors.HexColor("#CBD5E1"),
            borderWidth=0.6,
            borderPadding=7,
            backColor=colors.HexColor("#F8FAFC"),
            textColor=DARK,
            wordWrap="CJK",
            spaceBefore=2 * mm,
            spaceAfter=5 * mm,
        ),
    }


def markdown_story(markdown: str, styles: dict[str, ParagraphStyle]) -> list:
    story: list = []
    in_code = False
    code_lines: list[str] = []
    first_title = True
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("```"):
            if in_code:
                escaped = "<br/>".join(html.escape(part) or "&nbsp;" for part in code_lines)
                story.append(Paragraph(escaped, styles["code"]))
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line:
            story.append(Spacer(1, 1.5 * mm))
            continue
        if line.startswith("# "):
            title = html.escape(line[2:].strip())
            if first_title:
                story.append(Spacer(1, 35 * mm))
                story.append(Paragraph(title, styles["title"]))
                first_title = False
            else:
                story.append(PageBreak())
                story.append(Paragraph(title, styles["h1"]))
        elif line.startswith("## "):
            heading = html.escape(line[3:].strip())
            style = styles["subtitle"] if len(story) < 4 else styles["h2"]
            story.append(Paragraph(heading, style))
        elif line.startswith("- "):
            story.append(Paragraph("• " + html.escape(line[2:].strip()), styles["bullet"]))
        elif line.startswith("> "):
            story.append(Paragraph(html.escape(line[2:].strip()), styles["quote"]))
        else:
            story.append(Paragraph(html.escape(line), styles["body"]))
    return story


def draw_page(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont(FONT_NAME, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 12 * mm, "VoiceBoard｜跨境电商用户反馈与产品路线图平台")
    canvas.drawRightString(192 * mm, 12 * mm, f"{document.page}")
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.line(18 * mm, 17 * mm, 192 * mm, 17 * mm)
    canvas.restoreState()


def main() -> None:
    register_fonts()
    styles = build_styles()
    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=23 * mm,
        title="VoiceBoard 项目总结",
        author="DevinJack1020",
        subject="跨境电商用户反馈与产品路线图平台",
    )
    document.build(
        markdown_story(SOURCE.read_text(encoding="utf-8"), styles),
        onFirstPage=draw_page,
        onLaterPages=draw_page,
    )
    reader = PdfReader(str(OUTPUT))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    required = ("VoiceBoard", "完整产品闭环", "安全与可靠性", "简历表述")
    missing = [heading for heading in required if heading not in text]
    if missing:
        raise RuntimeError(f"PDF 缺少必要内容：{missing}")
    print(f"generated={OUTPUT}")
    print(f"pages={len(reader.pages)}")
    print(f"characters={len(text)}")


if __name__ == "__main__":
    main()
