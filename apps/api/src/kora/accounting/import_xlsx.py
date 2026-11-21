"""Précontrôle d'un classeur normalisé, sans accès à la base."""

import re
import zipfile
from collections.abc import Iterator
from io import BytesIO
from typing import Self
from xml.parsers import expat

import openpyxl
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from kora.accounting.import_validation import (
    COLUMNS,
    MAX_IMPORT_ROWS,
    ImportIssue,
    ImportReport,
    validate_rows,
)

MAX_XLSX_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 128


class _RejectedError(ValueError):
    def __init__(self, code: str, row: int = 1) -> None:
        super().__init__(code)
        self.code = code
        self.row = row


def _check_xml(content: bytes) -> None:
    # UTF-8 uniquement : aucune DTD (même interne), ni expansion d'entité.
    decoded = content.decode("utf-8-sig")
    if "\x00" in decoded or "<!DOCTYPE" in decoded or "<!ENTITY" in decoded:
        raise _RejectedError("unsafe_xml")
    row = 0
    column = ""
    worksheet = False

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal row, column, worksheet
        local = name.rsplit("}", 1)[-1]
        if local == "worksheet":
            worksheet = True
        if local == "Relationship" and attrs.get("TargetMode") == "External":
            raise _RejectedError("external_link")
        if not worksheet:
            return
        if local == "row":
            number = attrs.get("r", "")
            if not re.fullmatch(r"[0-9]{1,6}", number):
                raise _RejectedError("row_limit")
            next_row = int(number)
            if not row < next_row <= MAX_IMPORT_ROWS + 2:
                raise _RejectedError("row_limit", next_row)
            row = next_row
            column = ""
        elif local == "c":
            reference = attrs.get("r", "")
            if not re.fullmatch(rf"[A-G]{row}", reference) or reference[0] <= column:
                raise _RejectedError("column_count", row)
            column = reference[0]
            if attrs.get("t") in ("e", "b"):
                raise _RejectedError("invalid_cell_type", row)
        elif local == "f":
            raise _RejectedError("formula_not_allowed", row)
        elif local == "mergeCell":
            raise _RejectedError("merged_cells", row)

    parser = expat.ParserCreate(namespace_separator="}")
    parser.StartElementHandler = start
    parser.Parse(decoded, True)


def _check_archive(content: bytes) -> None:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        members = archive.infolist()
        expanded = sum(item.file_size for item in members)
        if len(members) > MAX_MEMBERS or expanded > MAX_EXPANDED_BYTES:
            raise _RejectedError("expanded_size_limit")
        names = {item.filename for item in members}
        if len(names) != len(members) or "xl/workbook.xml" not in names:
            raise _RejectedError("invalid_xlsx")
        for item in members:
            name = item.filename
            if item.flag_bits & 1 or not name.endswith((".xml", ".rels")):
                raise _RejectedError("unsupported_xlsx_part")
            if name.startswith(("xl/externalLinks/", "xl/macrosheets/", "xl/embeddings/")):
                raise _RejectedError("unsupported_xlsx_part")
            _check_xml(archive.read(item))


def _cell(value: object, index: int) -> str:
    if isinstance(value, str):
        return value
    if index >= 5 and type(value) is int:
        return str(value)
    return ""


class _Rows:
    def __init__(self, rows: Iterator[tuple[object, ...]]) -> None:
        self._rows = rows
        self.line_num = 0

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> list[str]:
        row = next(self._rows)
        self.line_num += 1
        return [_cell(value, index) for index, value in enumerate(row)]


def validate_xlsx(content: bytes) -> ImportReport:
    """Une seule feuille, sept colonnes CSV, dates ISO et montants mineurs entiers.

    Les identifiants doivent être textuels pour préserver les zéros initiaux.
    Les formules, valeurs décimales et classeurs actifs ne sont pas interprétés.
    """
    if len(content) > MAX_XLSX_BYTES:
        return ImportReport(issues=[ImportIssue(1, "file_size_limit")])
    try:
        _check_archive(content)
        workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=False)
        try:
            if len(workbook.sheetnames) != 1 or len(workbook.worksheets) != 1:
                raise _RejectedError("sheet_count")
            sheet = workbook.worksheets[0]
            if not isinstance(sheet, ReadOnlyWorksheet):
                raise _RejectedError("invalid_xlsx")
            sheet.reset_dimensions()
            rows = _Rows(sheet.iter_rows(max_col=len(COLUMNS), values_only=True))
            return validate_rows(rows, COLUMNS, lambda row: row)
        finally:
            workbook.close()
    except _RejectedError as exc:
        return ImportReport(issues=[ImportIssue(exc.row, exc.code)])
    except Exception:
        # Les parseurs ZIP/XML/Excel lèvent des exceptions hétérogènes sur les
        # fichiers corrompus ; ne jamais exposer leur contenu dans le rapport.
        return ImportReport(issues=[ImportIssue(1, "invalid_xlsx")])
