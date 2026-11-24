"""API lecture licences: admin plateforme, isolation et dates civiles."""

import uuid
from collections.abc import Callable
from datetime import date

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from kora.api.v1.modules import router
from kora.db.tenant import bind_tenant
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
    assert len(license_routes) == 1
    assert license_routes[0].path == "/platform/module-clients/{client_id}/licenses"
    assert license_routes[0].methods == {"GET"}
