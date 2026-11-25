"""Double authentification exigible pour l'administration plateforme."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kora.core.config import get_settings
from kora.models.common import utcnow
from kora.models.identity import User
from tests.conftest import UserFixture

DIRECTORY = "/api/v1/platform/module-clients"


def test_admin_sans_2fa_admis_tant_que_l_exigence_est_desactivee(
    client: TestClient, db: Session, make_user: Callable[..., UserFixture]
) -> None:
    assert get_settings().platform_admin_require_mfa is False
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    assert client.get(DIRECTORY, headers=admin.headers(client)).status_code == 200


def test_exigence_2fa_refuse_admin_sans_second_facteur(
    client: TestClient,
    db: Session,
    make_user: Callable[..., UserFixture],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "platform_admin_require_mfa", True)
    without_mfa, with_mfa = make_user(), make_user()
    for fixture in (without_mfa, with_mfa):
        db.get_one(User, fixture.id).is_platform_admin = True
    db.commit()
    # Jetons obtenus avant l'activation : le droit est relu en base à chaque requête.
    headers_without, headers_with = without_mfa.headers(client), with_mfa.headers(client)
    db.get_one(User, with_mfa.id).totp_enabled_at = utcnow()
    db.commit()

    refused = client.get(DIRECTORY, headers=headers_without)
    assert refused.status_code == 403
    assert "double authentification" in refused.json()["detail"].lower()
    assert client.get(DIRECTORY, headers=headers_with).status_code == 200
    # La désactivation du second facteur retire aussitôt l'accès plateforme.
    db.get_one(User, with_mfa.id).totp_enabled_at = None
    db.commit()
    assert client.get(DIRECTORY, headers=headers_with).status_code == 403
