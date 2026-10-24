"""Mot de passe oublié, vérification de l'adresse et notifications par email."""

import re
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import update
from sqlalchemy.orm import Session

from kora.core.config import get_settings
from kora.email.sender import OUTBOX
from kora.models.common import utcnow
from kora.models.identity import EmailToken, User
from kora.worker import tasks
from tests.conftest import Mailbox, UserFixture

MakeUser = Callable[..., UserFixture]

FORGOT = "/api/v1/auth/password/forgot"
RESET = "/api/v1/auth/password/reset"
NEW_PASSWORD = "Nouveau-secret-solide-2026"


def _token(body: str, page: str) -> str:
    match = re.search(rf"/(?:fr|en)/{page}\?jeton=([A-Za-z0-9_-]+)", body)
    assert match, f"lien {page} absent de l'email"
    return match[1]


def _reset_token(client: TestClient, mailbox: Mailbox, user: UserFixture) -> str:
    assert client.post(FORGOT, json={"email": user.email}).status_code == 202
    return _token(mailbox.last_to(user.email).text, "reinitialisation-mot-de-passe")


# --- Mot de passe oublié


def test_reinitialisation_complete(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox, db: Session
) -> None:
    user = make_user()
    old_session = user.login(client)
    mailbox.deliver()  # email de vérification de l'inscription
    OUTBOX.clear()

    token = _reset_token(client, mailbox, user)
    email = mailbox.last_to(user.email)
    assert email.subject == "Réinitialisation de votre mot de passe Kora Finance"
    assert token not in email.subject
    assert f"{get_settings().web_public_url}/fr/reinitialisation-mot-de-passe?jeton=" in email.html

    response = client.post(RESET, json={"token": token, "new_password": NEW_PASSWORD})
    assert response.status_code == 204, response.text

    # Ancien mot de passe refusé, nouveau accepté, anciennes sessions fermées.
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": user.password}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": old_session["refresh_token"]}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": NEW_PASSWORD}
        ).status_code
        == 200
    )
    # Le lien ne sert qu'une fois.
    reused = client.post(RESET, json={"token": token, "new_password": "Autre-secret-solide-2026"})
    assert reused.status_code == 400
    assert reused.json()["code"] == "lien_invalide"
    # L'adresse est vérifiée de fait, et une notification part.
    assert db.get_one(User, user.id).email_verified_at is not None
    assert mailbox.last_to(user.email).subject == "Votre mot de passe Kora Finance a été modifié"


def test_reponse_identique_compte_existant_ou_non(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox
) -> None:
    user = make_user()
    mailbox.deliver()
    OUTBOX.clear()
    known = client.post(FORGOT, json={"email": user.email})
    unknown = client.post(FORGOT, json={"email": "inconnu@exemple.gn"})
    assert (known.status_code, known.content) == (unknown.status_code, unknown.content)
    assert [m.to for m in mailbox.deliver()] == [user.email]


def test_compte_desactive_ne_recoit_rien(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox, db: Session
) -> None:
    user = make_user()
    db.get_one(User, user.id).is_active = False
    db.commit()
    mailbox.deliver()
    OUTBOX.clear()
    assert client.post(FORGOT, json={"email": user.email}).status_code == 202
    assert mailbox.deliver() == []


def test_lien_expire_refuse(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox, db: Session
) -> None:
    user = make_user()
    token = _reset_token(client, mailbox, user)
    db.execute(
        update(EmailToken)
        .where(EmailToken.user_id == user.id)
        .values(expires_at=utcnow() - timedelta(seconds=1))
    )
    db.commit()
    response = client.post(RESET, json={"token": token, "new_password": NEW_PASSWORD})
    assert response.status_code == 400


def test_nouvelle_demande_invalide_le_lien_precedent(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox
) -> None:
    user = make_user()
    first = _reset_token(client, mailbox, user)
    second = _reset_token(client, mailbox, user)
    assert first != second
    assert (
        client.post(RESET, json={"token": first, "new_password": NEW_PASSWORD}).status_code == 400
    )
    assert (
        client.post(RESET, json={"token": second, "new_password": NEW_PASSWORD}).status_code == 204
    )


def test_mot_de_passe_faible_ne_consomme_pas_le_lien(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox
) -> None:
    user = make_user()
    token = _reset_token(client, mailbox, user)
    weak = client.post(RESET, json={"token": token, "new_password": "court"})
    assert weak.status_code == 422
    assert (
        client.post(RESET, json={"token": token, "new_password": NEW_PASSWORD}).status_code == 204
    )


