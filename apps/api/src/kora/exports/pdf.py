"""Rendu PDF (A4) d'un document : en-tête du dossier, tableaux, pied de page numéroté."""

import io
from functools import lru_cache
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from kora.exports.document import Document, Section, format_amount, format_date

_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONT = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"


@lru_cache
def _register_fonts() -> None:
    """Police Unicode installée dans l'image (fonts-dejavu-core). Absente : erreur
    explicite, pas de repli silencieux sur une police qui perdrait des caractères."""
    for name in (FONT, FONT_BOLD):
        path = _FONT_DIR / f"{name}.ttf"
        if not path.exists():
            raise RuntimeError(f"Police {path} introuvable : installer fonts-dejavu-core.")
        pdfmetrics.registerFont(TTFont(name, str(path)))


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName=FONT_BOLD, fontSize=14, leading=18),
        "company": ParagraphStyle("company", fontName=FONT_BOLD, fontSize=10, leading=13),
        "meta": ParagraphStyle("meta", fontName=FONT, fontSize=8.5, leading=11),
        "note": ParagraphStyle(
            "note", fontName=FONT, fontSize=7.5, leading=10, textColor=colors.HexColor("#555555")
        ),
        "section": ParagraphStyle(
            "section", fontName=FONT_BOLD, fontSize=11, leading=15, spaceBefore=6
        ),
        "cell": ParagraphStyle("cell", fontName=FONT, fontSize=7.5, leading=9),
        "cell_bold": ParagraphStyle("cell_bold", fontName=FONT_BOLD, fontSize=7.5, leading=9),
    }


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(
    section: Section, decimals: int, width: float, styles: dict[str, ParagraphStyle]
) -> Table:
    total_width = sum(column.width for column in section.columns)
    col_widths = [width * column.width / total_width for column in section.columns]
    data: list[list[object]] = [
        [Paragraph(_escape(column.label), styles["cell_bold"]) for column in section.columns]
    ]
    commands: list[Any] = [
        ("FONT", (0, 0), (-1, -1), FONT, 7.5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for col_index, column in enumerate(section.columns):
        if column.kind in ("amount", "number"):
            commands.append(("ALIGN", (col_index, 0), (col_index, -1), "RIGHT"))
    for row_index, row in enumerate(section.rows, start=1):
        bold = row.style in ("total", "subtotal", "heading")
        cells: list[object] = []
        for column, cell in zip(section.columns, row.cells, strict=True):
            if cell is None:
                cells.append("")
            elif column.kind == "amount" and isinstance(cell, int):
                # Zéros des lignes de détail laissés en blanc (lisibilité) ; totaux affichés.
                cells.append(
                    "" if cell == 0 and row.style == "normal" else format_amount(cell, decimals)
                )
            elif column.kind == "date" and not isinstance(cell, (str, int)):
                cells.append(format_date(cell))
            elif column.kind == "text":
                cells.append(Paragraph(_escape(str(cell)), styles["cell_bold" if bold else "cell"]))
            else:
                cells.append(str(cell))
        data.append(cells)
        if bold:
            commands.append(("FONT", (0, row_index), (-1, row_index), FONT_BOLD, 7.5))
        if row.style == "total":
            commands.append(
                ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#EEEEEE"))
            )
            commands.append(("LINEABOVE", (0, row_index), (-1, row_index), 0.4, colors.black))
        elif row.style == "subtotal":
            commands.append(
                ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#F6F6F6"))
            )
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(commands))
    return table


class _NumberedCanvas(Canvas):
    """Pied de page « Page x / y » : le total n'est connu qu'à la fin."""

    def __init__(self, *args: object, footer: str = "", **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._saved_states: list[dict[str, object]] = []
        self._footer = footer

    # Attributs internes de reportlab (_startPage, _pagesize, _pageNumber) : technique
    # usuelle de numérotation « page x / y », non couverte par les stubs de typage.
    def showPage(self) -> None:  # noqa: N802 (API reportlab)
        self._saved_states.append(dict(self.__dict__))
        self._startPage()  # type: ignore[attr-defined]

    def save(self) -> None:
        total = len(self._saved_states)
        for state in self._saved_states:
            self.__dict__.update(state)
            self.setFont(FONT, 7)
            width = self._pagesize[0]  # type: ignore[attr-defined]
            self.drawString(15 * mm, 8 * mm, self._footer)
            page = self._pageNumber  # type: ignore[attr-defined]
            self.drawRightString(width - 15 * mm, 8 * mm, f"Page {page} / {total}")
            super().showPage()
        super().save()


def render(document: Document) -> bytes:
    _register_fonts()
    styles = _styles()
    pagesize = landscape(A4) if document.landscape else A4
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=pagesize,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=document.title,
        author="Kora Finance",
    )
    story: list[object] = [
        Paragraph(_escape(document.title), styles["title"]),
        Paragraph(_escape(document.company_name), styles["company"]),
        Paragraph(_escape(document.identifiers), styles["meta"]),
        Paragraph(_escape(f"{document.period} — montants en {document.currency}"), styles["meta"]),
    ]
    story += [Paragraph(_escape(note), styles["note"]) for note in document.notes]
    story.append(Spacer(1, 4 * mm))
    for section in document.sections:
        if section.title:
            story.append(Paragraph(_escape(section.title), styles["section"]))
        story.append(_table(section, document.decimals, doc.width, styles))
        story.append(Spacer(1, 4 * mm))
    footer = (
        f"{document.company_name} — {document.title} — généré le "
        f"{format_date(document.generated_at.date())} à {document.generated_at:%H:%M} UTC"
    )
    doc.build(story, canvasmaker=lambda *a, **k: _NumberedCanvas(*a, footer=footer, **k))  # type: ignore[arg-type]
    return output.getvalue()
