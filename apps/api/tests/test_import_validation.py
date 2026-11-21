from io import StringIO

from kora.accounting.import_validation import MAX_IMPORT_ROWS, validate_normalized_csv

HEADER = "journal;ecriture;date;compte;libelle;debit;credit\n"


def test_balanced_noncontiguous_entries() -> None:
    report = validate_normalized_csv(
        StringIO(
            HEADER
            + "VT;1;2026-01-02;571;Vente;1500000;0\n"
            "AC;1;2026-01-03;601;Achat;20;0\n"
            "VT;1;2026-01-02;701;Vente;0;1500000\n"
            "AC;1;2026-01-03;401;Achat;0;20\n"
        )
    )
    assert report.valid
    assert (report.rows, report.entries, report.debit, report.credit) == (4, 2, 1500020, 1500020)


def test_reports_group_and_line_errors_without_source_values() -> None:
    report = validate_normalized_csv(
        StringIO(
            HEADER
            + "VT;1;2026-01-02;571;Vente;10;0\n"
            "VT;1;2026-01-03;701;Autre;0;9\n"
            "VT;2;2026-02-30;571;Vente;10;0\n"
            "VT;3;2026-01-02;571;Vente;1.5;0\n"
            "VT;4;2026-01-02;571;Vente;10;10\n"
            "VT;5;2026-01-02;571;Vente;10000000000001;0\n"
            "VT;6;2026-01-02;571;Vente;-1;0\n"
            "VT;7;2026-01-02;571;Vente;0;0\n"
            "short\n"
        )
    )
    assert not report.valid
    assert [(issue.row, issue.code) for issue in report.issues] == [
        (3, "inconsistent_entry"),
        (4, "invalid_date"),
        (5, "invalid_amount"),
        (6, "invalid_amount"),
        (7, "invalid_amount"),
        (8, "invalid_amount"),
        (9, "invalid_amount"),
        (10, "column_count"),
        (2, "unbalanced_entry"),
    ]


def test_file_validation_and_entry_limit() -> None:
    assert not validate_normalized_csv(StringIO(HEADER)).valid
    assert not validate_normalized_csv(StringIO("bad\n")).valid
    assert not validate_normalized_csv(StringIO(HEADER + '"unfinished')).valid
    rows = "VT;1;2026-01-02;571;Vente;1;0\n" * 501
    report = validate_normalized_csv(StringIO(HEADER + rows))
    assert any(issue.code == "entry_line_limit" for issue in report.issues)


def test_100000_rows_and_limit() -> None:
    rows = [HEADER]
    for entry in range(MAX_IMPORT_ROWS // 2):
        rows.append(f"VT;{entry};2026-01-02;571;Vente;10000000000000;0\n")
        rows.append(f"VT;{entry};2026-01-02;701;Vente;0;10000000000000\n")
    content = "".join(rows)
    report = validate_normalized_csv(StringIO(content))
    assert report.valid
    assert report.rows == MAX_IMPORT_ROWS
    assert report.entries == MAX_IMPORT_ROWS // 2
    assert report.debit == report.credit == 500_000_000_000_000_000
    report = validate_normalized_csv(StringIO(content + rows[1]))
    assert not report.valid
    assert report.issues[-1].code == "row_limit"
