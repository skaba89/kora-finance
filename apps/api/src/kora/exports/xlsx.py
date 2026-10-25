"""Rendu Excel (.xlsx) d'un document : montants en nombres (sommables), dates en dates."""

import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from kora.exports.document import Cell, Column, Document, Row, Section, format_date

_BOLD = Font(bold=True)
_TITLE = Font(bold=True, size=14)
_MUTED = Font(italic=True, color="555555")
_TOTAL_FILL = PatternFill("solid", fgColor="EEEEEE")


def _sheet_title(title: str | None, index: int) -> str:
    # Excel : 31 caractères au plus, sans : \ / ? * [ ].
    cleaned = "".join(c for c in (title or f"Feuille {index}") if c not in ":\\/?*[]")
    return cleaned[:31] or f"Feuille {index}"


def _header(sheet: Worksheet, document: Document) -> None:
    generated = document.generated_at
    lines = [
        (document.title, _TITLE),
        (document.company_name, _BOLD),
        (document.identifiers, None),
        (document.period, None),
        (f"Montants en {document.currency}", None),
        (f"Généré le {format_date(generated.date())} à {generated:%H:%M} (UTC)", _MUTED),
        *((note, _MUTED) for note in document.notes),
    ]
    for text, font in lines:
        sheet.append([text])
        if font:
            sheet.cell(sheet.max_row, 1).font = font
    sheet.append([])


def _value(column: Column, cell: Cell, decimals: int) -> object:
    if cell is None:
        return None
    if column.kind == "amount" and isinstance(cell, int) and decimals:
        # Decimal exact : 1250 centimes → 12,50 sans passer par un flottant.
        return Decimal(cell).scaleb(-decimals)
    return cell


def _style_row(sheet: Worksheet, section: Section, row: Row, number_format: str) -> None:
    current = sheet.max_row
    for col_index, column in enumerate(section.columns, start=1):
        target = sheet.cell(current, col_index)
        if column.kind == "amount":
            target.number_format = number_format
            target.alignment = Alignment(horizontal="right")
        elif column.kind == "date":
            target.number_format = "DD/MM/YYYY"
        if row.style != "normal":
            target.font = _BOLD
        if row.style == "total":
            target.fill = _TOTAL_FILL


def _section(sheet: Worksheet, section: Section, decimals: int) -> None:
    number_format = "#,##0" if decimals == 0 else "#,##0." + "0" * decimals
    if section.title:
        sheet.append([section.title])
        sheet.cell(sheet.max_row, 1).font = _BOLD
    sheet.append([column.label for column in section.columns])
    header_row = sheet.max_row
    for col_index, column in enumerate(section.columns, start=1):
        sheet.cell(header_row, col_index).font = _BOLD
        sheet.column_dimensions[get_column_letter(col_index)].width = column.width + 2
    for row in section.rows:
        sheet.append(
            [_value(c, v, decimals) for c, v in zip(section.columns, row.cells, strict=True)]
        )
        _style_row(sheet, section, row, number_format)
    sheet.freeze_panes = f"A{header_row + 1}"


def render(document: Document) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for index, section in enumerate(document.sections, start=1):
        sheet = workbook.create_sheet(_sheet_title(section.title, index))
        _header(sheet, document)
        _section(sheet, section, document.decimals)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
