"""Authentification : inscription, connexion, verrouillage, jetons, sessions."""

import uuid
from collections.abc import Callable
from datetime import timedelta

import jwt
import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.audit.service import verify_chain
from kora.auth.tokens import create_mfa_token
from kora.core.config import get_settings
from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.audit import AuditEvent
from kora.models.common import utcnow
from kora.models.identity import RefreshToken, User
from tests.conftest import UserFixture

MakeUser = Callable[..., UserFixture]
PASSWORD = "Mot-de-passe-solide-2026"


def _register(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Mamadou Bah"},
    )
    return {"status": response.status_code, "body": response.json()}


def _login(client: TestClient, email: str, password: str) -> dict[str, object]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return {"status": response.status_code, "body": response.json(), "headers": response.headers}


# --- Inscription


def test_inscription_normalise_l_email_et_ne_renvoie_aucun_secret(client: TestClient) -> None:
    result = _register(client, "  Fatou.Camara@Exemple.GN ")
    assert result["status"] == 201
    body = result["body"]
    assert isinstance(body, dict)
    assert body["email"] == "fatou.camara@exemple.gn"
    assert "password" not in str(body).lower()
    assert body["mfa_enabled"] is False


def test_inscription_refuse_un_email_deja_utilise_quelle_que_soit_la_casse(
    client: TestClient,
) -> None:
    assert _register(client, "doublon@exemple.gn")["status"] == 201
    result = _register(client, "DOUBLON@exemple.gn")
    assert result["status"] == 409
    assert result["body"] == {
        "detail": "Un compte existe déjà avec cette adresse email.",
        "code": "conflit",
        "errors": [],
    }


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("court", "au moins 10 caractères"),
        ("aaaaaaaaaaaa", "trop répétitif"),
        ("identique@exemple.gn", "identique à l'adresse email"),
    ],
)
def test_inscription_applique_la_politique_de_mot_de_passe(
    client: TestClient, password: str, message: str
) -> None:
    result = _register(client, "identique@exemple.gn", password)
    assert result["status"] == 422
    body = result["body"]
    assert isinstance(body, dict)
    assert any(message in error for error in body["errors"])


def test_mot_de_passe_stocke_en_argon2id(make_user: MakeUser, db: Session) -> None:
    user = make_user()
    stored = db.get(User, user.id)
    assert stored is not None
    assert stored.password_hash.startswith("$argon2id$")


# --- Connexion


def test_connexion_puis_profil(client: TestClient, make_user: MakeUser) -> None:
    user = make_user()
    tokens = user.login(client)
    assert tokens["status"] == "authenticated"
    assert tokens["token_type"] == "bearer"
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == user.email


def test_message_identique_pour_compte_inconnu_et_mauvais_mot_de_passe(
    client: TestClient, make_user: MakeUser
) -> None:
    user = make_user()
    wrong_password = _login(client, user.email, "Mauvais-mot-de-passe-1")
    unknown = _login(client, "inconnu@exemple.gn", "Mauvais-mot-de-passe-1")
    assert wrong_password["status"] == unknown["status"] == 401
    assert wrong_password["body"] == unknown["body"]


def test_verrouillage_apres_echecs_repetes(client: TestClient, make_user: MakeUser) -> None:
    user = make_user()
    max_failures = get_settings().login_max_failures
    for _ in range(max_failures):
        assert _login(client, user.email, "Mauvais-mot-de-passe-1")["status"] == 401

    # Le bon mot de passe est refusé pendant le verrouillage.
    locked = _login(client, user.email, user.password)
    assert locked["status"] == 423
    assert locked["body"]["code"] == "compte_verrouille"  # type: ignore[index]
    assert int(locked["headers"]["retry-after"]) > 0  # type: ignore[index]

    with time_machine.travel(
        utcnow() + timedelta(seconds=get_settings().login_lockout_seconds + 1)
    ):
        assert _login(client, user.email, user.password)["status"] == 200


def test_succes_remet_le_compteur_d_echecs_a_zero(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    user = make_user()
    for _ in range(get_settings().login_max_failures - 1):
        _login(client, user.email, "Mauvais-mot-de-passe-1")
    user.login(client)
    stored = db.get(User, user.id)
    assert stored is not None
    assert stored.failed_login_count == 0


def test_compte_desactive_ne_peut_pas_se_connecter(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    user = make_user()
    stored = db.get(User, user.id)
    assert stored is not None
    stored.is_active = False
    db.commit()
    assert _login(client, user.email, user.password)["status"] == 401


# --- Jetons d'accès


def test_route_protegee_sans_jeton(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_jeton_d_acces_expire_refuse(client: TestClient, make_user: MakeUser) -> None:
    headers = make_user().headers(client)
    ttl = get_settings().access_token_ttl_seconds
    with time_machine.travel(utcnow() + timedelta(seconds=ttl + 60)):
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_jeton_mfa_refuse_comme_jeton_d_acces(client: TestClient, make_user: MakeUser) -> None:
    user = make_user()
    token = create_mfa_token(user.id, 0)
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.parametrize("attaque", ["signature", "alg_none", "autre_cle"])
def test_jeton_falsifie_refuse(client: TestClient, make_user: MakeUser, attaque: str) -> None:
    user = make_user()
    access = user.login(client)["access_token"]
    claims = jwt.decode(access, options={"verify_signature": False})
    claims["sub"] = str(uuid.uuid4())
    if attaque == "signature":
        forged = access.rsplit(".", 1)[0] + ".AAAA"
    elif attaque == "alg_none":
        forged = jwt.encode(claims, key=None, algorithm="none")  # type: ignore[arg-type]
    else:
        forged = jwt.encode(claims, "x" * 64, algorithm="HS256")
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


# --- Refresh tokens


def test_rafraichissement_fait_tourner_les_jetons(client: TestClient, make_user: MakeUser) -> None:
    tokens = make_user().login(client)
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    renewed = response.json()
    assert renewed["refresh_token"] != tokens["refresh_token"]
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {renewed['access_token']}"}
        ).status_code
        == 200
    )


def test_reutilisation_d_un_refresh_token_revoque_toute_la_famille(
    client: TestClient, make_user: MakeUser
) -> None:
    user = make_user()
    stolen = user.login(client)["refresh_token"]
    legit = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen}).json()

    # L'attaquant rejoue le jeton volé, consommé depuis plus longtemps que la tolérance.
    grace = get_settings().refresh_reuse_grace_seconds
    with time_machine.travel(utcnow() + timedelta(seconds=grace + 1)):
        replay = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
        assert replay.status_code == 401
        assert replay.json()["code"] == "session_expiree"

        # Le jeton légitime de la même famille est révoqué lui aussi…
        after = client.post("/api/v1/auth/refresh", json={"refresh_token": legit["refresh_token"]})
        assert after.status_code == 401

    # … et la révocation est durable (vérifiée depuis une autre session).
    with get_sessionmaker()() as other:
        tokens = other.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        ).scalars()
        assert all(t.revoked_at is not None for t in tokens)
        bind_tenant(other, None)
        actions = (
            other.execute(select(AuditEvent.action).where(AuditEvent.actor_user_id == user.id))
            .scalars()
            .all()
        )
        assert "auth.refresh_reuse_detected" in actions


