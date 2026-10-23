"""Isolation stricte entre dossiers (critère d'acceptation de la phase 1).

Ces tests parcourent *toutes* les routes de l'application : une nouvelle route
`/companies/{company_id}/…` est couverte automatiquement, sans rien ajouter ici.
"""

import re
import uuid
from collections.abc import Callable

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from kora.api.v1 import PREFIX, ROUTERS
from kora.db.tenant import bind_tenant
from kora.main import create_app
from kora.tenancy.deps import get_tenant
from tests.conftest import CompanyFixture, UserFixture

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]


def _api_routes() -> list[APIRoute]:
    return [r for router in ROUTERS for r in router.routes if isinstance(r, APIRoute)]


def _tenant_routes() -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for route in _api_routes():
        if "{company_id}" in route.path:
            routes.extend((method, PREFIX + route.path) for method in sorted(route.methods or ()))
    return routes


TENANT_ROUTES = _tenant_routes()


def test_le_registre_couvre_toutes_les_routes_publiees() -> None:
    """Toute route de l'API publiée dans OpenAPI est dans le registre parcouru ici."""
    published = {
        (method.upper(), path)
        for path, operations in create_app().openapi()["paths"].items()
        if path.startswith(PREFIX)
        for method in operations
    }
    registered = {
        (method, PREFIX + route.path) for route in _api_routes() for method in route.methods or ()
    }
    assert published == registered


def _depends_on(dependant: object, target: object) -> bool:
    for sub in getattr(dependant, "dependencies", []):
        if sub.call is target or _depends_on(sub, target):
            return True
    return False


def test_il_existe_des_routes_tenant_a_controler() -> None:
    assert len(TENANT_ROUTES) >= 15


@pytest.mark.parametrize(("method", "path"), TENANT_ROUTES)
def test_chaque_route_tenant_passe_par_le_controle_d_acces(method: str, path: str) -> None:
    route = next(
        r for r in _api_routes() if PREFIX + r.path == path and method in (r.methods or ())
    )
    assert _depends_on(route.dependant, get_tenant), f"{method} {path} sans contrôle tenant"


@pytest.mark.parametrize(("method", "path"), TENANT_ROUTES)
def test_un_utilisateur_ne_peut_rien_faire_sur_le_dossier_d_un_autre(
    client: TestClient, make_company: MakeCompany, method: str, path: str
) -> None:
    mine = make_company()
    theirs = make_company()
    url = re.sub(
        r"\{(\w+)\}", lambda m: str(theirs.id if m[1] == "company_id" else uuid.uuid4()), path
    )

    response = client.request(
        method, "/api/v1" + url.removeprefix("/api/v1"), headers=mine.headers, json={}
    )
    assert response.status_code == 404, f"{method} {url} → {response.status_code}"
    assert response.json()["code"] == "introuvable"


@pytest.mark.parametrize(("method", "path"), TENANT_ROUTES)
def test_routes_tenant_refusees_sans_authentification(
    client: TestClient, make_company: MakeCompany, method: str, path: str
) -> None:
    company = make_company()
    url = re.sub(
        r"\{(\w+)\}", lambda m: str(company.id if m[1] == "company_id" else uuid.uuid4()), path
    )
    assert client.request(method, url, json={}).status_code == 401


def test_la_liste_des_dossiers_ne_montre_que_les_siens(
    client: TestClient, make_company: MakeCompany
) -> None:
    mine = make_company()
    make_company()
    listed = client.get("/api/v1/companies", headers=mine.headers).json()
    assert [c["company"]["id"] for c in listed] == [str(mine.id)]


# --- IDOR : identifiant d'une ressource d'un autre dossier, via son propre dossier


def _first_account_id(client: TestClient, company: CompanyFixture) -> str:
    accounts = client.get(
        f"/api/v1/companies/{company.id}/accounts?q=401", headers=company.headers
    ).json()
    account_id: str = accounts["items"][0]["id"]
    return account_id


def test_idor_compte_d_un_autre_dossier(client: TestClient, make_company: MakeCompany) -> None:
    mine, theirs = make_company(), make_company()
    response = client.patch(
        f"/api/v1/companies/{mine.id}/accounts/{_first_account_id(client, theirs)}",
        headers=mine.headers,
        json={"is_active": False},
    )
    assert response.status_code == 404


def test_idor_membre_d_un_autre_dossier(client: TestClient, make_company: MakeCompany) -> None:
    mine, theirs = make_company(), make_company()
    their_member = client.get(
        f"/api/v1/companies/{theirs.id}/members", headers=theirs.headers
    ).json()[0]["id"]
    for method in ("PATCH", "DELETE"):
        response = client.request(
            method,
            f"/api/v1/companies/{mine.id}/members/{their_member}",
            headers=mine.headers,
            json={"role": "PME_LECTEUR"},
        )
        assert response.status_code == 404


def test_idor_taux_d_un_autre_dossier(client: TestClient, make_company: MakeCompany) -> None:
    mine, theirs = make_company(), make_company()
    their_rate = client.get(
        f"/api/v1/companies/{theirs.id}/tax-rates", headers=theirs.headers
    ).json()[0]["id"]
    response = client.post(
        f"/api/v1/companies/{mine.id}/tax-rates/{their_rate}/verification", headers=mine.headers
    )
    assert response.status_code == 404


# --- Base de données : toute table tenant est protégée par la RLS


def test_toute_table_avec_tenant_id_est_sous_rls(db: Session) -> None:
    rows = db.execute(
        text(
            """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
               EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = c.relname) AS has_policy
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
        WHERE c.relkind = 'r'
        """
        )
    ).all()
    assert rows, "aucune table tenant trouvée"
    unprotected = [
        r.relname for r in rows if not (r.relrowsecurity and r.relforcerowsecurity and r.has_policy)
    ]
    assert unprotected == []


def test_rls_masque_les_comptes_des_autres_dossiers(
    client: TestClient, make_company: MakeCompany, db: Session
) -> None:
    mine, theirs = make_company(), make_company()
    bind_tenant(db, mine.id)
    visible = db.execute(text("SELECT DISTINCT tenant_id FROM accounts")).scalars().all()
    assert visible == [mine.id]
    bind_tenant(db, None)
    assert db.execute(text("SELECT count(*) FROM accounts")).scalar_one() == 0
    assert theirs.id not in visible
