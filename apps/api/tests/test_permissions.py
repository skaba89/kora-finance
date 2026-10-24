"""Matrice rôle × permission, testée de bout en bout sur l'API (critère d'acceptation)."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kora.tenancy.permissions import ROLE_PERMISSIONS, Permission, render_markdown
from kora.tenancy.roles import Role
from tests.conftest import CompanyFixture, UserFixture
from tests.ledger_helpers import account_id, entry_body

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Scenario:
    company_id: uuid.UUID
    headers: dict[str, str]


def _scenario(
    role: Role, client: TestClient, make_user: MakeUser, make_company: MakeCompany
) -> Scenario:
    if role in (Role.PME_DIRIGEANT, Role.PME_COMPTABLE, Role.PME_LECTEUR):
        company = make_company()
        if role == Role.PME_DIRIGEANT:
            return Scenario(company.id, company.headers)
        member = make_user()
        added = client.post(
            f"/api/v1/companies/{company.id}/members",
            headers=company.headers,
            json={"email": member.email, "role": role.value},
        )
        assert added.status_code == 201, added.text
        return Scenario(company.id, member.headers(client))

    admin = make_user()
    admin_headers = admin.headers(client)
    firm = client.post("/api/v1/firms", headers=admin_headers, json={"name": "Cabinet Test"}).json()
    company = make_company(owner=admin, firm_id=firm["id"])
    if role == Role.CABINET_ADMIN:
        return Scenario(company.id, admin_headers)
    collaborator = make_user()
    membership = client.post(
        f"/api/v1/firms/{firm['id']}/members",
        headers=admin_headers,
        json={"email": collaborator.email, "role": role.value},
    ).json()
    assigned = client.post(
        f"/api/v1/firms/{firm['id']}/assignments",
        headers=admin_headers,
        json={"firm_membership_id": membership["id"], "company_id": str(company.id)},
    )
    assert assigned.status_code == 201, assigned.text
    return Scenario(company.id, collaborator.headers(client))


def _probe(permission: Permission, client: TestClient, s: Scenario, make_user: MakeUser) -> int:
    base = f"/api/v1/companies/{s.company_id}"
    calls: dict[Permission, Callable[[], int]] = {
        Permission.COMPANY_READ: lambda: client.get(base, headers=s.headers).status_code,
        Permission.COMPANY_UPDATE: lambda: (
            client.patch(base, headers=s.headers, json={"city": "Conakry"}).status_code
        ),
        Permission.MEMBERS_READ: lambda: (
            client.get(f"{base}/members", headers=s.headers).status_code
        ),
        Permission.MEMBERS_MANAGE: lambda: (
            client.post(
                f"{base}/members",
                headers=s.headers,
                json={"email": make_user().email, "role": "PME_LECTEUR"},
            ).status_code
        ),
        Permission.FISCAL_YEARS_READ: lambda: (
            client.get(f"{base}/fiscal-years", headers=s.headers).status_code
        ),
        Permission.FISCAL_YEARS_MANAGE: lambda: (
            client.post(
                f"{base}/fiscal-years",
                headers=s.headers,
                json={"start_date": "2027-01-01", "end_date": "2027-12-31"},
            ).status_code
        ),
        Permission.ACCOUNTS_READ: lambda: (
            client.get(f"{base}/accounts", headers=s.headers).status_code
        ),
        Permission.ACCOUNTS_MANAGE: lambda: (
            client.post(
                f"{base}/accounts",
                headers=s.headers,
                json={"number": "4011001", "label": "Fournisseur test"},
            ).status_code
        ),
        Permission.TAXES_READ: lambda: (
            client.get(f"{base}/tax-rates", headers=s.headers).status_code
        ),
        Permission.TAXES_MANAGE: lambda: (
            client.post(
                f"{base}/tax-rates",
                headers=s.headers,
                json={
                    "code": "TAXE_TEST",
                    "label": "Test",
                    "kind": "AUTRE",
                    "rate_basis_points": 100,
                    "valid_from": "2026-01-01",
                },
            ).status_code
        ),
        Permission.AUDIT_READ: lambda: (
            client.get(f"{base}/audit-events", headers=s.headers).status_code
        ),
        Permission.JOURNALS_MANAGE: lambda: (
            client.post(
                f"{base}/journals",
                headers=s.headers,
                json={
                    "code": f"T{uuid.uuid4().hex[:6].upper()}",
                    "label": "Test",
                    "kind": "OPERATIONS_DIVERSES",
                },
            ).status_code
        ),
        Permission.ENTRIES_READ: lambda: (
            client.get(f"{base}/entries", headers=s.headers).status_code
        ),
        Permission.ENTRIES_WRITE: lambda: _create_draft(client, base, s).status_code,
        Permission.FISCAL_YEARS_CLOSE: lambda: _close_probe(client, base, s),
        Permission.LETTERING_MANAGE: lambda: (
            client.post(
                f"{base}/letterings/auto",
                headers=s.headers,
                json={"account_id": account_id(client, base, s.headers, "411")},
            ).status_code
        ),
        Permission.ENTRIES_POST: lambda: (
            client.post(
                f"{base}/entries/{_draft_id_or_random(client, base, s)}/post", headers=s.headers
            ).status_code
        ),
    }
    return calls[permission]()


def _close_probe(client: TestClient, base: str, s: Scenario) -> int:
    """Clôture d'un exercice vide (2030) dont le suivant (2031) existe."""
    for year in (2030, 2031):
        client.post(
            f"{base}/fiscal-years",
            headers=s.headers,
            json={"start_date": f"{year}-01-01", "end_date": f"{year}-12-31"},
        )
    years = client.get(f"{base}/fiscal-years", headers=s.headers).json()
    target = next((y["id"] for y in years if y["start_date"] == "2030-01-01"), years[0]["id"])
    return client.post(f"{base}/fiscal-years/{target}/closing", headers=s.headers).status_code


