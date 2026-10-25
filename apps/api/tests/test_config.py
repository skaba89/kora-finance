"""Garde-fous de configuration : réglages dangereux refusés au démarrage en production."""

from typing import Any

import pytest
from pydantic import ValidationError

from kora.core.config import Environment, Settings

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
