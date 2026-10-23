"""Configuration de l'application, lue exclusivement depuis l'environnement.

Aucune valeur secrète n'a de défaut : si une variable manque, le démarrage échoue.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr
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

    # --- Authentification
    # Clé HMAC des JWT : au moins 256 bits d'entropie (64 caractères hexadécimaux).
    jwt_secret: SecretStr = Field(min_length=64)
    jwt_issuer: str = "kora-finance"
    jwt_audience: str = "kora-finance-api"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    # Délai pendant lequel un refresh token déjà consommé est encore accepté : des
    # requêtes parallèles d'un même navigateur (préchargements, onglets) présentent le
    # même jeton. Au-delà, la réutilisation est traitée comme un vol (famille révoquée).
    refresh_reuse_grace_seconds: int = Field(default=20, ge=0, le=60)
    mfa_challenge_ttl_seconds: int = Field(default=300, ge=60, le=900)
    # Verrouillage du compte après N échecs consécutifs.
    login_max_failures: int = Field(default=5, ge=3, le=20)
    login_lockout_seconds: int = Field(default=900, ge=60)
    # Limitation de débit des routes d'authentification, par adresse IP.
    auth_rate_limit_per_minute: int = Field(default=20, ge=1)
    # Nombre de proxys de confiance devant l'API (pour lire l'IP client réelle).
    trusted_proxy_count: int = Field(default=0, ge=0, le=5)

    # Clé de chiffrement des données sensibles au repos (secrets TOTP…) : clé Fernet
    # (32 octets en base64 url-safe). Plusieurs clés séparées par des virgules :
    # la première chiffre, toutes déchiffrent (rotation).
    encryption_keys: SecretStr

    @property
    def is_production(self) -> bool:
        return self.env in (Environment.STAGING, Environment.PRODUCTION)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # valeurs fournies par l'environnement
