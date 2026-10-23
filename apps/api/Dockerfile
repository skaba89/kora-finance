# syntax=docker/dockerfile:1.7
# Image de l'API et du worker Kora (même code, commandes différentes).

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /usr/local/bin/uv
WORKDIR /app

# --- Dépendances de production uniquement
FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# --- Outillage : tests, lint, typage (code monté en volume par docker compose)
FROM deps AS dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen
COPY . .

# --- Image d'exécution : pas d'uv, pas de dépendances de dev, utilisateur non root
FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH=/opt/venv/bin:$PATH
RUN groupadd --system --gid 10001 kora && useradd --system --uid 10001 --gid kora kora
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
USER kora
EXPOSE 8000
# Pas de --proxy-headers : uvicorn remplacerait l'IP client par X-Forwarded-For quel
# que soit l'émetteur. L'IP est déterminée par kora.core.client_ip selon le nombre de
# proxys de confiance (KORA_TRUSTED_PROXY_COUNT).
CMD ["uvicorn", "kora.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
