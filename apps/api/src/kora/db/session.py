"""Moteur et sessions SQLAlchemy (synchrones, exécutées dans le threadpool de FastAPI)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from kora.core.config import Settings, get_settings


def _session_options(settings: Settings) -> str:
    """Options psycopg passées à chaque connexion du runtime (N-B6)."""
    parts = []
    if settings.statement_timeout_ms > 0:
        parts.append(f"-c statement_timeout={settings.statement_timeout_ms}")
    if settings.lock_timeout_ms > 0:
        parts.append(f"-c lock_timeout={settings.lock_timeout_ms}")
    return " ".join(parts)


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        str(settings.database_url),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args={"options": _session_options(settings)},
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Dépendance FastAPI : une session par requête, toujours fermée."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
