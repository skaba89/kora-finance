from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook

from kora.accounting.import_validation import COLUMNS
from kora.accounting.import_xlsx import MAX_XLSX_BYTES, validate_xlsx


def _file(*rows: list[object], extra_sheet: bool = False) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(COLUMNS))
    for row in rows:
        sheet.append(row)
    if extra_sheet:
        workbook.create_sheet("Autre")
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def test_xlsx_balanced_exact_integer_amounts() -> None:
    report = validate_xlsx(
        _file(
            ["VT", "001", "2026-11-21", "0571", "Vente", 10**13, 0],
            ["VT", "001", "2026-11-21", "0701", "Vente", "0", "10000000000000"],
        )
    )
    assert report.valid
    assert (report.rows, report.entries, report.debit, report.credit) == (2, 1, 10**13, 10**13)


def test_xlsx_refuses_ambiguous_amount_and_numeric_identifier() -> None:
    for amount in (1.5, "1.5", "1e3", "-1"):
        report = validate_xlsx(_file(["VT", "001", "2026-11-21", "571", "Vente", amount, 0]))
        assert report.issues[0].code == "invalid_amount"
    report = validate_xlsx(_file(["VT", 1, "2026-11-21", "571", "Vente", 10, 0]))
    assert report.issues[0].code == "invalid_text"


def test_xlsx_refuses_formulas_extra_columns_and_sheets() -> None:
    row: list[object] = ["VT", "1", "2026-11-21", "571", "Vente", 10, 0]
    formula = [*row[:5], "=5+5", 0]
    for content, code in (
        (_file(formula), "formula_not_allowed"),
        (_file([*row, "extra"]), "column_count"),
        (_file(row, extra_sheet=True), "sheet_count"),
        (b"x" * (MAX_XLSX_BYTES + 1), "file_size_limit"),
        (b"invalid", "invalid_xlsx"),
    ):
        report = validate_xlsx(content)
        assert not report.valid
        assert report.issues[0].code == code


def test_xlsx_rejects_dtd_before_loading() -> None:
    output = BytesIO()
    with ZipFile(BytesIO(_file())) as source, ZipFile(output, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                data = b'<!DOCTYPE worksheet [<!ENTITY x "bad">]>' + data
            target.writestr(name, data)
    report = validate_xlsx(output.getvalue())
    assert not report.valid
    assert report.issues[0].code == "unsafe_xml"
