from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kora.models.identity import User
from tests.conftest import CompanyFixture, UserFixture
from tests.test_purchases import _creer_fournisseur
from tests.test_sales import _creer_tier, _dossier, _lignes


@pytest.mark.parametrize(
    ("module", "invoice_kind", "credit_kind"),
    [
        ("sales", "invoice", "credit_note"),
        ("purchases", "supplier_invoice", "supplier_credit_note"),
    ],
)
def test_module_commercial_desactive_preserve_les_obligations(
    client: TestClient,
    db: Session,
    make_user: Callable[..., UserFixture],
    make_company: Callable[..., CompanyFixture],
    module: str,
    invoice_kind: str,
    credit_kind: str,
) -> None:
    company = _dossier(make_company)
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    admin_headers = admin.headers(client)
    base = f"/api/v1/companies/{company.id}"
    url = f"{base}/{module}"
    config = f"/api/v1/platform/module-clients/{company.id}/modules/{module}"
    partner = (
        _creer_tier(client, company) if module == "sales" else _creer_fournisseur(client, company)
    )
    body = {"doc_kind": invoice_kind, "partner_id": partner, "lines": _lignes()}
    created = client.post(url, headers=company.headers, json=body)
    assert created.status_code == 201, created.text
    invoice_id = created.json()["id"]
    quote_id = None
    if module == "sales":
        quote = client.post(url, headers=company.headers, json={**body, "doc_kind": "quote"})
        assert quote.status_code == 201, quote.text
        quote_id = quote.json()["id"]
        assert client.post(f"{url}/{quote_id}/send", headers=company.headers).status_code == 200
        decision = client.post(
            f"{url}/{quote_id}/decision", headers=company.headers, json={"accepted": True}
        )
        assert decision.status_code == 200
    change = client.put(
        config, headers=admin_headers, json={"enabled": False, "expected_revision": 0}
    )
    assert change.status_code == 200
    assert client.post(url, headers=company.headers, json=body).status_code == 403
    if quote_id is not None:
        assert client.post(f"{url}/{quote_id}/convert", headers=company.headers).status_code == 403
    assert client.get(f"{url}/{invoice_id}", headers=company.headers).status_code == 200
    assert client.post(f"{url}/{invoice_id}/issue", headers=company.headers).status_code == 200
    credit_body = {**body, "doc_kind": credit_kind, "origin_document_id": invoice_id}
    credit = client.post(url, headers=company.headers, json=credit_body)
    assert credit.status_code == 201, credit.text
    issued = client.post(f"{url}/{credit.json()['id']}/issue", headers=company.headers)
    assert issued.status_code == 200, issued.text
    change = client.put(
        config, headers=admin_headers, json={"enabled": True, "expected_revision": 1}
    )
    assert change.status_code == 200
    assert client.post(url, headers=company.headers, json=body).status_code == 201
