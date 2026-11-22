"""Chiffrement symétrique des données sensibles au repos (Fernet, rotation de clés)."""

from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class EncryptionSettings(BaseSettings):
    """Configuration minimale commune au runtime et aux sauvegardes isolées."""

    model_config = SettingsConfigDict(env_prefix="KORA_", extra="ignore")
    encryption_keys: SecretStr


@lru_cache
def _cipher() -> MultiFernet:
    keys = [k.strip() for k in EncryptionSettings().encryption_keys.get_secret_value().split(",")]
    if not keys or not all(keys):
        raise RuntimeError("KORA_ENCRYPTION_KEYS ne contient aucune clé valide")
    # La première clé chiffre ; toutes déchiffrent (rotation sans interruption).
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt(plaintext: str) -> bytes:
    return _cipher().encrypt(plaintext.encode())


def decrypt(token: bytes) -> str:
    return _cipher().decrypt(token).decode()


def encrypt_bytes(plaintext: bytes) -> bytes:
    return _cipher().encrypt(plaintext)


def decrypt_bytes(token: bytes) -> bytes:
    return _cipher().decrypt(token)
