"""Double authentification TOTP : enrôlement, connexion, rejeu, codes de secours."""

from collections.abc import Callable
from datetime import timedelta

import pyotp
import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kora.core.config import get_settings
from kora.models.common import utcnow
from kora.models.identity import User
from tests.conftest import UserFixture

MakeUser = Callable[..., UserFixture]


class MfaUser:
    def __init__(self, user: UserFixture, secret: str, recovery_codes: list[str]) -> None:
        self.user = user
        self.secret = secret
        self.recovery_codes = recovery_codes

    def code(self) -> str:
        return pyotp.TOTP(self.secret).now()

    def start_login(self, client: TestClient) -> str:
        response = client.post(
            "/api/v1/auth/login", json={"email": self.user.email, "password": self.user.password}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "mfa_required"
        assert "access_token" not in body
        token: str = body["mfa_token"]
        return token


def _verify(client: TestClient, mfa_token: str, code: str) -> int:
    return client.post(
        "/api/v1/auth/mfa/verify", json={"mfa_token": mfa_token, "code": code}
    ).status_code


@pytest.fixture
def mfa_user(client: TestClient, make_user: MakeUser) -> MfaUser:
    user = make_user()
    headers = user.headers(client)
    setup = client.post("/api/v1/auth/mfa/setup", headers=headers).json()
    enabled = client.post(
        "/api/v1/auth/mfa/enable",
        headers=headers,
        json={"code": pyotp.TOTP(setup["secret"]).now()},
    )
    assert enabled.status_code == 200
    # Le code d'activation consomme le pas de temps courant : les tests avancent d'un pas.
    return MfaUser(user, setup["secret"], enabled.json()["recovery_codes"])


def test_nouveaux_defis_ne_remettent_pas_les_echecs_mfa_a_zero(
    client: TestClient, mfa_user: MfaUser, db: Session
) -> None:
    # Huit chiffres ne peuvent correspondre au TOTP à six chiffres ni à un secours.
    for _ in range(get_settings().login_max_failures):
        token = mfa_user.start_login(client)
        assert _verify(client, token, "99999999") == 401
    response = client.post(
        "/api/v1/auth/login",
        json={"email": mfa_user.user.email, "password": mfa_user.user.password},
    )
    assert response.status_code == 423
    db.expire_all()
    stored = db.get_one(User, mfa_user.user.id)
    assert stored.failed_login_count == 0
    assert stored.locked_until is not None
    assert stored.locked_until > utcnow()


@pytest.mark.parametrize("method", ["totp", "secours"])
def test_second_facteur_reussi_remet_le_compteur_a_zero(
    client: TestClient, mfa_user: MfaUser, db: Session, method: str
) -> None:
    with time_machine.travel(utcnow() + timedelta(seconds=30)):
        token = mfa_user.start_login(client)
        for _ in range(get_settings().login_max_failures - 1):
            assert _verify(client, token, "99999999") == 401
        code = mfa_user.code() if method == "totp" else mfa_user.recovery_codes[0]
        assert _verify(client, token, code) == 200
        db.expire_all()
        assert db.get_one(User, mfa_user.user.id).failed_login_count == 0


def test_enrolement_fournit_secret_uri_et_qr(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    user = make_user()
    response = client.post("/api/v1/auth/mfa/setup", headers=user.headers(client))
    assert response.status_code == 200
    body = response.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/Kora%20Finance:")
    assert body["qr_svg_data_uri"].startswith("data:image/svg+xml")

    stored = db.get(User, user.id)
    assert stored is not None
    assert stored.totp_secret_encrypted is not None
    assert body["secret"].encode() not in stored.totp_secret_encrypted
    assert stored.totp_enabled_at is None  # pas actif avant confirmation


def test_activation_refuse_un_code_errone(client: TestClient, make_user: MakeUser) -> None:
    user = make_user()
    headers = user.headers(client)
    client.post("/api/v1/auth/mfa/setup", headers=headers)
    response = client.post("/api/v1/auth/mfa/enable", headers=headers, json={"code": "000000"})
    assert response.status_code == 401
    assert response.json()["code"] == "code_mfa_invalide"


def test_activation_renvoie_dix_codes_de_secours(mfa_user: MfaUser, client: TestClient) -> None:
    assert len(mfa_user.recovery_codes) == 10
    assert len(set(mfa_user.recovery_codes)) == 10
    # Le mot de passe seul ne donne plus de jeton d'accès.
    mfa_user.start_login(client)


def test_connexion_en_deux_etapes(mfa_user: MfaUser, client: TestClient) -> None:
    with time_machine.travel(utcnow() + timedelta(seconds=30)):
        token = mfa_user.start_login(client)
        response = client.post(
            "/api/v1/auth/mfa/verify", json={"mfa_token": token, "code": mfa_user.code()}
        )
        assert response.status_code == 200
        access = response.json()["access_token"]
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert me.json()["mfa_enabled"] is True


def test_un_code_totp_ne_peut_pas_etre_rejoue(mfa_user: MfaUser, client: TestClient) -> None:
    with time_machine.travel(utcnow() + timedelta(seconds=30)):
        code = mfa_user.code()
        assert _verify(client, mfa_user.start_login(client), code) == 200
        assert _verify(client, mfa_user.start_login(client), code) == 401


def test_code_de_secours_utilisable_une_seule_fois(mfa_user: MfaUser, client: TestClient) -> None:
    recovery = mfa_user.recovery_codes[0]
    assert _verify(client, mfa_user.start_login(client), recovery) == 200
    assert _verify(client, mfa_user.start_login(client), recovery) == 401
    # Saisie tolérante : minuscules et sans tirets.
    other = mfa_user.recovery_codes[1].replace("-", "").lower()
    assert _verify(client, mfa_user.start_login(client), other) == 200


def test_codes_errones_verrouillent_le_compte(mfa_user: MfaUser, client: TestClient) -> None:
    token = mfa_user.start_login(client)
    for _ in range(get_settings().login_max_failures):
        assert _verify(client, token, "000000") == 401
    with time_machine.travel(utcnow() + timedelta(seconds=30)):
        assert _verify(client, token, mfa_user.code()) == 423


def test_jeton_de_defi_expire(mfa_user: MfaUser, client: TestClient) -> None:
    token = mfa_user.start_login(client)
    ttl = get_settings().mfa_challenge_ttl_seconds
    with time_machine.travel(utcnow() + timedelta(seconds=ttl + 60)):
        assert _verify(client, token, mfa_user.code()) == 401


def test_jeton_d_acces_refuse_comme_jeton_de_defi(
    mfa_user: MfaUser, client: TestClient, make_user: MakeUser
) -> None:
    other_access = make_user().login(client)["access_token"]
    with time_machine.travel(utcnow() + timedelta(seconds=30)):
        assert _verify(client, other_access, mfa_user.code()) == 401


def _session_after_mfa(mfa_user: MfaUser, client: TestClient) -> dict[str, str]:
    token = mfa_user.start_login(client)
    response = client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": token, "code": mfa_user.recovery_codes.pop()},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_desactivation_exige_mot_de_passe_et_code(mfa_user: MfaUser, client: TestClient) -> None:
    headers = _session_after_mfa(mfa_user, client)
    with time_machine.travel(utcnow() + timedelta(seconds=30)):
        refused = client.post(
            "/api/v1/auth/mfa/disable",
            headers=headers,
            json={"password": "Pas-le-bon-mdp-123", "code": mfa_user.code()},
        )
        assert refused.status_code == 401
        response = client.post(
            "/api/v1/auth/mfa/disable",
            headers=headers,
            json={"password": mfa_user.user.password, "code": mfa_user.code()},
        )
        assert response.status_code == 204
        # Toutes les sessions sont fermées, et la connexion redevient en une étape.
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
        assert mfa_user.user.login(client)["status"] == "authenticated"


def test_regeneration_invalide_les_anciens_codes(mfa_user: MfaUser, client: TestClient) -> None:
    headers = _session_after_mfa(mfa_user, client)
    old_code = mfa_user.recovery_codes[0]
    with time_machine.travel(utcnow() + timedelta(seconds=30)):
        response = client.post(
            "/api/v1/auth/mfa/recovery-codes",
            headers=headers,
            json={"password": mfa_user.user.password, "code": mfa_user.code()},
        )
    assert response.status_code == 200
    assert len(response.json()["recovery_codes"]) == 10
    assert _verify(client, mfa_user.start_login(client), old_code) == 401


def test_enrolement_impossible_si_deja_active(mfa_user: MfaUser, client: TestClient) -> None:
    headers = _session_after_mfa(mfa_user, client)
    assert client.post("/api/v1/auth/mfa/setup", headers=headers).status_code == 409
