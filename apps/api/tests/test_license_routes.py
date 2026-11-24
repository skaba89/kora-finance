"""API lecture licences: admin plateforme, isolation et dates civiles."""

import uuid
from collections.abc import Callable
from datetime import date

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from kora.api.v1.modules import router
from kora.audit.service import verify_chain
from kora.db.tenant import bind_tenant
from kora.models.audit import AuditEvent
from kora.models.identity import User
from kora.models.licenses import CommercialLicensePeriod
from kora.models.offers import CommercialOfferVersion
from tests.conftest import CompanyFixture, UserFixture


def test_api_lecture_licences_plateforme(
    client: TestClient,
    db: Session,
    owner_engine: Engine,
    make_company: Callable[..., CompanyFixture],
    make_user: Callable[..., UserFixture],
) -> None:
    company, other = make_company(), make_company()
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    code = f"test-{uuid.uuid4().hex}"
    with Session(owner_engine) as owner:
        bind_tenant(owner, company.id)
        owner.add(CommercialOfferVersion(code=code, version=1, modules=["sales"]))
        owner.flush()
        owner.add(
            CommercialLicensePeriod(
                tenant_id=company.id,
                offer_code=code,
                offer_version=1,
                kind="trial",
                starts_on=date(2027, 1, 1),
                ends_on=date(2027, 2, 1),
            )
        )
        owner.commit()

    url = f"/api/v1/platform/module-clients/{company.id}/licenses"
    params = {"as_of": "2027-01-15"}
    assert client.get(url, params=params).status_code == 401
    assert client.get(url, headers=other.headers, params=params).status_code == 403
    headers = admin.headers(client)
    assert client.get(url, headers=headers).status_code == 422
    assert client.get(url, headers=headers, params={"as_of": "invalid"}).status_code == 422
    response = client.get(url, headers=headers, params=params)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "trial"
    assert rows[0]["status"] == "trial"
    assert rows[0]["offer_code"] == code
    assert rows[0]["starts_on"] == "2027-01-01"
    assert rows[0]["ends_on"] == "2027-02-01"
    other_url = f"/api/v1/platform/module-clients/{other.id}/licenses"
    assert client.get(other_url, headers=headers, params=params).json() == []


def test_aucune_mutation_http_licence_exposee_sans_revue_securite() -> None:
    """Une exposition future des mutations exige une revue RBAC/IDOR explicite."""

    base = "/platform/module-clients/"
    license_routes = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path.startswith(base) and "/licenses" in route.path
    ]
    # M6c6 : seule la suspension/réactivation est ouverte, après revue RBAC/IDOR.
    exposed = {(route.path, frozenset(route.methods or ())) for route in license_routes}
    assert exposed == {
        ("/platform/module-clients/{client_id}/licenses", frozenset({"GET"})),
        (
            "/platform/module-clients/{client_id}/licenses/{license_id}/suspension",
            frozenset({"PUT"}),
        ),
    }


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_mutations_http_licences_non_exposees(client: TestClient, method: str) -> None:
    """Aucune écriture commerciale ne doit être accessible par HTTP."""
    url = f"/api/v1/platform/module-clients/{uuid.uuid4()}/licenses"
    response = client.request(method, url, json={"suspended": True})
    assert response.status_code == 405


def _seed_license(owner_engine: Engine, company_id: uuid.UUID) -> uuid.UUID:
    identifier = uuid.uuid4()
    code = f"test-{uuid.uuid4().hex}"
    with Session(owner_engine) as owner:
        bind_tenant(owner, company_id)
        owner.add(CommercialOfferVersion(code=code, version=1, modules=["sales"]))
        owner.flush()
        owner.add(
            CommercialLicensePeriod(
                id=identifier,
                tenant_id=company_id,
                offer_code=code,
                offer_version=1,
                kind="paid",
                starts_on=date(2027, 1, 1),
                ends_on=date(2028, 1, 1),
            )
        )
        owner.commit()
    return identifier


def _suspended(owner_engine: Engine, company_id: uuid.UUID, license_id: uuid.UUID) -> bool:
    with Session(owner_engine) as owner:
        bind_tenant(owner, company_id)
        return owner.get_one(CommercialLicensePeriod, license_id).suspended


