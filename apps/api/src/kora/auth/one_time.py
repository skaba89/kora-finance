"""Jetons opaques à usage unique transmis par email : seule l'empreinte est stockée."""

import hashlib
import secrets


def new_token() -> tuple[str, str]:
    """Renvoie (jeton à transmettre, empreinte à stocker)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
