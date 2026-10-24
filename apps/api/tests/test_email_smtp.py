"""Envoi SMTP réel contre Mailpit, et garde-fous de configuration des emails."""

import json
import os
import smtplib
import urllib.parse
import urllib.request
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from kora.core.config import Environment, Settings, get_settings
from kora.email import sender, templates

SMTP = os.environ.get("KORA_TEST_MAILPIT_SMTP")
API = os.environ.get("KORA_TEST_MAILPIT_API")


@pytest.fixture
def smtp_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    # Pas de saut silencieux : sans Mailpit (service compose), le test échoue.
    assert SMTP, "KORA_TEST_MAILPIT_SMTP doit être défini (make api-test)"
    host, port = SMTP.split(":")
    settings = get_settings()
    for field, value in {
        "email_backend": "smtp",
        "smtp_host": host,
        "smtp_port": int(port),
        "smtp_security": "none",
        "smtp_username": "kora",
    }.items():
        monkeypatch.setattr(settings, field, value)
    return settings


def _search(to: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"query": f'to:"{to}"'})
    with urllib.request.urlopen(f"{API}/api/v1/search?{query}", timeout=5) as response:  # noqa: S310 (URL de test)
        messages: list[dict[str, Any]] = json.load(response)["messages"]
        return messages


def test_envoi_smtp_reel(smtp_settings: Settings) -> None:
    to = f"smtp-{uuid.uuid4().hex[:8]}@exemple.gn"
    email = templates.render(
        "password_reset", "fr", to=to, url="https://kora.test/fr/x?jeton=abc", name="Awa", ttl=60
    )
    sender.send(email)
    [received] = _search(to)
    assert received["Subject"] == email.subject
    assert received["From"]["Address"] == "no-reply@kora.local"
    with urllib.request.urlopen(f"{API}/api/v1/message/{received['ID']}", timeout=5) as response:  # noqa: S310
        detail = json.load(response)
    assert "jeton=abc" in detail["Text"]
    assert "jeton=abc" in detail["HTML"]


def test_starttls_exige_est_refuse_par_un_serveur_sans_tls(
    smtp_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Le chiffrement exigé n'est jamais abandonné en silence : l'envoi échoue (et le
    # worker réessaiera), aucun email ne part en clair.
    monkeypatch.setattr(smtp_settings, "smtp_security", "starttls")
    to = f"tls-{uuid.uuid4().hex[:8]}@exemple.gn"
    with pytest.raises(smtplib.SMTPNotSupportedError):
        sender.send(templates.render("password_changed", "fr", to=to, name="Awa"))
    assert _search(to) == []


def _settings(**overrides: object) -> Settings:
    base = get_settings().model_dump()
    return Settings.model_validate({**base, **overrides})


def test_boite_en_memoire_reservee_aux_tests() -> None:
    with pytest.raises(ValidationError, match="réservé aux tests"):
        _settings(env=Environment.LOCAL, email_backend="memory")


def test_production_exige_le_chiffrement_smtp_et_https() -> None:
    common = {"env": Environment.PRODUCTION, "email_backend": "smtp"}
    with pytest.raises(ValidationError, match="SMTP_SECURITY"):
        _settings(**common, smtp_security="none", web_public_url="https://app.kora.gn")
    with pytest.raises(ValidationError, match="https"):
        _settings(**common, smtp_security="tls", web_public_url="http://app.kora.gn")
    ok = _settings(**common, smtp_security="tls", web_public_url="https://app.kora.gn/")
    assert ok.web_public_url == "https://app.kora.gn"
