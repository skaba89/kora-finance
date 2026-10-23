# Journal de travail Kora Finance

Entrées datées, les plus récentes en haut. Chaque session y note ce qui a été fait,
vérifié, et ce qui reste.

## 2026-10-23 — Audit initial + phase 0 (fondations du dépôt)

**Audit.** Aucun code Kora Finance préexistant sur la machine. Seul projet présent :
`~/gestion-scolaire-pro` (ERP scolaire, autre produit). Ses modèles de socle (RLS,
JWT + révocation, idempotence, stockage) serviront d'inspiration en phase 1, sans
copier-coller ; ses passerelles de paiement utilisent des `float` → non réutilisables.

**Plan** par phases validé par l'utilisateur (`docs/PLAN.md`).

**Décision utilisateur** : Next.js 16 au lieu de 14 (Next 14 sans correctif de sécurité
depuis le 2025-12-11).

**Livré (phase 0)**
- Monorepo `apps/api` (FastAPI, SQLAlchemy 2.1 sync, Alembic, Pydantic 2.14, Dramatiq)
  et `apps/web` (Next 16.4.2, React 19.3, Tailwind 4.3, shadcn/ui radix-nova, TS strict).
- `docker-compose.yml` : postgres, redis, migrate (one-shot), api, worker, web ;
  profils `tools` et `e2e`. Ports sur 127.0.0.1 uniquement. Images non root.
- Rôles PostgreSQL `kora_owner` (migrations) / `kora_app` (NOBYPASSRLS, sans DDL),
  bases `kora` et `kora_test` (`infra/postgres/init-roles.sh`).
- Sondes `/health/live` et `/health/ready` (base + Redis, 503 si dépendance KO) ;
  page d'accueil qui affiche le statut réel de l'API ; tâche worker `ping`.
- Contrat OpenAPI committé + types TS générés, vérifiés par `make contract`.
- Garde-fous AST : `create_all()` et SQL interpolé interdits.
- CI GitHub Actions (`.github/workflows/ci.yml`) : gitleaks, API, web, contrat, E2E,
  job agrégateur « Résultat ». Actions épinglées par SHA.
- `CLAUDE.md`, `docs/CAHIER_DES_CHARGES.md`, `docs/PLAN.md`, `README.md`.

**Vérifié**
- `make check` → code 0 : ruff OK, mypy strict OK, 22 tests pytest (couverture 96 %),
  ESLint OK, `tsc` OK, 7 tests Vitest, contrat à jour.
- `make up` → les 6 services sains ; web → API → PostgreSQL + Redis vérifié ; une tâche
  envoyée depuis l'API est traitée par le worker (log `ping reçu`).
- `make e2e` → 2/2 Playwright (Chromium desktop + Pixel 5).
- Dans une copie jetable avec commit : test cassé → `make api-test` échoue ; API modifiée
  sans régénération → `make contract` échoue ; secret committé → gitleaks échoue.
- `actionlint` sur le workflow : aucune erreur.

**Non vérifié / reste à faire par l'utilisateur**
- La CI n'a jamais tourné sur GitHub : le dépôt n'a ni commit ni remote. Après le
  premier push, activer la protection de branche sur `main` en exigeant le statut
  « CI / Résultat » (c'est ce qui bloque réellement une PR).

**Incidents rencontrés (pour mémoire)**
- `@types/node@20` (choisi par create-next-app) incompatible avec Vitest 5 → `@types/node@24`.
- Starlette déprécie `httpx` pour son TestClient → `httpx2` (pydantic/httpx2).
- shadcn 4.22 utilise le paquet `cn` (publié par shadcn) au lieu de clsx + tailwind-merge.
- `UID` est en lecture seule dans bash → variables `KORA_UID` / `KORA_GID`.
- `make` installé sur la machine via apt (absent auparavant).

**Prochaine étape** : phase 1 (socle). Commencer par le modèle tenants/memberships/RBAC
et la RLS, puis l'auth, puis l'audit chaîné.
