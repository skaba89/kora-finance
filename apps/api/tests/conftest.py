"""Fixtures partagées. Les tests s'exécutent contre un vrai PostgreSQL et un vrai Redis
(base `kora_test`), jamais contre des simulacres de base de données."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from kora.core.config import Environment, get_settings
from kora.db.session import get_sessionmaker
from kora.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    return Config(str(API_ROOT / "alembic.ini"))


@pytest.fixture(scope="session", autouse=True)
def _migrated_database() -> None:
    settings = get_settings()
    if settings.env != Environment.TEST:
        pytest.exit("Les tests exigent KORA_ENV=test (base dédiée).", returncode=2)
    # Base repartie de zéro à chaque session : le journal d'audit est en ajout seul,
    # on ne peut pas le vider autrement.
    command.downgrade(alembic_config(), "base")
    command.upgrade(alembic_config(), "head")


@pytest.fixture
def db() -> Iterator[Session]:
    """Session avec le rôle applicatif (kora_app, soumis à la RLS)."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="session")
def owner_engine() -> Iterator[Engine]:
    """Connexion propriétaire du schéma : réservée aux tests d'attaque (falsification…)."""
    engine = create_engine(str(get_settings().database_migration_url))
    yield engine
    engine.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
