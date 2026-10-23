"""Point d'entrée de l'API Kora Finance."""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kora import __version__
from kora.api import health
from kora.api.v1 import auth
from kora.core.config import get_settings
from kora.core.errors import install_error_handlers
from kora.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    # La documentation interactive n'est pas exposée en production.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title="Kora Finance API",
        version=__version__,
        openapi_url="/api/openapi.json" if docs_enabled else None,
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url=None,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    install_error_handlers(app)
    app.include_router(health.router)

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(auth.router)
    app.include_router(api_v1)
    return app
