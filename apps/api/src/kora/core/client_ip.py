"""Adresse IP du client, en ne faisant confiance qu'au nombre de proxys configuré."""

import ipaddress

from fastapi import Request

from kora.core.config import get_settings


def _valid_ip(value: str | None) -> str | None:
    """Ne renvoie que des adresses IP syntaxiquement valides (en-têtes forgés écartés)."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    proxies = get_settings().trusted_proxy_count
    if proxies > 0:
        forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",")]
        forwarded = [p for p in forwarded if p]
        # Chaque proxy de confiance ajoute une entrée à droite : l'IP client est
        # la N-ième en partant de la droite. Les entrées plus à gauche sont falsifiables.
        if len(forwarded) >= proxies:
            return _valid_ip(forwarded[-proxies])
    return _valid_ip(request.client.host if request.client else None)
