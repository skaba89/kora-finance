# Commandes de développement Kora Finance. Tout s'exécute dans des conteneurs épinglés :
# seuls Docker et make sont nécessaires sur le poste.
SHELL := /bin/bash
.DEFAULT_GOAL := help
# Sous Windows, Git Bash (MSYSTEM défini) fournit id et bash ; PowerShell et cmd
# non. Dans ce cas on évite d'appeler id (erreurs CreateProcess bruyantes) et
# Compose applique ses valeurs par défaut ${KORA_UID:-1000}:${KORA_GID:-1000}.
ifeq ($(OS),Windows_NT)
ifeq ($(MSYSTEM),)
KORA_UID := 1000
KORA_GID := 1000
else
KORA_UID := $(shell id -u)
KORA_GID := $(shell id -g)
endif
else
KORA_UID := $(shell id -u)
KORA_GID := $(shell id -g)
endif
export KORA_UID
export KORA_GID

COMPOSE := docker compose
API := $(COMPOSE) run --rm api-tools
API_NODEPS := $(COMPOSE) run --rm --no-deps -T api-tools
WEB := $(COMPOSE) run --rm --no-deps web-tools

.PHONY: help env up down logs ps seed seed-reset \
        api-lint api-typecheck api-test api-lock api-audit permissions-doc migrate \
        web-install web-lint web-typecheck web-test web-build web-audit \
        contract e2e secrets-scan sbom check

help: ## Affiche cette aide
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

env: ## Crée .env avec des secrets aléatoires (une seule fois ; bash requis sous Windows -> Git Bash)
	@bash ./scripts/init-env.sh || { \
		echo "bash introuvable sur le PATH." ; \
		echo "  - Si .env existe déjà à la racine du dépôt : rien à faire, passez à make up." ; \
		echo "  - Sinon, sous Windows : ouvrir Git Bash et relancer make env (docs/DEMO.md §5)." ; \
		exit 1 ; }

up: ## Construit et démarre la pile complète (postgres, redis, migrations, api, worker, web)
ifeq ($(wildcard .env),)
up: env
endif
	$(COMPOSE) up -d --build --wait

down: ## Arrête la pile (conserve les données)
	$(COMPOSE) down

logs: ## Suit les journaux de la pile
	$(COMPOSE) logs -f --tail=100

ps: ## État des services
	$(COMPOSE) ps

migrate: ## Applique les migrations Alembic sur la base locale
	$(COMPOSE) run --rm migrate

seed: ## Charge le jeu de démonstration Djouma Distribution SARL (comptes, écritures, relevés)
	$(COMPOSE) exec api python -m kora.scripts.seed_demo

# La réinitialisation supprime le dossier en cascade (grand livre en ajout seul) : elle
# exige les droits du propriétaire du schéma, que le conteneur api ne porte pas
# volontairement (séparation runtime/DDL). Compose interpole ${KORA_DB_OWNER_PASSWORD}
# depuis le .env créé par « make env » — même commande que docs/DEMO.md §3.
seed-reset: ## Réinitialise puis recharge le jeu de démonstration
	$(COMPOSE) exec -e KORA_DATABASE_MIGRATION_URL="postgresql+psycopg://kora_owner:$${KORA_DB_OWNER_PASSWORD}@postgres:5432/kora" api python -m kora.scripts.seed_demo --reset

# --- Backend
api-lint: ## Ruff (lint + format)
	$(API) sh -c "ruff check . && ruff format --check ."

api-typecheck: ## mypy strict
	$(API) mypy

api-test: ## Tests pytest (vraie base kora_test)
	$(API) pytest --cov --cov-report=term-missing

api-lock: ## Régénère uv.lock après modification de pyproject.toml
	$(API) uv lock

api-audit: ## pip-audit sur l'environnement verrouillé (vulnérabilités connues, SCA)
	$(API_NODEPS) sh -c "HOME=/tmp UV_TOOL_DIR=/tmp/uv-tools uv tool run pip-audit --path /opt/venv/lib/python3.13/site-packages --desc off"

storage-check: ## Vérifie le stockage S3 de la pile (écriture, lecture, chiffrement, suppression)
	$(COMPOSE) run --rm --no-deps api python -m kora.scripts.check_storage

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

web-audit: ## npm audit : production sans tolérance, dev sans haut ni critique
	$(WEB) sh -c "npm audit --omit=dev --audit-level=low && npm audit --audit-level=high"

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

sbom: ## Génère les SBOM CycloneDX (API et Web) dans sbom/
	mkdir -p sbom
	$(API_NODEPS) sh -c "HOME=/tmp UV_TOOL_DIR=/tmp/uv-tools uv tool run cyclonedx-py environment --of JSON -o /repo/sbom/kora-api.json /opt/venv/bin/python"
	$(WEB) sh -c "npx --yes @cyclonedx/cyclonedx-npm --output-file /repo/sbom/kora-web.json --output-format JSON"

sca: api-audit web-audit sbom ## Analyse de composition logicielle (audits + SBOM)

check: api-lint api-typecheck api-test web-lint web-typecheck web-test contract ## Tout ce que la CI vérifie (hors E2E)
