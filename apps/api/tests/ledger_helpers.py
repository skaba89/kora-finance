"""Aides communes aux tests de comptabilité générale (via l'API)."""

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import CompanyFixture


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


class Ledger:
    """Raccourcis d'appel à l'API pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def body(self, lines: list[tuple[str, int, int]], **kwargs: Any) -> dict[str, Any]:
        return entry_body(self.client, self.base, self.company.headers, lines, **kwargs)

    def create(self, lines: list[tuple[str, int, int]], **kwargs: Any) -> Any:
        return self.client.post(
            f"{self.base}/entries", headers=self.company.headers, json=self.body(lines, **kwargs)
        )

    def post(self, entry_id: str) -> Any:
        return self.client.post(
            f"{self.base}/entries/{entry_id}/post", headers=self.company.headers
        )

    def posted(self, lines: list[tuple[str, int, int]], **kwargs: Any) -> dict[str, Any]:
        created = self.create(lines, **kwargs)
        assert created.status_code == 201, created.text
        response = self.post(created.json()["id"])
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result
