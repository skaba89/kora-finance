"""Notifications d'exploitation (KF-12) : destinataire, honnêteté, échappement."""

import pytest

from kora.core.config import get_settings
from kora.email import sender
from kora.scripts import notify


def test_alerte_envoyee_a_ladresse_dexploitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "alert_email", "ops@exemple.gn")
    assert notify.notify("Kora Finance : échec de kora-backup.service", "corps d'alerte")
    alerte = sender.OUTBOX[-1]
    assert alerte.to == "ops@exemple.gn"
    assert "kora-backup" in alerte.subject
    assert "corps d'alerte" in alerte.text


def test_alerte_html_echappe_le_corps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le corps d'alerte (noms d'unités, commandes) ne peut pas casser le HTML."""
    monkeypatch.setattr(get_settings(), "alert_email", "ops@exemple.gn")
    notify.notify("Sujet", "échec <kora-backup> & relance")
    assert "<kora-backup>" not in sender.OUTBOX[-1].html
    assert "&lt;kora-backup&gt;" in sender.OUTBOX[-1].html


def test_alerte_sans_destinataire_refusee(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "alert_email", None)
    assert not notify.notify("Sujet", "corps")
    assert sender.OUTBOX == []


def test_alerte_backend_desactive_refusee(monkeypatch: pytest.MonkeyPatch) -> None:
    """Honnêteté : avec l'envoi désactivé, ne pas prétendre avoir alerté."""
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_email", "ops@exemple.gn")
    monkeypatch.setattr(settings, "email_backend", "disabled")
    assert not notify.notify("Sujet", "corps")
    assert sender.OUTBOX == []


def test_usage_incomplet_refuse() -> None:
    with pytest.raises(SystemExit, match="Usage"):
        notify.main(["sujet-seul"])