def test_suspension_http_refus_rbac_idor_et_validation(
    client: TestClient,
    db: Session,
    owner_engine: Engine,
    make_company: Callable[..., CompanyFixture],
    make_user: Callable[..., UserFixture],
) -> None:
    company, other = make_company(), make_company()
    license_id = _seed_license(owner_engine, company.id)
    other_license = _seed_license(owner_engine, other.id)
    admin, revoked = make_user(), make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.get_one(User, revoked.id).is_platform_admin = True
    db.commit()
    admin_headers, revoked_headers = admin.headers(client), revoked.headers(client)
    db.get_one(User, revoked.id).is_platform_admin = False
    db.commit()

    def url(client_id: uuid.UUID, lic: uuid.UUID) -> str:
        return f"/api/v1/platform/module-clients/{client_id}/licenses/{lic}/suspension"

    body = {"suspended": True, "expected_suspended": False, "reason": "Impayé constaté"}
    target = url(company.id, license_id)
    # Authentification et RBAC : propriétaire de dossier et admin révoqué refusés.
    assert client.put(target, json=body).status_code == 401
    assert client.put(target, headers=company.headers, json=body).status_code == 403
    assert client.put(target, headers=other.headers, json=body).status_code == 403
    assert client.put(target, headers=revoked_headers, json=body).status_code == 403
    # IDOR : licence d'un autre dossier, dossier inconnu, licence inconnue.
    for client_id, lic in (
        (company.id, other_license),
        (other.id, license_id),
        (uuid.uuid4(), license_id),
        (company.id, uuid.uuid4()),
    ):
        response = client.put(url(client_id, lic), headers=admin_headers, json=body)
        assert response.status_code == 404, (client_id, lic)
    # Validation stricte du corps : types, motif, champs inconnus.
    for invalid in (
        {**body, "suspended": "true"},
        {**body, "expected_suspended": 0},
        {key: value for key, value in body.items() if key != "reason"},
        {**body, "reason": "  "},
        {**body, "reason": "x" * 501},
        {**body, "paid": True},
    ):
        assert client.put(target, headers=admin_headers, json=invalid).status_code == 422, invalid
    assert _suspended(owner_engine, company.id, license_id) is False
    assert _suspended(owner_engine, other.id, other_license) is False


def test_suspension_http_transitions_conflit_et_audit(
    client: TestClient,
    db: Session,
    owner_engine: Engine,
    make_company: Callable[..., CompanyFixture],
    make_user: Callable[..., UserFixture],
) -> None:
    company = make_company()
    license_id = _seed_license(owner_engine, company.id)
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    headers = admin.headers(client)
    target = f"/api/v1/platform/module-clients/{company.id}/licenses/{license_id}/suspension"
    suspend = {"suspended": True, "expected_suspended": False, "reason": "Impayé constaté"}

    response = client.put(target, headers=headers, json=suspend)
    assert response.status_code == 200, response.text
    assert response.json() == {"id": str(license_id), "suspended": True, "changed": True}
    assert _suspended(owner_engine, company.id, license_id) is True
    # État obsolète : la même demande ne s'applique pas deux fois.
    assert client.put(target, headers=headers, json=suspend).status_code == 409
    # Demande déjà satisfaite avec l'état attendu exact : sans effet ni audit.
    noop = {"suspended": True, "expected_suspended": True, "reason": "Vérification"}
    response = client.put(target, headers=headers, json=noop)
    assert response.status_code == 200
    assert response.json()["changed"] is False
    reactivate = {"suspended": False, "expected_suspended": True, "reason": "Paiement reçu"}
    assert client.put(target, headers=headers, json=reactivate).json()["changed"] is True
    assert _suspended(owner_engine, company.id, license_id) is False

    bind_tenant(db, company.id)
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == str(license_id)).order_by(AuditEvent.seq)
    ).all()
    assert [(e.action, e.payload["reason"], e.actor_user_id) for e in events] == [
        ("commercial.license_suspended", "Impayé constaté", admin.id),
        ("commercial.license_reactivated", "Paiement reçu", admin.id),
    ]
    assert verify_chain(db).ok
    # Les dates et l'offre ne sont jamais modifiées par la suspension.
    period = db.get_one(CommercialLicensePeriod, license_id)
    assert (period.starts_on, period.ends_on, period.kind) == (
        date(2027, 1, 1),
        date(2028, 1, 1),
        "paid",
    )
