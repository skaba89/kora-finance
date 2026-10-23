"""Fixtures partagées. Les tests s'exécutent contre un vrai PostgreSQL et un vrai Redis
(base `kora_test`), jamais contre des simulacres de base de données."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from kora.core.config import Environment, get_settings
from kora.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    return Config(str(API_ROOT / "alembic.ini"))


@pytest.fixture(scope="session", autouse=True)
def _migrated_database() -> None:
    settings = get_settings()
    if settings.env != Environment.TEST:
        pytest.exit("Les tests exigent KORA_ENV=test (base dédiée).", returncode=2)
    command.upgrade(alembic_config(), "head")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