def test_reinitialisation_leve_le_verrouillage(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox
) -> None:
    user = make_user()
    for _ in range(get_settings().login_max_failures):
        client.post("/api/v1/auth/login", json={"email": user.email, "password": "mauvais"})
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": user.password}
        ).status_code
        == 423
    )
    token = _reset_token(client, mailbox, user)
    assert (
        client.post(RESET, json={"token": token, "new_password": NEW_PASSWORD}).status_code == 204
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": NEW_PASSWORD}
        ).status_code
        == 200
    )


def test_quota_d_emails_par_compte(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox
) -> None:
    user = make_user()
    mailbox.deliver()
    OUTBOX.clear()
    limit = get_settings().account_emails_per_hour
    for _ in range(limit + 2):
        assert client.post(FORGOT, json={"email": user.email}).status_code == 202
    assert len(mailbox.deliver()) == limit


def test_file_d_attente_injoignable_renvoie_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise RedisConnectionError("injoignable")

    monkeypatch.setattr(tasks.request_password_reset, "send", broken)
    response = client.post(FORGOT, json={"email": "quelqu-un@exemple.gn"})
    assert response.status_code == 503
    assert response.json()["code"] == "service_indisponible"


def test_changement_de_mot_de_passe_notifie(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox
) -> None:
    user = make_user()
    response = client.post(
        "/api/v1/auth/password",
        headers=user.headers(client),
        json={"current_password": user.password, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200
    assert mailbox.last_to(user.email).subject == "Votre mot de passe Kora Finance a été modifié"


# --- Vérification de l'adresse


def _me(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    body: dict[str, object] = client.get("/api/v1/auth/me", headers=headers).json()
    return body


def test_inscription_envoie_la_verification(client: TestClient, mailbox: Mailbox) -> None:
    password = "Mot-de-passe-solide-2026"
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "nouveau@exemple.gn", "password": password, "full_name": "Fanta Camara"},
    )
    assert registered.status_code == 201
    user = UserFixture(id=registered.json()["id"], email="nouveau@exemple.gn", password=password)
    headers = user.headers(client)
    assert _me(client, headers)["email_verified"] is False
    email = mailbox.last_to(user.email)
    assert email.subject == "Confirmez votre adresse email Kora Finance"
    token = _token(email.text, "verification-email")

    verify = "/api/v1/auth/email/verify"
    assert client.post(verify, json={"token": token}).status_code == 204
    assert _me(client, headers)["email_verified"] is True
    # Double clic sur le lien : toujours un succès.
    assert client.post(verify, json={"token": token}).status_code == 204
    assert client.post(verify, json={"token": "inconnu"}).status_code == 400


def test_email_en_anglais_pour_un_compte_anglophone(client: TestClient, mailbox: Mailbox) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "english@exemple.gn",
            "password": "Mot-de-passe-solide-2026",
            "full_name": "Mamadou Bah",
            "locale": "en",
        },
    )
    assert response.status_code == 201
    email = mailbox.last_to("english@exemple.gn")
    assert email.subject == "Confirm your Kora Finance email address"
    assert "/en/verification-email?jeton=" in email.text


def test_renvoi_de_la_verification_et_quota(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox
) -> None:
    user = make_user()
    headers = user.headers(client)
    mailbox.deliver()
    OUTBOX.clear()
    resend = "/api/v1/auth/email/verification"
    limit = get_settings().account_emails_per_hour
    for _ in range(limit):
        assert client.post(resend, headers=headers).status_code == 202
    blocked = client.post(resend, headers=headers)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    sent = mailbox.deliver()
    assert len(sent) == limit
    # Seul le dernier lien est valable.
    tokens = [_token(m.text, "verification-email") for m in sent]
    verify = "/api/v1/auth/email/verify"
    assert client.post(verify, json={"token": tokens[0]}).status_code == 400
    assert client.post(verify, json={"token": tokens[-1]}).status_code == 204


def test_renvoi_sans_effet_si_deja_verifiee(
    client: TestClient, make_user: MakeUser, mailbox: Mailbox
) -> None:
    user = make_user(verified=True)
    mailbox.deliver()
    OUTBOX.clear()
    assert (
        client.post("/api/v1/auth/email/verification", headers=user.headers(client)).status_code
        == 202
    )
    assert mailbox.deliver() == []
