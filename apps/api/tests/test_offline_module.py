import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kora.models.identity import User
from tests.conftest import CompanyFixture, UserFixture
from tests.ledger_helpers import Ledger, account_id


@pytest.mark.parametrize("kind", ["entries", "guided-entries"])
def test_synchronisation_desactivee_sans_bloquer_la_saisie_en_ligne(
    client: TestClient,
    db: Session,
    make_user: Callable[..., UserFixture],
    make_company: Callable[..., CompanyFixture],
    kind: str,
) -> None:
    company = make_company()
    ledger = Ledger(client, company)
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    admin_headers = admin.headers(client)
    config = f"/api/v1/platform/module-clients/{company.id}/modules"
    offline_headers = {**company.headers, "X-Kora-Offline-Sync": "1"}
    if kind == "entries":
        body = ledger.body([("571", 1000, 0), ("701", 0, 1000)])
    else:
        body = {
            "operation": "ACHAT_COMPTANT",
            "entry_date": "2026-03-15",
            "amount": "1000",
            "nature_account_id": account_id(client, ledger.base, company.headers, "605"),
            "treasury_account_id": account_id(client, ledger.base, company.headers, "571"),
        }
    body["id"] = str(uuid.uuid4())
    url = f"{ledger.base}/{kind}"
    assert client.post(url, headers=offline_headers, json=body).status_code == 201
    assert client.post(url, headers=offline_headers, json=body).status_code == 200
    change = client.put(
        f"{config}/offline", headers=admin_headers, json={"enabled": False, "expected_revision": 0}
    )
    assert change.status_code == 200
    # Même un rejeu déjà enregistré ne doit pas contourner la désactivation.
    assert client.post(url, headers=offline_headers, json=body).status_code == 403
    body["id"] = str(uuid.uuid4())
    assert client.post(url, headers=offline_headers, json=body).status_code == 403
    entry_url = f"{ledger.base}/entries/{body['id']}"
    assert client.get(entry_url, headers=company.headers).status_code == 404
    assert client.post(url, headers=company.headers, json=body).status_code == 201
    change = client.put(
        f"{config}/offline", headers=admin_headers, json={"enabled": True, "expected_revision": 1}
    )
    assert change.status_code == 200
    assert client.post(url, headers=offline_headers, json=body).status_code == 200
    change = client.put(
        f"{config}/accounting",
        headers=admin_headers,
        json={"enabled": False, "expected_revision": 0},
    )
    assert change.status_code == 200
    assert client.post(url, headers=offline_headers, json=body).status_code == 403
