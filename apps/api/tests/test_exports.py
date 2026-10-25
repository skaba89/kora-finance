"""Exports PDF et Excel."""

import io
import re
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from kora.core.errors import BusinessRuleError
from kora.exports import service
from kora.exports.document import currency_decimals, format_amount
from tests.conftest import CompanyFixture
from tests.ledger_helpers import Ledger, account_id

MakeCompany = Callable[..., CompanyFixture]


@pytest.mark.parametrize(
    ("amount", "decimals", "text"),
    [(1_234_567, 0, "1\u202f234\u202f567"), (-1250, 2, "-12,50"), (7, 2, "0,07"), (0, 0, "0")],
)
def test_format_des_montants(amount: int, decimals: int, text: str) -> None:
    assert format_amount(amount, decimals) == text


def test_devise_non_prise_en_charge() -> None:
    assert currency_decimals("GNF") == 0
    with pytest.raises(BusinessRuleError):
        currency_decimals("ZZZ")


@pytest.fixture
def book(client: TestClient, make_company: MakeCompany) -> Ledger:
    ledger = Ledger(
        client,
        make_company(legal_name="Société <b>Élégance</b> & Fils SARL", rccm="GN.TCC.2024.B.1"),
    )
    ledger.posted(
        [("521", 5_000_000, 0), ("101", 0, 5_000_000)], journal="AN", entry_date="2026-01-01"
    )
    ledger.posted(
        [("411", 1_180_000, 0), ("701", 0, 1_000_000), ("4431", 0, 180_000)],
        journal="VT",
        entry_date="2026-02-10",
    )
    ledger.posted(
        [("521", 1_180_000, 0), ("411", 0, 1_180_000)], journal="BQ", entry_date="2026-03-20"
    )
    return ledger


def _fy(book: Ledger) -> str:
    years = book.client.get(f"{book.base}/fiscal-years", headers=book.company.headers).json()
    return str(years[0]["id"])


def _export(book: Ledger, path: str, file_format: str, **params: str) -> Any:
    return book.client.get(
        f"{book.base}/exports/{path}",
        headers=book.company.headers,
        params={"fiscal_year_id": _fy(book), "format": file_format, **params},
    )


def _sheet_rows(content: bytes) -> list[tuple[Any, ...]]:
    workbook = load_workbook(io.BytesIO(content), read_only=True)
    return [
        tuple(row) for sheet in workbook.worksheets for row in sheet.iter_rows(values_only=True)
    ]


def test_balance_excel(book: Ledger) -> None:
    response = _export(book, "trial-balance", "xlsx")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(service.MEDIA_TYPES["xlsx"])
    assert (
        'filename="balance-societe-b-elegance-b-fils-sarl-20260101-20261231.xlsx"'
        in (response.headers["content-disposition"])
    )
    rows = _sheet_rows(response.content)
    assert rows[0][0] == "Balance générale"
    assert rows[1][0] == "Société <b>Élégance</b> & Fils SARL"
    by_account = {row[0]: row for row in rows if isinstance(row[0], str) and row[0].isdigit()}
    # Montants numériques (sommables dans Excel), pas du texte.
    assert by_account["521"][2:] == (5_000_000, 0, 1_180_000, 0, 6_180_000, 0)
    total = next(row for row in rows if row[1] == "Total général")
    assert total[2:] == (5_000_000, 5_000_000, 2_360_000, 2_360_000, 6_180_000, 6_180_000)


def test_grand_livre_excel_de_tous_les_comptes(book: Ledger) -> None:
    rows = _sheet_rows(_export(book, "ledger", "xlsx").content)
    headings = [row[4] for row in rows if isinstance(row[4], str) and " — " in row[4]]
    assert headings == [
        "101 — Capital social",
        "411 — Clients",
        "4431 — TVA facturée sur ventes",
        "521 — Banques locales",
        "701 — Ventes de marchandises",
    ]
    closing_521 = next(row for row in rows if row[4] == "Total 521 et solde de clôture")
    assert closing_521[5:] == (1_180_000, 0, 6_180_000)


def test_grand_livre_d_un_seul_compte(book: Ledger) -> None:
    rows = _sheet_rows(
        _export(
            book,
            "ledger",
            "xlsx",
            account_id=account_id(book.client, book.base, book.company.headers, "411"),
        ).content
    )
    assert [row[4] for row in rows if isinstance(row[4], str) and " — " in row[4]] == [
        "411 — Clients"
    ]


def test_journal_des_ecritures_equilibre(book: Ledger) -> None:
    book.create([("601", 999, 0), ("401", 0, 999)])  # brouillon : exclu
    rows = _sheet_rows(_export(book, "entries", "xlsx").content)
    total = next(row for row in rows if row[5] == "Total")
    assert total[6] == total[7] == 7_360_000
    assert not any(row[6] == 999 for row in rows)


@pytest.mark.parametrize("path", ["trial-balance", "ledger", "entries", "financial-statements"])
def test_exports_pdf(book: Ledger, path: str) -> None:
    response = _export(book, path, "pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type\s*/Page[^s]", response.content)) >= 1
    assert response.headers["cache-control"] == "no-store"


def test_etats_financiers_excel(book: Ledger) -> None:
    workbook = load_workbook(
        io.BytesIO(_export(book, "financial-statements", "xlsx").content), read_only=True
    )
    assert workbook.sheetnames == ["Bilan — Actif", "Bilan — Passif", "Compte de résultat"]
    income = list(workbook["Compte de résultat"].iter_rows(values_only=True))
    assert any("expert-comptable" in str(row[0]) for row in income)
    assert next(row for row in income if row[0] == "XI")[2] == 1_000_000


def test_format_inconnu(book: Ledger) -> None:
    assert _export(book, "trial-balance", "csv").status_code == 422


def test_pdf_trop_volumineux(book: Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "MAX_PDF_ROWS", 3)
    response = _export(book, "ledger", "pdf")
    assert response.status_code == 422
    assert "Excel" in response.json()["detail"]
    assert _export(book, "ledger", "xlsx").status_code == 200


def test_chaque_export_est_trace(book: Ledger) -> None:
    _export(book, "trial-balance", "pdf")
    events = book.client.get(f"{book.base}/audit-events", headers=book.company.headers).json()[
        "items"
    ]
    event = next(e for e in events if e["action"] == "export.generated")
    assert event["payload"]["type"] == "balance"
    assert event["payload"]["format"] == "pdf"
