"""Aides communes aux tests de comptabilité générale (via l'API)."""

from typing import Any

from fastapi.testclient import TestClient


def journal_id(client: TestClient, base: str, headers: dict[str, str], code: str) -> str:
    journals = client.get(f"{base}/journals", headers=headers).json()
    return str(next(j["id"] for j in journals if j["code"] == code))


def account_id(client: TestClient, base: str, headers: dict[str, str], number: str) -> str:
    items = client.get(f"{base}/accounts", headers=headers, params={"q": number}).json()["items"]
    return str(next(a["id"] for a in items if a["number"] == number))


def entry_body(
    client: TestClient,
    base: str,
    headers: dict[str, str],
    lines: list[tuple[str, int, int]],
    *,
    journal: str = "OD",
    entry_date: str = "2026-03-15",
    label: str = "Écriture de test",
) -> dict[str, Any]:
    """`lines` : (numéro de compte, débit, crédit)."""
    return {
        "journal_id": journal_id(client, base, headers, journal),
        "entry_date": entry_date,
        "label": label,
        "lines": [
            {"account_id": account_id(client, base, headers, n), "debit": str(d), "credit": str(c)}
            for n, d, c in lines
        ],
    }
