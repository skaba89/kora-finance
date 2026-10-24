"""Fixtures partagées. Les tests s'exécutent contre un vrai PostgreSQL et un vrai Redis
(base `kora_test`), jamais contre des simulacres de base de données."""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dramatiq import Worker
from dramatiq.brokers.stub import StubBroker
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from kora.auth import service as auth_service
from kora.core.config import Environment, get_settings
from kora.core.redis import get_redis
from kora.db.session import get_sessionmaker
from kora.email.sender import OUTBOX, OutgoingEmail
from kora.main import create_app
from kora.models.common import utcnow
from kora.models.identity import User
from kora.worker.broker import broker

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


@pytest.fixture(autouse=True)
def _redis_vide() -> None:
    """Base Redis 15 dédiée aux tests : vidée avant chaque test (compteurs de débit…)."""
    get_redis().flushdb()


@pytest.fixture(autouse=True)
def _file_d_attente_vide() -> None:
    """Tâches et emails d'un test précédent ne fuient pas dans le suivant."""
    assert isinstance(broker, StubBroker)
    broker.flush_all()
    OUTBOX.clear()


class Mailbox:
    """Exécute les tâches en attente (worker réel sur le broker en mémoire) et donne
    accès aux emails « envoyés » par le backend de test."""

    def __init__(self, worker: Worker) -> None:
        self._worker = worker

    def deliver(self) -> list[OutgoingEmail]:
        assert isinstance(broker, StubBroker)
        # Les tâches peuvent en programmer d'autres (préparation → envoi) : on attend
        # que la file soit vide. Un échec fait échouer le test (pas de réessai d'attente).
        broker.join("default", timeout=10_000, fail_fast=True)
        self._worker.join()
        return list(OUTBOX)

    def last_to(self, email: str) -> OutgoingEmail:
        sent = [m for m in self.deliver() if m.to == email]
        assert sent, f"aucun email envoyé à {email}"
        return sent[-1]


@pytest.fixture
def mailbox() -> Iterator[Mailbox]:
    worker = Worker(broker, worker_timeout=50)
    worker.start()
    try:
        yield Mailbox(worker)
    finally:
        worker.stop()


@dataclass
class UserFixture:
    id: uuid.UUID
    email: str
    password: str

    def login(self, client: TestClient) -> dict[str, str]:
        response = client.post(
            "/api/v1/auth/login", json={"email": self.email, "password": self.password}
        )
        assert response.status_code == 200, response.text
        body: dict[str, str] = response.json()
        return body

    def headers(self, client: TestClient) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.login(client)['access_token']}"}


@pytest.fixture
def make_user(db: Session) -> Callable[..., UserFixture]:
    def factory(
        password: str = "Mot-de-passe-solide-2026", *, verified: bool = False, **kwargs: str
    ) -> UserFixture:
        email = kwargs.get("email", f"user-{uuid.uuid4().hex[:12]}@exemple.gn")
        user = auth_service.register(
            db,
            email=email,
            password=password,
            full_name=kwargs.get("full_name", "Aïssatou Diallo"),
            locale="fr",
            ctx=auth_service.RequestContext(),
        )
        if verified:
            db.get_one(User, user.id).email_verified_at = utcnow()
            db.commit()
        return UserFixture(id=user.id, email=user.email, password=password)

    return factory


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@dataclass
class CompanyFixture:
    id: uuid.UUID
    owner: UserFixture
    headers: dict[str, str]


@pytest.fixture
def make_company(
    client: TestClient, make_user: Callable[..., UserFixture]
) -> Callable[..., CompanyFixture]:
    """Crée un dossier via l'API ; le créateur en devient PME_DIRIGEANT."""

    def factory(owner: UserFixture | None = None, **fields: object) -> CompanyFixture:
        owner = owner or make_user()
        headers = owner.headers(client)
        body = {
            "legal_name": f"Société {uuid.uuid4().hex[:6]} SARL",
            "legal_form": "SARL",
            "first_fiscal_year": {"start_date": "2026-01-01", "end_date": "2026-12-31"},
            **fields,
        }
        response = client.post("/api/v1/companies", headers=headers, json=body)
        assert response.status_code == 201, response.text
        return CompanyFixture(id=uuid.UUID(response.json()["id"]), owner=owner, headers=headers)

    return factory
