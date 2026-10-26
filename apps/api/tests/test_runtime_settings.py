"""Le runtime n'a plus besoin du compte propriétaire réservé aux migrations."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from kora.core.config import MigrationSettings, Settings

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
