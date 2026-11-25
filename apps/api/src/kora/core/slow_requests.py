"""Journal des requêtes lentes (diagnostic de performance en production).

Middleware ASGI pur : une ligne JSON par requête dépassant `slow_request_ms`,
avec le gabarit de route (jamais le chemin brut, la chaîne de requête ni les
en-têtes : aucun identifiant ni jeton dans les journaux), la méthode, le statut,
la durée et l'état du pool de connexions PostgreSQL (attente de connexion).
"""

import logging
import re
import time

from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from kora.core.config import get_settings
from kora.db.session import get_engine

logger = logging.getLogger("kora.slow_requests")
UNKNOWN_ROUTE = "(route inconnue)"


_STATIC_SEGMENT = re.compile(r"^[a-z0-9_-]*$")


def _route_template(scope: Scope) -> str:
    """Gabarit complet, ex. `/api/v1/companies/{company_id}/dashboard`.

    La route retenue (`scope["route"]`) porte un gabarit relatif à son routeur
    monté ; le préfixe est repris du chemin réel, segment par segment, et
    seulement s'il est statique (aucun identifiant ne peut y figurer).
    """
    route = scope.get("route")
    template = getattr(route, "path", None) if isinstance(route, BaseRoute) else None
    if not isinstance(template, str):
        return UNKNOWN_ROUTE
    segments = str(scope.get("path", "")).split("/")
    prefix = segments[: max(len(segments) - template.count("/"), 0)]
    if all(_STATIC_SEGMENT.fullmatch(segment) for segment in prefix):
        return "/".join(prefix) + template
    return template


class SlowRequestMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000)
            if duration_ms >= get_settings().slow_request_ms:
                logger.warning(
                    "Requête lente",
                    extra={
                        "route": _route_template(scope),
                        "method": scope["method"],
                        "status": status,
                        "duration_ms": duration_ms,
                        "pool": get_engine().pool.status(),
                    },
                )
