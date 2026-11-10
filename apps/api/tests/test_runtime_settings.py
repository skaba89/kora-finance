"""Le runtime n'a plus besoin du compte propriétaire réservé aux migrations."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from kora.core.config import MigrationSettings, Settings, get_settings
from kora.db.session import _session_options

RUNTIME: dict[str, Any] = {
    "database_url": "postgresql+psycopg://runtime:local-only@localhost/kora_test",
    "redis_url": "redis://localhost/15",
    "jwt_secret": "x" * 64,
    "encryption_keys": "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=",
    "s3_endpoint_url": "http://localhost:3900",
    "s3_bucket": "test-only",
    "s3_access_key_id": "test-only",
    "s3_secret_access_key": "test-only",
}
API_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_demarre_sans_identifiant_de_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KORA_DATABASE_MIGRATION_URL", raising=False)
    settings = Settings(**RUNTIME)
    assert str(settings.database_url).endswith("/kora_test")
    assert "database_migration_url" not in settings.model_dump()


def test_runtime_n_ingere_pas_un_secret_de_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "KORA_DATABASE_MIGRATION_URL", "postgresql://owner:local-only@localhost/test"
    )
    assert "database_migration_url" not in Settings(**RUNTIME).model_dump()


def test_migration_refuse_de_demarrer_sans_son_identifiant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KORA_DATABASE_MIGRATION_URL", raising=False)
    with pytest.raises(ValidationError, match="database_migration_url"):
        MigrationSettings()


def test_migration_ne_depend_pas_des_secrets_du_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in RUNTIME:
        monkeypatch.delenv("KORA_" + name.upper(), raising=False)
    settings = MigrationSettings(
        database_migration_url="postgresql+psycopg://owner:local-only@localhost/kora_test"
    )
    assert set(settings.model_dump()) == {"database_migration_url"}


@pytest.mark.parametrize(
    "code", ["from kora.main import create_app; create_app()", "import kora.worker.tasks"]
)
def test_processus_runtime_sans_secret_proprietaire(code: str) -> None:
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(API_ROOT / "src"),
        "KORA_ENV": "test",
        "KORA_EMAIL_BACKEND": "memory",
        **{"KORA_" + name.upper(): str(value) for name, value in RUNTIME.items()},
    }
    result = subprocess.run(  # noqa: S603 (code fixe de la paramétrisation)
        [sys.executable, "-c", code],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_alembic_genere_le_schema_avec_seule_configuration_de_migration() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=API_ROOT,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(API_ROOT / "src"),
            "KORA_DATABASE_MIGRATION_URL": "postgresql+psycopg://owner:local-only@localhost/test",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE journal_entries" in result.stdout


def test_les_plafonds_de_session_sont_reglables(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(**RUNTIME)
    assert settings.statement_timeout_ms == 60_000
    assert settings.lock_timeout_ms == 5_000
    monkeypatch.setenv("KORA_STATEMENT_TIMEOUT_MS", "30000")
    monkeypatch.setenv("KORA_LOCK_TIMEOUT_MS", "2000")
    bounded = Settings(**RUNTIME)
    assert bounded.statement_timeout_ms == 30_000
    assert bounded.lock_timeout_ms == 2_000
    with pytest.raises(ValidationError):
        Settings(**{**RUNTIME, "statement_timeout_ms": -1})


def test_le_moteur_du_runtime_transmet_les_plafonds(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "statement_timeout=60000" in _session_options(Settings(**RUNTIME))
    assert "lock_timeout=5000" in _session_options(Settings(**RUNTIME))
    monkeypatch.setenv("KORA_STATEMENT_TIMEOUT_MS", "0")
    monkeypatch.setenv("KORA_LOCK_TIMEOUT_MS", "0")
    assert _session_options(Settings(**RUNTIME)) == ""


def test_une_requete_trop_longue_est_annulee(client: TestClient) -> None:
    # Le plafond s'applique réellement au rôle applicatif, pas seulement au mot.

    engine = create_engine(
        str(get_settings().database_url),
        connect_args={"options": "-c statement_timeout=100"},
    )
    try:
        with pytest.raises(DBAPIError, match="statement timeout"), engine.connect() as conn:
            conn.execute(text("SELECT pg_sleep(1)"))
    finally:
        # Destruction déterministe : une connexion oubliée au GC déclencherait une
        # ResourceWarning « unraisable » imputée au setup du test suivant.
        engine.dispose()
