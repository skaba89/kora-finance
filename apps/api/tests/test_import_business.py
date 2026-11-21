from datetime import date
from io import BytesIO

from openpyxl import Workbook

from kora.accounting.import_business import (
    MAX_CSV_BYTES,
    ImportCatalog,
    ImportPeriod,
    validate_import,
)
from kora.accounting.import_fec import FEC_COLUMNS
from kora.accounting.import_validation import COLUMNS

HEADER = ";".join(COLUMNS) + "\n"


def _catalog() -> ImportCatalog:
    return ImportCatalog(
        journals={"VT": True, "AC": False},
        accounts={"57": True, "571": True, "701": True, "601": False},
        periods=[
            ImportPeriod(date(2025, 1, 1), date(2025, 12, 31), False),
            ImportPeriod(date(2026, 1, 1), date(2026, 12, 31), True, date(2026, 1, 31)),
        ],
    )


def test_csv_catalog_checks_all_business_errors() -> None:
    content = (
        HEADER + "AC;1;2025-11-21;57;Vente;10;0\n"
        "AC;1;2025-11-21;601;Vente;0;10\n"
        "XX;2;2026-01-31;999;Vente;20;0\n"
        "XX;2;2026-01-31;701;Vente;0;20\n"
        "VT;3;2027-01-01;571;Vente;1;0\n"
        "VT;3;2027-01-01;701;Vente;0;1\n"
    ).encode()
    report = validate_import(content, file_format="csv", catalog=_catalog())
    assert not report.valid
    assert (report.rows, report.entries, report.debit, report.credit) == (6, 3, 31, 31)
    assert [(issue.row, issue.code) for issue in report.issues] == [
        (2, "inactive_journal"),
        (2, "grouping_account"),
        (2, "closed_fiscal_year"),
        (3, "inactive_journal"),
        (3, "inactive_account"),
        (3, "closed_fiscal_year"),
        (4, "unknown_journal"),
        (4, "unknown_account"),
        (4, "locked_period"),
        (5, "unknown_journal"),
        (5, "locked_period"),
        (6, "missing_fiscal_year"),
        (7, "missing_fiscal_year"),
    ]


def test_csv_valid_and_limits() -> None:
    content = (HEADER + "VT;1;2026-02-01;571;Vente;10;0\nVT;1;2026-02-01;701;Vente;0;10\n").encode()
    assert validate_import(content, file_format="csv", catalog=_catalog()).valid
    for data, code in (
        (b"\xff", "invalid_encoding"),
        (b"x" * (MAX_CSV_BYTES + 1), "file_size_limit"),
    ):
        report = validate_import(data, file_format="csv", catalog=_catalog())
        assert report.issues[0].code == code


def test_fec_catalog_check() -> None:
    debit = ["VT", "", "1", "20260201", "571", "", "", "", "", "", "Vente", "10", "0"]
    credit = ["VT", "", "1", "20260201", "999", "", "", "", "", "", "Vente", "0", "10"]
    rows = [list(FEC_COLUMNS), debit + [""] * 5, credit + [""] * 5]
    content = "\n".join("|".join(row) for row in rows).encode()
    report = validate_import(content, file_format="fec", catalog=_catalog())
    assert [(issue.row, issue.code) for issue in report.issues] == [(3, "unknown_account")]


def test_xlsx_catalog_check() -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(COLUMNS))
    sheet.append(["VT", "1", "2026-01-31", "571", "Vente", 10, 0])
    sheet.append(["VT", "1", "2026-01-31", "701", "Vente", 0, 10])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    report = validate_import(output.getvalue(), file_format="xlsx", catalog=_catalog())
    assert [(issue.row, issue.code) for issue in report.issues] == [
        (2, "locked_period"),
        (3, "locked_period"),
    ]
