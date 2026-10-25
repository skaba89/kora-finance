"""Garde-fous de configuration : réglages dangereux refusés au démarrage en production."""

from typing import Any

import pytest
from pydantic import ValidationError

from kora.core.config import Environment, Settings, get_settings
from kora.email import sender

PRODUCTION: dict[str, Any] = {
    "env": Environment.PRODUCTION,
    "email_backend": "smtp",
    "smtp_security": "starttls",
    "web_public_url": "https://app.kora.example",
    "s3_endpoint_url": "https://s3.fournisseur.example",
}


def test_configuration_de_production_valide() -> None:
    settings = Settings(**PRODUCTION)
    assert settings.is_production


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"smtp_security": "none"}, "KORA_SMTP_SECURITY"),
        ({"web_public_url": "http://app.kora.example"}, "KORA_WEB_PUBLIC_URL"),
        ({"s3_endpoint_url": "http://storage:3900"}, "KORA_S3_ENDPOINT_URL"),
    ],
)
def test_reglages_non_chiffres_refuses_en_production(
    override: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(**{**PRODUCTION, **override})


def test_stockage_http_accepte_en_local() -> None:
    assert Settings(env=Environment.TEST, s3_endpoint_url="http://storage:3900").s3_bucket


def test_emails_desactives_acceptes_en_production() -> None:
    settings = Settings(**{**PRODUCTION, "email_backend": "disabled", "smtp_security": "none"})
    assert settings.email_backend == "disabled"


def test_email_non_envoye_mais_journalise(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(get_settings(), "email_backend", "disabled")
    sender.OUTBOX.clear()
    with caplog.at_level("WARNING", logger="kora.email.sender"):
        sender.send(
            sender.OutgoingEmail("awa@exemple.gn", "Réinitialisation", "lien", "<p>lien</p>")
        )
    assert sender.OUTBOX == []
    assert "envoi désactivé" in caplog.text
    assert "awa@exemple.gn" not in caplog.text
