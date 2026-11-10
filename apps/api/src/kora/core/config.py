"""Configuration de l'application, lue exclusivement depuis l'environnement.

Aucune valeur secrète n'a de défaut : si une variable manque, le démarrage échoue.
"""

import os
from enum import StrEnum
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, ValidationError, model_validator
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

    # --- Emails transactionnels (SMTP générique : tout fournisseur compatible)
    # « memory » : boîte d'envoi en mémoire, réservée aux tests automatisés.
    # « disabled » : aucun envoi (fournisseur pas encore choisi) ; chaque email non envoyé
    # est journalisé et l'interface signale que l'envoi d'emails est inactif.
    email_backend: Literal["smtp", "memory", "disabled"] = "smtp"
    email_from: str = "Kora Finance <no-reply@kora.local>"
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    # starttls (port 587) ou tls implicite (port 465) ; « none » interdit en production.
    smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_timeout_seconds: int = Field(default=15, ge=1, le=120)
    # Destinataire des alertes d'exploitation (KF-12 : échec de sauvegarde, sonde
    # externe) — distinct des emails transactionnels des utilisateurs. Utilisé par
    # `python -m kora.scripts.notify` ; sans lui, les alertes restent journalisées.
    alert_email: str | None = None
    # URL publique du frontend, pour les liens des emails (sans barre finale).
    web_public_url: str = "http://localhost:3100"

    # Durées de validité des liens envoyés par email.
    password_reset_ttl_minutes: int = Field(default=60, ge=10, le=24 * 60)
    email_verification_ttl_hours: int = Field(default=48, ge=1, le=24 * 14)
    invitation_ttl_days: int = Field(default=7, ge=1, le=30)
    # Anti-abus : emails de réinitialisation et de vérification par compte et par heure,
    # invitations par dossier sur 24 heures, exports (PDF/Excel) par utilisateur et par
    # dossier par heure (KF-13 : chaque export est synchrone et coûteux).
    account_emails_per_hour: int = Field(default=3, ge=1)
    invitations_per_company_per_day: int = Field(default=20, ge=1)
    exports_per_user_per_hour: int = Field(default=30, ge=1)
    exports_per_company_per_hour: int = Field(default=120, ge=1)

    # --- Stockage des pièces justificatives (S3 compatible : Garage en local, fournisseur
    # S3 en production). Les objets sont chiffrés par l'application avant l'envoi.
    s3_endpoint_url: str
    s3_region: str = "garage"
    s3_bucket: str
    s3_access_key_id: str
    s3_secret_access_key: SecretStr
    s3_timeout_seconds: int = Field(default=20, ge=1, le=300)
    # Taille maximale d'une pièce (les photos sont réduites dans le navigateur avant envoi).
    attachment_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    attachments_per_entry: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def _check_settings(self) -> Self:
        self.web_public_url = self.web_public_url.rstrip("/")
        if self.email_backend == "memory" and self.env != Environment.TEST:
            raise ValueError("KORA_EMAIL_BACKEND=memory est réservé aux tests.")
        if self.is_production:
            if self.email_backend == "smtp" and self.smtp_security == "none":
                raise ValueError("KORA_SMTP_SECURITY=none est interdit en production.")
            if not self.web_public_url.startswith("https://"):
                raise ValueError("KORA_WEB_PUBLIC_URL doit être en https:// en production.")
            if not self.s3_endpoint_url.startswith("https://"):
                raise ValueError("KORA_S3_ENDPOINT_URL doit être en https:// en production.")
        return self

    @property
    def is_production(self) -> bool:
        return self.env in (Environment.STAGING, Environment.PRODUCTION)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # valeurs fournies par l'environnement


class BackupSettings(BaseSettings):
    """Stockage des sauvegardes : endpoint, bucket et identifiants S3 **dédiés**
    (KF-09), distincts de ceux des pièces justificatives. Lus uniquement par les
    outils de sauvegarde (`kora.scripts.backup`) ; l'API et le worker n'y ont
    jamais accès (le Compose ne leur transmet pas ces variables). La clé de
    sauvegarde ne doit porter aucun droit de suppression : la rétention est
    administrée côté fournisseur (cycle de vie / Object Lock)."""

    model_config = SettingsConfigDict(env_prefix="KORA_BACKUP_S3_", extra="ignore")

    endpoint_url: str
    region: str = "garage"
    bucket: str
    access_key_id: str
    secret_access_key: SecretStr
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    # Plafond mémoire d'une sauvegarde (KF-23) : contrôlé par stat() AVANT lecture du
    # fichier. Défaut aligné sur le budget du conteneur « backup » (512 Mo, KF-13) ;
    # à augmenter seulement si le budget du conteneur suit.
    max_bytes: int = Field(default=400 * 1024**2, ge=1024 * 1024)

    @model_validator(mode="after")
    def _check_backup_settings(self) -> Self:
        if os.environ.get("KORA_ENV") in (
            "staging",
            "production",
        ) and not self.endpoint_url.startswith("https://"):
            raise ValueError("KORA_BACKUP_S3_ENDPOINT_URL doit être en https:// en production.")
        return self


@lru_cache
def get_backup_settings() -> BackupSettings:
    return BackupSettings()


class BackupAdminSettings(BaseSettings):
    """Clé d'administration de la rétention des sauvegardes : **distincte** de la clé
    de sauvegarde et jamais déployée sur le VPS. Seule la purge manuelle
    (`kora.scripts.backup prune`) l'utilise, depuis un poste d'administration."""

    model_config = SettingsConfigDict(env_prefix="KORA_BACKUP_ADMIN_S3_", extra="ignore")

    access_key_id: str
    secret_access_key: SecretStr


def get_backup_admin_settings() -> BackupAdminSettings | None:
    """Renvoie None si la clé d'administration n'est pas fournie : l'absence de cette
    clé sur un serveur est un état normal (et souhaité) — la purge est alors refusée."""
    try:
        return BackupAdminSettings()
    except ValidationError:
        return None


class MigrationSettings(BaseSettings):
    """Configuration réservée au processus Alembic, sans secrets du runtime."""

    model_config = SettingsConfigDict(env_prefix="KORA_", extra="ignore")

    database_migration_url: PostgresDsn


@lru_cache
def get_migration_settings() -> MigrationSettings:
    return MigrationSettings()
