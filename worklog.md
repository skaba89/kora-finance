# Journal de travail Kora Finance

Entrées datées, les plus récentes en haut. Chaque session y note ce qui a été fait,
vérifié, et ce qui reste.

## 2026-10-23 — Phase 1 (socle)

Commits : `dac9685` (1a), `070ad3d` (1b), `796c2b6` (1c), `35262c0` (1d-1e), puis 1f (frontend).

**Livré**
- 1a — Identité et tenancy (users, firms, companies = tenants, memberships, affectations),
  contexte tenant RLS réappliqué à chaque transaction, journal d'audit chaîné SHA-256
  (par dossier + plateforme), ajout seul (trigger + REVOKE), vérificateur.
- 1b — Auth : argon2id, JWT d'accès 15 min (token_version), refresh tokens rotatifs avec
  révocation de famille (tolérance 20 s), verrouillage après 5 échecs (423), limitation
  de débit Redis par IP (429 ; 503 si Redis indisponible), format d'erreur commun.
- 1c — 2FA TOTP : enrôlement en deux temps, secret chiffré (Fernet), anti-rejeu,
  10 codes de secours, désactivation/régénération avec mot de passe + code.
- 1d — RBAC 7 rôles (matrice unique → `docs/PERMISSIONS.md` généré et vérifié),
  dossiers, membres (garde du dernier dirigeant), cabinets/affectations (API),
  exercices (sans chevauchement, ≤ 24 mois).
- 1e — Plan SYSCOHADA révisé préchargé (520 comptes, classes 1-8), sous-comptes,
  masquage ; taux de taxes en points de base, versionnés par date, « à vérifier DGI ».
- 1f — Frontend BFF : connexion/inscription/2FA, dossiers, tableau de bord de mise en
  route, fiche entreprise, exercices, plan comptable (recherche, pagination), taxes,
  utilisateurs, journal d'audit (vérification d'intégrité), sécurité du compte ;
  i18n fr/en ; PWA (manifeste, icônes, service worker, page hors connexion) ; CSP et
  en-têtes de sécurité.

**Vérifié**
- `make check` → code 0 : ruff, mypy strict, **182 tests pytest**, ESLint, tsc,
  26 tests Vitest, contrat d'API à jour.
- `make e2e` → **24/24** Playwright (desktop + mobile) : parcours complet dossier,
  droits du comptable, 2FA de bout en bout, redirections, 404 cross-tenant, cookies
  httpOnly, renouvellement de session, langue, PWA, aucune erreur console.
- Critères d'acceptation de la phase 1 :
  - isolation testée sur 100 % des routes `/companies/{id}/…` (test générique, 404) +
    RLS exigée sur toute table à `tenant_id` + tests IDOR ;
  - altération / suppression / troncature du journal d'audit détectées ;
  - verrouillage au 5ᵉ échec (mot de passe ou code 2FA) ;
  - matrice rôle × permission testée de bout en bout pour les 5 rôles de dossier.
- Historique git scanné par gitleaks : aucune fuite.

**Problèmes trouvés et corrigés en cours de route**
- CSP à nonce incompatible avec la coquille statique de Cache Components (JS bloqué) →
  CSP sans nonce, décision documentée.
- uvicorn `--proxy-headers --forwarded-allow-ips "*"` rendait l'IP client falsifiable →
  retiré.
- Requêtes parallèles avec le même refresh token → fenêtre de tolérance.
- FastAPI 0.162 imbrique les routeurs (`_IncludedRouter`) → registre public `ROUTERS`
  pour que les tests d'isolation ne soient jamais vides (test sentinelle).
- Connexion sur réseau lent : le champ « suivant » arrivait en streaming après le
  formulaire, qui pouvait être envoyé sans lui → formulaire rendu en un seul bloc.
- Revue visuelle : sur téléphone, le menu du dossier occupait tout le premier écran →
  barre horizontale défilante sous `md`.
- E2E : 3 exécutions consécutives à 24/24 après correction de courses dans les tests
  (navigation avant la fin d'une Server Action).

**Reste à faire — non livré en phase 1 (à traiter avant une mise en production)**
- **Emails** : vérification de l'adresse, *mot de passe oublié*, invitation d'une
  personne sans compte. Sans « mot de passe oublié », un utilisateur qui perd son mot
  de passe ne peut pas récupérer son compte. Nécessite un fournisseur d'email.
- **Écrans cabinet** : l'API cabinets/affectations existe, pas encore d'écran (phase 8).
- **Messages d'erreur de l'API en français uniquement** : un utilisateur en anglais voit
  les erreurs métier en français (traduire par `code` côté web ou localiser l'API).
- **Vérification quotidienne de la chaîne d'audit + ancrage externe des têtes** :
  vérification disponible à la demande (API + écran), pas encore planifiée.
- La CI n'a toujours pas tourné sur GitHub (pas de remote).
- Durée des tests API (~2 min 30) : surtout argon2 et la création de 520 comptes par
  dossier ; à optimiser si elle devient gênante.

**À valider par un expert-comptable guinéen** : plan SYSCOHADA préchargé (`apps/api/src/
kora/accounting/data/syscohada_revise_2017.csv`), formes juridiques, durée maximale
d'un exercice (24 mois), taux de TVA par défaut (18 %, comptes 4431/4452).

**Prochaine étape proposée** : sous-livrable 1g « emails » (mot de passe oublié,
vérification d'adresse, invitations), puis phase 2.

## 2026-10-23 — Audit initial + phase 0 (fondations du dépôt)

**Audit.** Aucun code Kora Finance préexistant : projet démarré de zéro.
Kora est un projet indépendant, sans lien avec les autres dépôts présents sur la machine.

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
