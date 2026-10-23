"""Hachage des mots de passe (argon2id) et politique de mot de passe."""

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 10
MAX_LENGTH = 128


@lru_cache
def _hasher() -> PasswordHasher:
    # Paramètres par défaut d'argon2-cffi : profil RFC 9106 « faible mémoire » (argon2id).
    return PasswordHasher()


@lru_cache
def _dummy_hash() -> str:
    return _hasher().hash("kora-mot-de-passe-factice-pour-temps-constant")


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Vérifie un mot de passe. Sans hash (utilisateur inconnu), vérifie un hash factice
    pour que le temps de réponse ne révèle pas l'existence du compte."""
    try:
        return _hasher().verify(password_hash or _dummy_hash(), password) and bool(password_hash)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher().check_needs_rehash(password_hash)


def password_policy_errors(password: str, *, email: str) -> list[str]:
    """Règles de mot de passe, messages en français. Liste vide = conforme."""
    errors: list[str] = []
    if len(password) < MIN_LENGTH:
        errors.append(f"Le mot de passe doit contenir au moins {MIN_LENGTH} caractères.")
    if len(password) > MAX_LENGTH:
        errors.append(f"Le mot de passe ne doit pas dépasser {MAX_LENGTH} caractères.")
    if password.strip().lower() == email.strip().lower():
        errors.append("Le mot de passe ne doit pas être identique à l'adresse email.")
    if len(set(password)) < 4:
        errors.append("Le mot de passe est trop répétitif.")
    return errors
