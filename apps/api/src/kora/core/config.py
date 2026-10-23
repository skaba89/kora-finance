"""Configuration de l'application, lue exclusivement depuis l'environnement.

Aucune valeur secrète n'a de défaut : si une variable manque, le démarrage échoue.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KORA_", extra="ignore")

    env: Environment = Environment.LOCAL
    log_level: str = "INFO"

    # Rôle applicatif (NOBYPASSRLS, DML uniquement) : utilisé par l'API et le worker.
    database_url: PostgresDsn
    # Rôle propriétaire du schéma : utilisé uniquement par Alembic.
    database_migration_url: PostgresDsn
    redis_url: RedisDsn

    cors_origins: list[str] = Field(default_factory=list)

    @property
    def is_production(self) -> bool:
        return self.env in (Environment.STAGING, Environment.PRODUCTION)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # valeurs fournies par l'environnement
