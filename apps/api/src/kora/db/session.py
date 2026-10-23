"""Moteur et sessions SQLAlchemy (synchrones, exécutées dans le threadpool de FastAPI)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from kora.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        str(get_settings().database_url),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
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
