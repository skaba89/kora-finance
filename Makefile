# Commandes de développement Kora Finance. Tout s'exécute dans des conteneurs épinglés :
# seuls Docker et make sont nécessaires sur le poste.
SHELL := /bin/bash
.DEFAULT_GOAL := help
export KORA_UID := $(shell id -u)
export KORA_GID := $(shell id -g)

COMPOSE := docker compose
API := $(COMPOSE) run --rm api-tools
API_NODEPS := $(COMPOSE) run --rm --no-deps -T api-tools
WEB := $(COMPOSE) run --rm --no-deps web-tools

.PHONY: help env up down logs ps \
        api-lint api-typecheck api-test api-lock permissions-doc migrate \
        web-install web-lint web-typecheck web-test web-build \
        contract e2e secrets-scan check

help: ## Affiche cette aide
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

env: ## Crée .env avec des secrets aléatoires (une seule fois)
	@./scripts/init-env.sh

up: env ## Construit et démarre la pile complète (postgres, redis, migrations, api, worker, web)
	$(COMPOSE) up -d --build --wait

down: ## Arrête la pile (conserve les données)
	$(COMPOSE) down

logs: ## Suit les journaux de la pile
	$(COMPOSE) logs -f --tail=100

ps: ## État des services
	$(COMPOSE) ps

migrate: ## Applique les migrations Alembic sur la base locale
	$(COMPOSE) run --rm migrate

# --- Backend
api-lint: ## Ruff (lint + format)
	$(API) sh -c "ruff check . && ruff format --check ."

api-typecheck: ## mypy strict
	$(API) mypy

api-test: ## Tests pytest (vraie base kora_test)
	$(API) pytest --cov --cov-report=term-missing

api-lock: ## Régénère uv.lock après modification de pyproject.toml
	$(API) uv lock

permissions-doc: ## Régénère docs/PERMISSIONS.md depuis la matrice du code
	$(API_NODEPS) python -c "from kora.tenancy.permissions import render_markdown; print(render_markdown(), end='')" > docs/PERMISSIONS.md

# --- Frontend
web-install: ## npm ci
	$(WEB) npm ci --no-audit

web-lint: ## ESLint
	$(WEB) npm run lint

web-typecheck: ## TypeScript strict
	$(WEB) npm run typecheck

web-test: ## Tests unitaires Vitest
	$(WEB) npm test

web-build: ## Build de production Next.js
	$(WEB) npm run build

# --- Transverse
contract: ## Vérifie que openapi.json et les types TS du frontend sont à jour
	./scripts/check-contract.sh

# Toutes les requêtes E2E viennent d'une même IP : limite d'authentification relevée pour
# la suite (la limitation elle-même est testée côté API). Exportée pour chaque commande,
# sinon `compose run` recréerait l'API avec la valeur par défaut.
e2e: export KORA_AUTH_RATE_LIMIT_PER_MINUTE = 1000
e2e: env ## Tests de bout en bout Playwright contre la pile démarrée
	$(COMPOSE) up -d --build --wait
	$(COMPOSE) --profile e2e run --rm e2e

secrets-scan: ## Recherche de secrets dans le dépôt (gitleaks)
	docker run --rm -v "$(CURDIR)":/repo ghcr.io/gitleaks/gitleaks:v8.28.0 git /repo --redact -v

check: api-lint api-typecheck api-test web-lint web-typecheck web-test contract ## Tout ce que la CI vérifie (hors E2E)
