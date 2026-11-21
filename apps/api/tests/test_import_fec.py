from kora.accounting.import_fec import FEC_COLUMNS, MAX_FEC_BYTES, validate_fec


def _row(account: str, debit: str, credit: str, day: str = "20261121") -> list[str]:
    return [
        "VT",
        "Ventes",
        "1",
        day,
        account,
        "Compte",
        "",
        "",
        "P1",
        day,
        "Vente",
        debit,
        credit,
        "",
        "",
        day,
        "",
        "",
    ]


def _file(*rows: list[str], separator: str = "|") -> bytes:
    return ("\n".join(separator.join(row) for row in [list(FEC_COLUMNS), *rows]) + "\n").encode()


def test_fec_exact_amounts_and_bom() -> None:
    content = _file(_row("571", "1234,50", "0"), _row("701", "0", "1234.5"))
    report = validate_fec(b"\xef\xbb\xbf" + content, scale=2, delimiter="|")
    assert report.valid
    assert (report.rows, report.entries, report.debit, report.credit) == (2, 1, 123450, 123450)


def test_fec_gnf_tab_and_no_rounding() -> None:
    content = _file(_row("571", "100,00", "0"), _row("701", "0", "100"), separator="\t")
    assert validate_fec(content, scale=0, delimiter="\t").valid
    for amount in ("100,01", "1e3", "-1", "1 000", "1.001", "10000000000001"):
        report = validate_fec(_file(_row("571", amount, "0")), scale=0, delimiter="|")
        assert not report.valid
        assert report.issues[0].code == "invalid_amount"


def test_fec_rejects_invalid_structure() -> None:
    for content, code in (
        (b"bad\n", "invalid_header"),
        (b"\xff", "invalid_encoding"),
        (b"x" * (MAX_FEC_BYTES + 1), "file_size_limit"),
        (_file(["short"]), "column_count"),
        (_file(_row("571", "10", "0", "20260230")), "invalid_date"),
    ):
        report = validate_fec(content, scale=0, delimiter="|")
        assert not report.valid
        assert report.issues[0].code == code


def test_fec_reuses_group_validation() -> None:
    report = validate_fec(
        _file(_row("571", "100", "0"), _row("701", "0", "99")), scale=0, delimiter="|"
    )
    assert not report.valid
    assert [(issue.row, issue.code) for issue in report.issues] == [(2, "unbalanced_entry")]
