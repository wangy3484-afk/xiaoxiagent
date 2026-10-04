"""PDF rendering for operations reports with embedded Chinese fonts."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    CondPageBreak,
    Image,
    ListFlowable,
    ListItem,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

from ops_agent.artifacts.branding import ReportBranding
from ops_agent.artifacts.rendering import (
    _Block,
    _build_document,
    _BulletList,
    _Heading,
    _Paragraph,
    _Table,
    _Text,
)
from ops_agent.domain.report import OperationsReport


@dataclass(frozen=True, slots=True)
class PdfRenderConfig:
    """Layout and identity settings that do not alter report content."""

    font_path: Path | None = None
    bold_font_path: Path | None = None
    orientation: Literal["portrait", "landscape"] = "landscape"
    header_text: str | None = None
    footer_text: str = "运营策略 Agent · 决策支持材料"


@dataclass(frozen=True, slots=True)
class _RegisteredFonts:
    regular: str
    bold: str


class PdfFontUnavailableError(RuntimeError):
    """Raised when no Chinese-capable font can be embedded."""


class _InvariantCanvas(canvas.Canvas):  # type: ignore[misc]
    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs["invariant"] = 1
        super().__init__(*args, **kwargs)


def render_operations_report_pdf(
    report: OperationsReport,
    *,
    config: PdfRenderConfig | None = None,
    branding: ReportBranding | None = None,
) -> bytes:
    """Render an immutable PDF with repeated table headers and live links."""

    resolved_config = config or PdfRenderConfig()
    active_branding = branding or ReportBranding()
    fonts = _register_fonts(resolved_config)
    page_size = A4 if resolved_config.orientation == "portrait" else landscape(A4)
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
        title=active_branding.display_title(report.title),
        author="Operations Strategy Agent",
        subject="Evidence-based operations decision support report",
    )
    styles = _styles(fonts)
    story: list[object] = []
    if active_branding.logo_path is not None:
        active_branding.logo_data_uri()
        story.extend([_logo_flowable(active_branding.logo_path), Spacer(1, 3 * mm)])
    story.append(
        Paragraph(
            escape(active_branding.display_title(report.title)), styles["title"]
        )
    )
    story.extend(
        _build_story(_build_document(report), document.width, styles, fonts)
    )
    header = (
        resolved_config.header_text
        or active_branding.header_text
        or active_branding.display_title(report.title)
    )
    draw_page = partial(
        _draw_header_footer,
        fonts=fonts,
        header_text=header,
        footer_text=resolved_config.footer_text,
        report_id=report.report_id,
    )
    document.build(
        story,
        onFirstPage=draw_page,
        onLaterPages=draw_page,
        canvasmaker=_InvariantCanvas,
    )
    return buffer.getvalue()


def _logo_flowable(path: Path) -> Image:
    logo = Image(str(path.resolve()))
    max_width = 45 * mm
    max_height = 12 * mm
    scale = min(max_width / logo.imageWidth, max_height / logo.imageHeight, 1)
    logo.drawWidth = logo.imageWidth * scale
    logo.drawHeight = logo.imageHeight * scale
    logo.hAlign = "LEFT"
    return logo


def _register_fonts(config: PdfRenderConfig) -> _RegisteredFonts:
    regular_path = _resolve_font_path(config.font_path, bold=False)
    if regular_path is None:
        raise PdfFontUnavailableError(
            "No Chinese PDF font found. Set OPS_AGENT_PDF_FONT_PATH or install "
            "fonts-wqy-zenhei in the runtime image."
        )
    bold_path = _resolve_font_path(config.bold_font_path, bold=True) or regular_path

    digest = hashlib.sha256(str(regular_path).encode("utf-8")).hexdigest()[:10]
    regular_name = f"OpsAgentCJK-{digest}"
    bold_digest = hashlib.sha256(str(bold_path).encode("utf-8")).hexdigest()[:10]
    bold_name = f"OpsAgentCJKBold-{bold_digest}"
    if regular_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont(
                regular_name,
                str(regular_path),
                subfontIndex=_ttc_subfont_index(regular_path),
            )
        )
    if bold_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont(
                bold_name,
                str(bold_path),
                subfontIndex=_ttc_subfont_index(bold_path),
            )
        )
    return _RegisteredFonts(regular=regular_name, bold=bold_name)


def _resolve_font_path(configured: Path | None, *, bold: bool) -> Path | None:
    environment_name = (
        "OPS_AGENT_PDF_BOLD_FONT_PATH" if bold else "OPS_AGENT_PDF_FONT_PATH"
    )
    environment_path = os.environ.get(environment_name)
    candidates = [
        configured,
        Path(environment_path) if environment_path else None,
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path(
            "C:/Windows/Fonts/"
            f"{'msyhbd.ttc' if bold else 'msyh.ttc'}"
        ),
        None if bold else Path("C:/Windows/Fonts/simhei.ttf"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    return None


def _ttc_subfont_index(path: Path) -> int:
    return 0


def _styles(fonts: _RegisteredFonts) -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "OpsTitle",
            parent=sample["Title"],
            fontName=fonts.bold,
            fontSize=20,
            leading=28,
            textColor=colors.HexColor("#172033"),
            alignment=TA_LEFT,
            spaceAfter=10 * mm,
            wordWrap="CJK",
        ),
        "h2": ParagraphStyle(
            "OpsH2",
            parent=sample["Heading2"],
            fontName=fonts.bold,
            fontSize=13,
            leading=18,
            textColor=colors.HexColor("#24466F"),
            spaceBefore=7 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
            wordWrap="CJK",
        ),
        "h3": ParagraphStyle(
            "OpsH3",
            parent=sample["Heading3"],
            fontName=fonts.bold,
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#27364B"),
            spaceBefore=5 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
            wordWrap="CJK",
        ),
        "body": ParagraphStyle(
            "OpsBody",
            parent=sample["BodyText"],
            fontName=fonts.regular,
            fontSize=8.5,
            leading=13,
            textColor=colors.HexColor("#172033"),
            spaceAfter=2.5 * mm,
            wordWrap="CJK",
        ),
        "table": ParagraphStyle(
            "OpsTable",
            parent=sample["BodyText"],
            fontName=fonts.regular,
            fontSize=7.2,
            leading=10.5,
            textColor=colors.HexColor("#172033"),
            wordWrap="CJK",
        ),
        "table_header": ParagraphStyle(
            "OpsTableHeader",
            parent=sample["BodyText"],
            fontName=fonts.bold,
            fontSize=7.2,
            leading=10.5,
            textColor=colors.HexColor("#172033"),
            wordWrap="CJK",
        ),
        "notice": ParagraphStyle(
            "OpsNotice",
            parent=sample["BodyText"],
            fontName=fonts.regular,
            fontSize=8,
            leading=12,
            textColor=colors.HexColor("#70490D"),
            leftIndent=4 * mm,
            rightIndent=4 * mm,
            borderColor=colors.HexColor("#D69E2E"),
            borderWidth=0.7,
            borderPadding=7,
            backColor=colors.HexColor("#FFFAF0"),
            spaceAfter=3 * mm,
            wordWrap="CJK",
        ),
        "quality": ParagraphStyle(
            "OpsQuality",
            parent=sample["BodyText"],
            fontName=fonts.regular,
            fontSize=8,
            leading=12,
            textColor=colors.HexColor("#24466F"),
            leftIndent=4 * mm,
            rightIndent=4 * mm,
            borderColor=colors.HexColor("#5B8CC6"),
            borderWidth=0.7,
            borderPadding=7,
            backColor=colors.HexColor("#EFF6FF"),
            spaceAfter=3 * mm,
            wordWrap="CJK",
        ),
    }


def _build_story(
    blocks: tuple[_Block, ...],
    available_width: float,
    styles: dict[str, ParagraphStyle],
    fonts: _RegisteredFonts,
) -> list[object]:
    story: list[object] = []
    for index, block in enumerate(blocks):
        if isinstance(block, _Heading):
            if (
                block.level == 2
                and index + 1 < len(blocks)
                and isinstance(blocks[index + 1], _Heading)
            ):
                story.append(PageBreak())
            story.append(CondPageBreak(18 * mm))
            style_name = "h2" if block.level == 2 else "h3"
            story.append(
                Paragraph(
                    f'<a name={quoteattr(block.anchor)}/>{escape(block.title)}',
                    styles[style_name],
                )
            )
        elif isinstance(block, _Paragraph):
            story.append(
                Paragraph(
                    _pdf_rich_text(block.content),
                    styles[block.role if block.role != "normal" else "body"],
                )
            )
        elif isinstance(block, _BulletList):
            story.append(
                ListFlowable(
                    [
                        ListItem(
                            Paragraph(_pdf_rich_text(item), styles["body"]),
                            leftIndent=4 * mm,
                        )
                        for item in block.items
                    ],
                    bulletType="bullet",
                    start="circle",
                    leftIndent=6 * mm,
                    bulletFontName=fonts.regular,
                    bulletFontSize=7,
                )
            )
            story.append(Spacer(1, 2 * mm))
        else:
            story.append(_pdf_table(block, available_width, styles))
            story.append(Spacer(1, 2 * mm))
    return story


def _pdf_table(
    block: _Table,
    available_width: float,
    styles: dict[str, ParagraphStyle],
) -> LongTable:
    headers = [Paragraph(escape(item), styles["table_header"]) for item in block.headers]
    rows = [
        [Paragraph(_pdf_rich_text(cell), styles["table"]) for cell in row]
        for row in block.rows
    ]
    column_widths = [available_width * fraction for fraction in _column_fractions(len(headers))]
    table = LongTable(
        [headers, *rows],
        colWidths=column_widths,
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0F7")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#BFCBDC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFCFF")]),
            ]
        )
    )
    return table


def _column_fractions(count: int) -> tuple[float, ...]:
    preferred = {
        2: (0.22, 0.78),
        4: (0.14, 0.36, 0.26, 0.24),
        5: (0.16, 0.23, 0.23, 0.19, 0.19),
        6: (0.10, 0.15, 0.26, 0.15, 0.17, 0.17),
    }
    return preferred.get(count, tuple(1 / count for _ in range(count)))


def _pdf_rich_text(value: _Text) -> str:
    content = escape(value.value).replace("\n", "<br/>")
    if value.href:
        content = (
            f'<a href={quoteattr(value.href)} color="#1859A9"><u>{content}</u></a>'
        )
    if value.anchor:
        content = f'<a name={quoteattr(value.anchor)}/>{content}'
    if value.citations:
        references = " ".join(
            f'<a href="#evidence-{label.lower()}" color="#1859A9">[{label}]</a>'
            for label in value.citations
        )
        content = f"{content} {references}"
    return content


def _draw_header_footer(
    page_canvas: canvas.Canvas,
    document: SimpleDocTemplate,
    *,
    fonts: _RegisteredFonts,
    header_text: str,
    footer_text: str,
    report_id: str,
) -> None:
    page_canvas.saveState()
    width, height = document.pagesize
    page_canvas.setTitle(header_text)
    page_canvas.setAuthor("Operations Strategy Agent")
    page_canvas.setFont(fonts.regular, 7)
    page_canvas.setFillColor(colors.HexColor("#607086"))
    page_canvas.drawString(document.leftMargin, height - 12 * mm, header_text[:80])
    page_canvas.drawRightString(
        width - document.rightMargin,
        height - 12 * mm,
        f"报告 ID: {report_id}",
    )
    page_canvas.setStrokeColor(colors.HexColor("#D4DDE8"))
    page_canvas.setLineWidth(0.35)
    page_canvas.line(
        document.leftMargin,
        height - 14 * mm,
        width - document.rightMargin,
        height - 14 * mm,
    )
    page_canvas.line(
        document.leftMargin,
        12 * mm,
        width - document.rightMargin,
        12 * mm,
    )
    page_canvas.drawString(document.leftMargin, 8 * mm, footer_text[:80])
    page_canvas.setFont(fonts.bold, 7)
    page_canvas.drawRightString(
        width - document.rightMargin,
        8 * mm,
        f"第 {document.page} 页",
    )
    page_canvas.restoreState()