def test_requetes_paralleles_tolerees_pendant_la_fenetre_de_grace(
    client: TestClient, make_user: MakeUser
) -> None:
    token = make_user().login(client)["refresh_token"]
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert first.status_code == second.status_code == 200
    # Les deux successeurs restent utilisables.
    for response in (first, second):
        renewed = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": response.json()["refresh_token"]}
        )
        assert renewed.status_code == 200


def test_jeton_revoque_refuse_meme_pendant_la_fenetre_de_grace(
    client: TestClient, make_user: MakeUser
) -> None:
    token = make_user().login(client)["refresh_token"]
    client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    client.post("/api/v1/auth/logout", json={"refresh_token": token})
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": token}).status_code == 401


def test_refresh_token_expire_refuse(client: TestClient, make_user: MakeUser) -> None:
    tokens = make_user().login(client)
    days = get_settings().refresh_token_ttl_days
    with time_machine.travel(utcnow() + timedelta(days=days, minutes=1)):
        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
    assert response.status_code == 401


def test_refresh_token_inconnu_refuse(client: TestClient) -> None:
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "inexistant"})
    assert response.status_code == 401


# --- Déconnexion et changement de mot de passe


def test_deconnexion_ferme_la_session(client: TestClient, make_user: MakeUser) -> None:
    tokens = make_user().login(client)
    assert (
        client.post(
            "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )


def test_deconnexion_partout_invalide_les_jetons_d_acces(
    client: TestClient, make_user: MakeUser
) -> None:
    user = make_user()
    device_a = user.login(client)
    device_b = user.login(client)
    headers_a = {"Authorization": f"Bearer {device_a['access_token']}"}
    assert client.post("/api/v1/auth/logout-everywhere", headers=headers_a).status_code == 204

    for device in (device_a, device_b):
        headers = {"Authorization": f"Bearer {device['access_token']}"}
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
        refresh = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": device["refresh_token"]}
        )
        assert refresh.status_code == 401


def test_changement_de_mot_de_passe(client: TestClient, make_user: MakeUser) -> None:
    user = make_user()
    old = user.login(client)
    old_headers = {"Authorization": f"Bearer {old['access_token']}"}
    response = client.post(
        "/api/v1/auth/password",
        headers=old_headers,
        json={"current_password": user.password, "new_password": "Nouveau-mot-de-passe-2026"},
    )
    assert response.status_code == 200
    new_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    assert client.get("/api/v1/auth/me", headers=old_headers).status_code == 401
    assert client.get("/api/v1/auth/me", headers=new_headers).status_code == 200
    assert _login(client, user.email, user.password)["status"] == 401
    assert _login(client, user.email, "Nouveau-mot-de-passe-2026")["status"] == 200


def test_changement_de_mot_de_passe_exige_le_mot_de_passe_actuel(
    client: TestClient, make_user: MakeUser
) -> None:
    user = make_user()
    response = client.post(
        "/api/v1/auth/password",
        headers=user.headers(client),
        json={"current_password": "Pas-le-bon-mot-de-passe", "new_password": "Nouveau-mdp-2026"},
    )
    assert response.status_code == 401


# --- Limitation de débit et audit


def test_limitation_de_debit_sur_la_connexion(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "auth_rate_limit_per_minute", 3)
    statuses = [_login(client, "x@exemple.gn", "Mauvais-mdp-123")["status"] for _ in range(4)]
    assert statuses == [401, 401, 401, 429]
    blocked = _login(client, "x@exemple.gn", "Mauvais-mdp-123")
    assert int(blocked["headers"]["retry-after"]) > 0  # type: ignore[index]


def test_evenements_d_authentification_audites_et_chaine_intacte(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    user = make_user()
    _login(client, user.email, "Mauvais-mot-de-passe-1")
    user.login(client)
    bind_tenant(db, None)
    actions = (
        db.execute(
            select(AuditEvent.action)
            .where(AuditEvent.actor_user_id == user.id)
            .order_by(AuditEvent.seq)
        )
        .scalars()
        .all()
    )
    assert actions == ["user.registered", "auth.login_failed", "auth.login_succeeded"]
    assert verify_chain(db).ok
