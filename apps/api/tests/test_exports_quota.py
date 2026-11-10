"""KF-13 : budget d'exports (Redis, fenêtre fixe) — chaque export est synchrone et
coûteux : par utilisateur puis par dossier, l'excédent renvoie 429 avec Retry-After,
et une panne Redis interrompt l'export (jamais de contournement silencieux)."""

import re
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from kora.core import quota
from kora.core.config import get_settings
from tests.conftest import CompanyFixture, UserFixture

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]
MotDePasse = "Mot-de-passe-solide-2026"


@pytest.fixture
def limit_exports(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[int, int], None]]:
    """Fixe les limites d'exports pour le test (base Redis vidée entre tests) ; les
    réglages par défaut sont rétablis à la fin pour les tests suivants."""

    def _fixe(utilisateur: int, dossier: int) -> None:
        monkeypatch.setenv("KORA_EXPORTS_PER_USER_PER_HOUR", str(utilisateur))
        monkeypatch.setenv("KORA_EXPORTS_PER_COMPANY_PER_HOUR", str(dossier))
        get_settings.cache_clear()

    yield _fixe
    get_settings.cache_clear()


def _fy(client: TestClient, company: CompanyFixture) -> str:
    years = client.get(
        f"/api/v1/companies/{company.id}/fiscal-years", headers=company.headers
    ).json()
    return str(years[0]["id"])


def _export(
    client: TestClient, company: CompanyFixture, headers: dict[str, str] | None = None
) -> Any:
    return client.get(
        f"/api/v1/companies/{company.id}/exports/trial-balance",
        headers=headers or company.headers,
        params={"fiscal_year_id": _fy(client, company), "format": "xlsx"},
    )


def _second_membre(client: TestClient, company: CompanyFixture, mailbox: Any) -> dict[str, str]:
    """Invite puis inscrit un second membre (comptable) dans le dossier."""
    email = f"comptable-{uuid.uuid4().hex[:8]}@exemple.gn"
    response = client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": email, "role": "PME_COMPTABLE"},
    )
    assert response.status_code == 201, response.text
    sent = mailbox.last_to(email)
    match = re.search(r"/(?:fr|en)/invitation\?jeton=([A-Za-z0-9_-]+)", sent.text)
    assert match
    accept = client.post(
        "/api/v1/invitations/accept",
        json={"token": match[1], "full_name": "Kadiatou Barry", "password": MotDePasse},
    )
    assert accept.status_code in (200, 201), accept.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": MotDePasse})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_quota_utilisateur_renvoie_429_avec_retry_after(
    client: TestClient, make_company: MakeCompany, limit_exports: Callable[[int, int], None]
) -> None:
    company = make_company()
    limit_exports(2, 100)
    assert _export(client, company).status_code == 200
    assert _export(client, company).status_code == 200
    third = _export(client, company)
    assert third.status_code == 429, third.text
    assert third.json()["code"] == "trop_de_demandes"
    assert "limite" in third.json()["detail"].lower()
    retry_after = third.headers["Retry-After"]
    assert retry_after.isdigit()
    assert 0 < int(retry_after) <= 3600


def test_quota_par_dossier_borne_lensemble_des_membres(
    client: TestClient,
    make_company: MakeCompany,
    make_user: MakeUser,
    limit_exports: Callable[[int, int], None],
    mailbox: Any,
) -> None:
    company = make_company(owner=make_user(verified=True))
    second = _second_membre(client, company, mailbox)
    limit_exports(100, 1)
    # Le dirigeant consomme l'unique export du dossier…
    assert _export(client, company).status_code == 200
    # …le second membre est bloqué même si son propre compteur utilisateur est vierge.
    blocked = _export(client, company, headers=second)
    assert blocked.status_code == 429, blocked.text
    assert "dossier" in blocked.json()["detail"].lower()


def test_les_dossiers_sont_comptes_separement(
    client: TestClient, make_company: MakeCompany, limit_exports: Callable[[int, int], None]
) -> None:
    owner = make_company()  # son dirigeant possède deux dossiers
    other = make_company(owner=owner.owner)
    limit_exports(100, 1)
    assert _export(client, owner).status_code == 200
    # Le compteur du second dossier part de zéro : l'export y reste possible.
    assert _export(client, other).status_code == 200


def test_panne_redis_echoue_ferme(
    client: TestClient, make_company: MakeCompany, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = make_company()

    def en_panne() -> None:
        raise RedisError("Redis injoignable")

    monkeypatch.setattr("kora.core.quota.get_redis", en_panne)
    # L'export ne doit ni réussir ni être dégradé en silence : l'exception Redis
    # traverse (500 côté serveur), la protection n'est jamais désactivée.
    with pytest.raises(RedisError):
        _export(client, company)


def test_quota_compte_par_fenetre() -> None:
    subject = uuid.uuid4().hex
    kwargs: dict[str, Any] = {"limit": 2, "window_seconds": 60}
    assert quota.allowed("test-compteur", subject, **kwargs)
    assert quota.allowed("test-compteur", subject, **kwargs)
    assert not quota.allowed("test-compteur", subject, **kwargs)
    # Les autres sujets et fenêtres ne sont pas concernés.
    assert quota.allowed("test-compteur", uuid.uuid4().hex, **kwargs)
    assert quota.allowed("autre-scope", subject, **kwargs)


def test_quota_redis_en_panne_leve_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def en_panne() -> None:
        raise RedisError("Redis injoignable")

    monkeypatch.setattr("kora.core.quota.get_redis", en_panne)
    with pytest.raises(RedisError):
        quota.allowed("test-panne", "sujet", limit=1, window_seconds=60)
