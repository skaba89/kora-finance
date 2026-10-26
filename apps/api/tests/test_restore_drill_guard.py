"""Le scénario de restauration refuse les connexions hors du banc synthétique."""

from typing import Any

import pytest
from pydantic import PostgresDsn

from kora.core.config import Environment, Settings
from tests.restore_drill_support import assert_isolated


def _settings(**overrides: Any) -> Settings:
    return Settings.model_construct(
        **{
            "env": Environment.TEST,
            "database_url": PostgresDsn(
                "postgresql+psycopg://kora_app:fake@postgres-source/kora_drill"
            ),
            "s3_endpoint_url": "http://storage-source:3900",
            "s3_bucket": "kora-drill",
            **overrides,
        }
    )


@pytest.mark.parametrize("phase", ["seed", "archive"])
def test_source_synthetique_acceptee(monkeypatch: pytest.MonkeyPatch, phase: str) -> None:
    monkeypatch.setenv("KORA_RESTORE_DRILL", "synthetic-v1")
    assert_isolated(_settings(), phase)


@pytest.mark.parametrize(
    "overrides",
    [
        {"env": Environment.PRODUCTION},
        {"s3_bucket": "production"},
        {"s3_endpoint_url": "https://storage.example.com"},
        {"database_url": PostgresDsn("postgresql+psycopg://kora_app:fake@postgres-source/kora")},
        {
            "database_url": PostgresDsn(
                "postgresql+psycopg://kora_app:fake@external.example/kora_drill"
            )
        },
    ],
)
def test_environnement_externe_refuse(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object]
) -> None:
    monkeypatch.setenv("KORA_RESTORE_DRILL", "synthetic-v1")
    with pytest.raises(RuntimeError, match="refusé"):
        assert_isolated(_settings(**overrides), "seed")


def test_absence_de_marqueur_refusee(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KORA_RESTORE_DRILL", raising=False)
    with pytest.raises(RuntimeError, match="refusé"):
        assert_isolated(_settings(), "seed")


def test_recuperation_refuse_la_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KORA_RESTORE_DRILL", "synthetic-v1")
    with pytest.raises(RuntimeError, match="refusé"):
        assert_isolated(_settings(), "recover")
