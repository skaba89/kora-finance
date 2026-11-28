"""Révocation CAB-2 : suppression immédiate des accès, isolation et audit."""

import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.db.tenant import bind_tenant
from kora.models.audit import AuditEvent
from kora.models.identity import FirmAssignment, FirmMembership
from tests.conftest import CompanyFixture, UserFixture

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]


def test_revocation_retirer_tous_les_acces_et_preserver_l_audit(
    client: TestClient, db: Session, make_user: MakeUser, make_company: MakeCompany
) -> None:
    admin, worker = make_user(), make_user()
    headers = admin.headers(client)
    firm = client.post("/api/v1/firms", headers=headers, json={"name": "Alpha"}).json()
    company_a = make_company(owner=admin, firm_id=firm["id"])
    company_b = make_company(owner=admin, firm_id=firm["id"])
    member = client.post(
        f"/api/v1/firms/{firm['id']}/members",
        headers=headers,
        json={"email": worker.email, "role": "CABINET_COLLABORATEUR"},
    )
    assert member.status_code == 201, member.text
    member_id = member.json()["id"]
    for company in (company_a, company_b):
        assigned = client.post(
            f"/api/v1/firms/{firm['id']}/assignments",
            headers=headers,
            json={"firm_membership_id": member_id, "company_id": str(company.id)},
        )
        assert assigned.status_code == 201, assigned.text

    worker_headers = worker.headers(client)
    for company in (company_a, company_b):
        assert (
            client.get(f"/api/v1/companies/{company.id}", headers=worker_headers).status_code == 200
        )

    url = f"/api/v1/firms/{firm['id']}/members/{member_id}"
    revoked = client.delete(url, headers=headers)
    assert revoked.status_code == 204, revoked.text
    assert revoked.content == b""
    assert client.delete(url, headers=headers).status_code == 404
    for company in (company_a, company_b):
        assert (
            client.get(f"/api/v1/companies/{company.id}", headers=worker_headers).status_code == 404
        )
    assert (
        client.get(f"/api/v1/firms/{firm['id']}/portfolio", headers=worker_headers).status_code
        == 404
    )

    bind_tenant(db, None)
    assert (
        db.scalar(select(FirmMembership.id).where(FirmMembership.id == uuid.UUID(member_id)))
        is None
    )
    assert (
        db.scalars(
            select(FirmAssignment).where(FirmAssignment.firm_membership_id == uuid.UUID(member_id))
        ).all()
        == []
    )
    audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "firm.collaborator_revoked"))
    assert audit is not None
    assert audit.payload["user_id"] == str(worker.id)
    assert audit.payload["membership_id"] == member_id


def test_revocation_refuse_admin_et_exterieurs(client: TestClient, make_user: MakeUser) -> None:
    admin, other_admin, worker = make_user(), make_user(), make_user()
    headers = admin.headers(client)
    firm = client.post("/api/v1/firms", headers=headers, json={"name": "Alpha"}).json()
    other_headers = other_admin.headers(client)
    other_firm = client.post("/api/v1/firms", headers=other_headers, json={"name": "Beta"}).json()
    member = client.post(
        f"/api/v1/firms/{firm['id']}/members",
        headers=headers,
        json={"email": worker.email, "role": "CABINET_COLLABORATEUR"},
    )
    assert member.status_code == 201, member.text
    member_id = member.json()["id"]
    url = f"/api/v1/firms/{firm['id']}/members/{member_id}"
    assert client.delete(url, headers=other_headers).status_code == 404
    assert client.delete(url, headers=worker.headers(client)).status_code == 403
    assert (
        client.delete(
            f"/api/v1/firms/{other_firm['id']}/members/{member_id}",
            headers=other_headers,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/firms/{firm['id']}/members/{uuid.uuid4()}", headers=headers
        ).status_code
        == 404
    )

    members = client.get(f"/api/v1/firms/{firm['id']}/members", headers=headers).json()
    admin_id = next(row["id"] for row in members if row["role"] == "CABINET_ADMIN")
    assert (
        client.delete(f"/api/v1/firms/{firm['id']}/members/{admin_id}", headers=headers).status_code
        == 422
    )
    # Aucun des refus précédents ne supprime le collaborateur.
    assert client.delete(url, headers=headers).status_code == 204