def _create_draft(client: TestClient, base: str, s: Scenario) -> Any:
    body = entry_body(client, base, s.headers, [("571", 1000, 0), ("701", 0, 1000)])
    return client.post(f"{base}/entries", headers=s.headers, json=body)


def _draft_id_or_random(client: TestClient, base: str, s: Scenario) -> str:
    created = _create_draft(client, base, s)
    return str(created.json()["id"]) if created.status_code == 201 else str(uuid.uuid4())


TENANT_ROLES = [
    Role.PME_DIRIGEANT,
    Role.PME_COMPTABLE,
    Role.PME_LECTEUR,
    Role.CABINET_ADMIN,
    Role.CABINET_COLLABORATEUR,
]


@pytest.mark.parametrize("role", TENANT_ROLES)
def test_matrice_des_permissions(
    role: Role, client: TestClient, make_user: MakeUser, make_company: MakeCompany
) -> None:
    scenario = _scenario(role, client, make_user, make_company)
    mismatches = []
    for permission in Permission:
        status_code = _probe(permission, client, scenario, make_user)
        allowed = permission in ROLE_PERMISSIONS[role]
        if (status_code < 300) != allowed or (not allowed and status_code != 403):
            mismatches.append(
                f"{permission.value}: attendu {'autorisé' if allowed else '403'}, "
                f"obtenu {status_code}"
            )
    assert mismatches == [], f"{role.value} : {mismatches}"


@pytest.mark.parametrize("role", [Role.SUPER_ADMIN, Role.PARTENAIRE_FINANCIER])
def test_roles_sans_acces_aux_dossiers(role: Role) -> None:
    assert ROLE_PERMISSIONS[role] == frozenset()


def test_super_admin_ne_voit_pas_les_dossiers(
    client: TestClient, make_user: MakeUser, make_company: MakeCompany, db: object
) -> None:
    from kora.db.session import get_sessionmaker  # noqa: PLC0415
    from kora.models.identity import User  # noqa: PLC0415

    company = make_company()
    admin = make_user()
    with get_sessionmaker()() as session:
        user = session.get(User, admin.id)
        assert user is not None
        user.is_platform_admin = True
        session.commit()
    response = client.get(f"/api/v1/companies/{company.id}", headers=admin.headers(client))
    assert response.status_code == 404


def test_collaborateur_non_affecte_n_a_pas_acces(
    client: TestClient, make_user: MakeUser, make_company: MakeCompany
) -> None:
    admin = make_user()
    headers = admin.headers(client)
    firm = client.post("/api/v1/firms", headers=headers, json={"name": "Cabinet"}).json()
    company = make_company(owner=admin, firm_id=firm["id"])
    collaborator = make_user()
    client.post(
        f"/api/v1/firms/{firm['id']}/members",
        headers=headers,
        json={"email": collaborator.email, "role": "CABINET_COLLABORATEUR"},
    )
    response = client.get(f"/api/v1/companies/{company.id}", headers=collaborator.headers(client))
    assert response.status_code == 404


def test_documentation_des_permissions_a_jour() -> None:
    documented = (REPO_ROOT / "docs" / "PERMISSIONS.md").read_text(encoding="utf-8")
    assert documented == render_markdown(), "Lancer `make permissions-doc` et committer."
