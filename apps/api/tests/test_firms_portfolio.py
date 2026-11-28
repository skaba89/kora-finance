"""CAB-1 : portefeuille cabinet limité aux dossiers explicitement autorisés."""

import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import CompanyFixture, UserFixture

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]


def test_portefeuille_admin_et_collaborateur_sont_isoles(
    client: TestClient, make_user: MakeUser, make_company: MakeCompany
) -> None:
    admin_a, admin_b = make_user(), make_user()
    headers_a, headers_b = admin_a.headers(client), admin_b.headers(client)
    firm_a = client.post("/api/v1/firms", headers=headers_a, json={"name": "Alpha"}).json()
    firm_b = client.post("/api/v1/firms", headers=headers_b, json={"name": "Beta"}).json()
    first = make_company(owner=admin_a, firm_id=firm_a["id"])
    second = make_company(owner=admin_a, firm_id=firm_a["id"])
    outsider = make_company(owner=admin_b, firm_id=firm_b["id"])

    url = f"/api/v1/firms/{firm_a['id']}/portfolio"
    admin_response = client.get(url, headers=headers_a)
    assert admin_response.status_code == 200, admin_response.text
    assert {row["id"] for row in admin_response.json()} == {str(first.id), str(second.id)}
    assert all(
        set(row) == {"id", "legal_name", "trade_name", "city", "currency"}
        for row in admin_response.json()
    )

    worker = make_user()
    joined = client.post(
        f"/api/v1/firms/{firm_a['id']}/members",
        headers=headers_a,
        json={"email": worker.email, "role": "CABINET_COLLABORATEUR"},
    )
    assert joined.status_code == 201, joined.text
    headers_worker = worker.headers(client)
    empty = client.get(url, headers=headers_worker)
    assert empty.status_code == 200
    assert empty.json() == []

    assigned = client.post(
        f"/api/v1/firms/{firm_a['id']}/assignments",
        headers=headers_a,
        json={"firm_membership_id": joined.json()["id"], "company_id": str(first.id)},
    )
    assert assigned.status_code == 201, assigned.text
    portfolio = client.get(url, headers=headers_worker)
    assert portfolio.status_code == 200, portfolio.text
    assert [row["id"] for row in portfolio.json()] == [str(first.id)]

    # Les dossiers des autres cabinets ne sont jamais retournés.
    assert str(outsider.id) not in {row["id"] for row in portfolio.json()}
    assert client.get(url, headers=headers_b).status_code == 404
    assert client.get(f"/api/v1/firms/{firm_b['id']}/portfolio", headers=headers_worker).status_code == 404
    assert client.get(f"/api/v1/firms/{uuid.uuid4()}/portfolio", headers=headers_a).status_code == 404
