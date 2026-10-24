# Kora Finance — instructions pour Claude Code

Plateforme SaaS de gestion financière et comptable pour les PME guinéennes et les
cabinets comptables : comptabilité SYSCOHADA révisé, rapprochement Mobile Money et
bancaire, états financiers prêts pour un dossier de crédit, assistance IA.
**Produit de production, pas une démo** : chaque livraison est complète, testée et sécurisée.

Journal daté des sessions : `worklog.md`. Le lire en début de session.

## État d'avancement

| Phase | Contenu | État |
|---|---|---|
| 0 | Fondations du dépôt : monorepo, Docker, CI, harnais de tests | ✅ livrée (2026-10-23) |
| 1 | Socle : auth, multi-tenant + RLS, RBAC, organisation, plan comptable, taxes, audit chaîné, PWA | ✅ livrée (2026-10-23) ; 1g emails ✅ (2026-10-24) — reste listé dans `worklog.md` |
| 2 | Comptabilité générale + états financiers | en cours : 2a saisie ✅, 2b balance et grand livre ✅, 2c lettrage ✅, 2d clôture ✅ (2026-10-24) ; 2e–2g à venir (`docs/PLAN.md`) |
| 3 | Trésorerie, Mobile Money, rapprochement | — |
| 4 | Ventes et achats | — |
| 5 | Import et migration | — |
| 6 | Dossier de financement partageable | — |
| 7 | Assistant IA | — |
| 8 | Espace cabinet et abonnements | — |

Le cahier des charges complet et les critères d'acceptation de chaque phase sont dans
`docs/PLAN.md`.

## Architecture

```
apps/api/      FastAPI + SQLAlchemy 2 (sync) + Alembic + Pydantic v2 — package `kora` (src/kora)
               └ worker Dramatiq dans le même code (src/kora/worker), même image Docker
apps/api/openapi.json         contrat d'API exporté (committé, vérifié en CI)
apps/web/      Next.js 16 App Router + TypeScript strict + Tailwind 4 + shadcn/ui (radix-nova)
apps/web/src/lib/api/schema.ts  types TS générés depuis openapi.json (ne pas éditer)
infra/postgres/init-roles.sh  rôles et bases PostgreSQL (local + CI)
scripts/       init-env.sh (secrets locaux), check-contract.sh
.github/workflows/ci.yml      CI : mêmes commandes `make` qu'en local
```

Pile locale (`docker-compose.yml`, ports sur 127.0.0.1 uniquement) :
postgres 16 (55432) · redis 7 (56379) · mailpit (UI 58025) · migrate (one-shot) · api (8100) ·
worker · web (3100).
Profils : `tools` (api-tools, web-tools), `e2e` (Playwright).

### Backend (`apps/api/src/kora`)

```
core/        config, erreurs {detail, code, errors}, crypto (Fernet), rate limit, IP client
db/          base, session, tenant.py (contexte RLS réappliqué à chaque transaction)
models/      identity (plateforme, sans RLS), organization, accounting, audit (tables tenant, RLS)
auth/        mots de passe argon2id, JWT, refresh tokens rotatifs, 2FA TOTP,
             recovery.py (mot de passe oublié, vérification d'adresse)
email/       envoi SMTP générique / boîte mémoire (tests), gabarits FR/EN, quotas Redis
tenancy/     rôles, matrice de permissions (source unique), résolution du rôle, dépendances
organization/ dossiers, membres, invitations, exercices, cabinets
accounting/  plan SYSCOHADA (data/*.csv), taux de taxes versionnés, paramétrage initial,
             journals.py (journaux par défaut), entries.py (écritures en partie double),
             reports.py (balance, grand livre : agrégats SQL sur écritures validées),
             lettering.py (lettrage des comptes de tiers, stocké hors des lignes immuables),
             closing.py (verrouillage de période, clôture, à-nouveaux, réouverture)
audit/       journal chaîné SHA-256 (écriture, vérification)
api/v1/      routes ; `ROUTERS` = registre parcouru par les tests d'isolation
worker/      acteurs Dramatiq (emails : préparation du jeton → deliver_email avec réessais)
```

Emails : jamais envoyés pendant une requête HTTP. L'API met une tâche en file
(`worker/enqueue.py`), le worker crée le jeton (empreinte SHA-256 en base) et envoie.
Tests : `KORA_EMAIL_BACKEND=memory` + fixture `mailbox` (worker réel sur StubBroker) ;
E2E : liens lus dans Mailpit (`emailLink` dans `e2e/helpers.ts`).

Route tenant = `/api/v1/companies/{company_id}/…` + paramètre typé `AccountsRead`,
`TaxesManage`… (`tenancy/deps.py`). `tests/test_isolation_tenants.py` vérifie
automatiquement toute nouvelle route ; `test_toute_table_avec_tenant_id_est_sous_rls`
exige la RLS sur toute nouvelle table portant un `tenant_id`.

### Frontend (`apps/web/src`) — BFF

Le navigateur ne voit jamais les jetons : cookies httpOnly `kora_at` / `kora_rt`, lus par
le serveur Next (proxy, Server Components, Server Actions) qui appelle l'API.

```
proxy.ts            CSP + en-têtes, renouvellement de session, garde des pages,
                    réécriture /x → /{lang}/x selon le cookie kora_locale
app/[lang]/(public) connexion, vérification 2FA, inscription
app/[lang]/(app)    dossiers, paramètres du dossier, journal d'audit, sécurité du compte
lib/dal.ts          lectures (API) ; lib/actions/*  Server Actions (mutations)
lib/i18n            fr.ts (référence) / en.ts (mêmes clés, vérifié par TypeScript)
public/sw.js        service worker : page hors connexion uniquement, rien d'authentifié en cache
```

## Commandes

Seuls Docker et `make` sont requis sur le poste (aucun Node ni Python local).

```bash
make env          # .env avec secrets aléatoires (une fois)
make up           # build + démarrage de toute la pile, attend les healthchecks
make check        # tout ce que la CI vérifie hors E2E
make api-test     # pytest contre une vraie base kora_test
make web-test     # vitest
make e2e          # Playwright (desktop + mobile) contre la pile démarrée
make contract     # échoue si openapi.json / schema.ts ne sont pas à jour
./scripts/check-contract.sh --write   # régénère le contrat après un changement d'API
make api-lock     # après modification de apps/api/pyproject.toml
```

## Règles non négociables

1. **Plan validé avant tout changement important.** Travailler phase par phase ; en fin
   de phase : CI verte, build OK, résumé livré/restant, `CLAUDE.md` + `worklog.md` à jour.
2. **Aucun raccourci silencieux.** Pas d'écran vide, pas de données fictives, pas de
   `except Exception: pass`. Si une fonctionnalité ne peut pas être terminée, le dire.
3. **Règle fiscale ou comptable incertaine** → la marquer « à valider par un
   expert-comptable guinéen », ne jamais l'inventer. Aucun taux codé en dur : valeurs
   paramétrables, datées, documentées « à vérifier auprès de la DGI ».
4. **Schéma = Alembic uniquement.** Jamais `create_all()` (garde-fou AST dans
   `tests/test_guardrails.py`). Ne jamais modifier une migration déjà mergée. Les
   migrations sont une étape distincte (service `migrate`), jamais au démarrage de l'API.
5. **SQL paramétré uniquement.** Jamais `text(f"…")`, `%` ou `.format()` (garde-fou AST).
6. **Montants = entiers** (`BIGINT`, unités mineures, devise sur chaque ligne ; GNF = 0
   décimale). Aucun `float` pour de l'argent, nulle part, y compris côté TypeScript
   (chaînes ou entiers, jamais d'arithmétique flottante).
7. **Isolation tenant** (à partir de la phase 1) : `tenant_id` sur chaque table métier,
   filtrage obligatoire dans la couche d'accès **et** politiques RLS PostgreSQL. Toute
   route tenant est couverte par la suite de tests cross-tenant.
8. **Rôles PostgreSQL** : `kora_app` (API/worker) est NOSUPERUSER, NOBYPASSRLS, sans DDL ;
   `kora_owner` exécute les migrations. Ne jamais faire tourner l'API avec `kora_owner`.
9. **Déploiement** : l'API ne doit pas être joignable directement depuis internet (seul
   le serveur web l'appelle) ; `KORA_PUBLIC_URL` en `https://` en production (cookies
   Secure). Exceptions gitleaks : `.gitleaks.toml` (mots de passe factices des tests).
10. **Secrets** : jamais dans le dépôt, jamais affichés. `.env` est généré localement
   (`make env`) ; gitleaks tourne en CI.
11. **Dépendances épinglées** à des versions exactes (uv.lock, package-lock + `save-exact`,
    images Docker taguées, actions GitHub par SHA). Vérifier la provenance de tout
    nouveau paquet avant de l'ajouter.
12. **Langue** : interface, messages d'erreur, noms de tests et documentation en français.

## Frontend : Next.js 16

Next 16.4 diffère de Next 14/15 (Cache Components activé, `connection()`, Partial
Prefetching…). **Lire la doc embarquée `apps/web/node_modules/next/dist/docs/` avant
d'écrire du code Next.** Points déjà rencontrés :
- avec `cacheComponents: true`, toute donnée dynamique doit être sous `<Suspense>` et
  appeler `await connection()` (ou une API de requête) pour ne pas être figée au build ;
- Vitest ne sait pas rendre les Server Components `async` : tester les composants
  synchrones en unitaire, les composants async en E2E ;
- `src/lib/api/client.ts` est `server-only` : l'URL interne de l'API ne fuit pas au navigateur.
- **Toute lecture de session/données (cookies, API) doit être sous `<Suspense>`** : sinon
  le build échoue (« blocking-prerender-dynamic »). Le layout d'un dossier encapsule déjà
  ses pages ; les autres pages encapsulent leur contenu.
- Langue : `await lang()` de `next/root-params` (Server Components). Indisponible dans
  les Server Actions → `actionDictionary()` (cookie). Liens internes **sans** préfixe de
  langue : le proxy réécrit.
- `usePathname()` renvoie le chemin réécrit : pour l'URL visible, lire `window.location`
  après hydratation (voir `components/nav-link.tsx`).
- Les tests E2E tournent sur desktop et mobile (Pixel 5) : une colonne masquée sur
  mobile (`hidden sm:table-cell`) n'est pas visible pour Playwright.
- Après une navigation client, Next 16 **garde la page précédente dans le DOM (masquée)** :
  `getByLabel` peut alors trouver deux champs ; préférer `getByRole`, qui ignore le masqué.
- `crypto.randomUUID()` n'existe qu'en HTTPS/localhost (absent en E2E sur http://web:3000) :
  utiliser `uuidV4()` de `lib/uuid.ts`.
- Tableaux larges (balance, grand livre) : fiches `sm:hidden` sur téléphone + tableau
  `hidden sm:table`. En E2E, `getByRole` ignore la variante masquée (rôle `row` sur
  ordinateur, `listitem` sur mobile, voir `e2e/etats.spec.ts`).
- Montants affichés avec des espaces fines insécables (fr-FR) : dans une regex, `\s`.
- Montants : chaînes de chiffres (unités mineures) de bout en bout ; saisie par
  `parseAmount`, sommes en BigInt (`lib/amounts.ts`), affichage par `formatMoney`.

## Décisions d'architecture

| Date | Décision | Raison |
|---|---|---|
| 2026-10-23 | **Next.js 16** au lieu de 14 (validé par l'utilisateur) | Next 14 sans correctif de sécurité depuis déc. 2025 |
| 2026-10-23 | SQLAlchemy **synchrone** (psycopg 3), threadpool FastAPI | Transactions comptables (`SELECT … FOR UPDATE`, `SET LOCAL` RLS) plus simples et plus sûres ; charge attendue compatible |
| 2026-10-23 | **Dramatiq** (broker Redis) pour les tâches de fond | Maintenu, retries/time-limits natifs, compatible code synchrone ; arq en maintenance minimale |
| 2026-10-23 | Worker dans le même package que l'API (`apps/api`), au lieu d'un `apps/worker` séparé | Partage des modèles et services sans duplication ; même image, commande différente |
| 2026-10-23 | Contrat OpenAPI committé + types TS générés (`openapi-typescript`, `openapi-fetch`), au lieu d'un `packages/api-types` | Moins de plomberie monorepo ; la CI bloque toute dérive |
| 2026-10-23 | Deux rôles PostgreSQL (`kora_owner` / `kora_app`) dès la phase 0 | La RLS de la phase 1 n'a de valeur que si le rôle d'exécution ne peut pas la contourner |
| 2026-10-23 | Tout l'outillage tourne en conteneurs (uv 0.13.4, Python 3.13, Node 24) | Parité stricte local/CI ; aucun prérequis local hors Docker |
| 2026-10-23 | Isolation : RLS PostgreSQL (`app.tenant_id`, FORCE) **et** filtrage applicatif ; tables plateforme (users, companies, memberships…) sans RLS, accès par services testés | Défense en profondeur ; un utilisateur appartient à plusieurs tenants |
| 2026-10-23 | Dossier inaccessible ⇒ **404** (jamais 403) | Ne pas révéler l'existence d'un dossier |
| 2026-10-23 | SUPER_ADMIN **sans** accès aux données des dossiers | Confidentialité ; accès support explicite à concevoir en phase 8 |
| 2026-10-23 | Refresh tokens : rotation + révocation de famille, **tolérance de 20 s** à la réutilisation | Requêtes parallèles d'un navigateur (préchargements) ; au-delà = vol présumé |
| 2026-10-23 | Frontend en **BFF** : jetons en cookies httpOnly, appels API côté serveur Next | Aucun jeton accessible au JavaScript ; formulaires fonctionnels en 3G |
| 2026-10-23 | CSP **sans nonce** (`script-src 'self' 'unsafe-inline'`), autres directives strictes | Avec Cache Components la coquille statique ne peut pas porter de nonce ; à durcir avec SRI quand stable |
| 2026-10-23 | L'API ne fait confiance qu'à `KORA_TRUSTED_PROXY_COUNT` proxys pour l'IP client ; uvicorn sans `--proxy-headers` | Limitation de débit non contournable par un en-tête forgé |
| 2026-10-23 | Montants et taux en entiers (taux en points de base : 1800 = 18 %) | Pas de flottant ; conversion des saisies par chaîne (`lib/rates.ts`) |
| 2026-10-23 | Stockage S3 **reporté** à la phase où il sert | Pas de service inutilisé. Note : MinIO ne publie plus d'images Docker officielles gratuites — choisir le serveur S3 local (MinIO via image tierce, Garage, SeaweedFS…) au moment voulu |
| 2026-10-24 | Emails en **SMTP générique** (aucun SDK fournisseur), Mailpit en local et en E2E | Fournisseur non choisi par l'utilisateur : tout fournisseur SMTP convient, changement par configuration |
| 2026-10-24 | « Mot de passe oublié » : l'API répond toujours 202 et le worker cherche le compte | Ni la réponse ni le temps de réponse ne révèlent l'existence d'un compte |
| 2026-10-24 | Réinitialisation : ferme toutes les sessions, lève le verrouillage, confirme l'adresse ; la **2FA reste exigée** | Recevoir le lien prouve la maîtrise de l'adresse, pas du second facteur |
| 2026-10-24 | Inviter une personne sans compte exige une **adresse vérifiée** chez l'invitant ; quota de 20 invitations / dossier / 24 h, 3 emails de compte / heure | Empêcher l'usage de Kora pour envoyer du spam ou inonder une boîte |
| 2026-10-24 | Vérification d'adresse et liens d'email : action par **bouton (POST)**, pas à l'ouverture du lien ; `Referrer-Policy: no-referrer` sur ces pages | Les antivirus de messagerie visitent les liens ; le jeton ne doit pas fuiter |
| 2026-10-24 | Invitations limitées aux **dossiers d'entreprise** ; cabinets en phase 8 (avec leurs écrans) | L'ajout d'un collaborateur de cabinet exige encore un compte existant |
| 2026-10-24 | Montants transmis en **chaînes de chiffres** dans l'API (type `Money`) | JavaScript perd la précision au-delà de 2^53 ; aucun flottant ne doit toucher un montant |
| 2026-10-24 | Écriture : brouillon libre → validée = numérotée (séquence verrouillée par journal et exercice) et **immuable** ; correction par contre-passation | Numérotation sans trou et piste d'audit exigées par la comptabilité |
| 2026-10-24 | Immuabilité, équilibre et appartenance au dossier **imposés par PostgreSQL** (déclencheurs, clés étrangères composites `(tenant_id, id)`) | Défense en profondeur : aucun bogue applicatif ne peut produire une écriture déséquilibrée ou croisée |
| 2026-10-24 | Imputation refusée sur un compte qui a des sous-comptes ; à-nouveaux datés du 1er jour de l'exercice | Conventions usuelles, à confirmer par un expert-comptable guinéen |
| 2026-10-24 | États sur écritures **validées** uniquement ; à-nouveaux (journal A_NOUVEAUX) toujours dans le solde d'ouverture ; soldes signés en chaîne (`SignedMoney`) | Présentation SYSCOHADA usuelle (balance à 6 colonnes), à confirmer par un expert-comptable |
| 2026-10-24 | Lettrage stocké à part (`letterings`, `lettering_lines`), équilibre vérifié par un déclencheur **différé** ; comptes lettrables = classe 4 ; lettrage automatique **uniquement** par référence de pièce identique | Les lignes validées restent immuables ; pas de rapprochement deviné (le rapprochement probabiliste viendra avec la trésorerie, phase 3) |
| 2026-10-24 | Clôture : à-nouveaux générés (origine CLOSING) = soldes des classes 1–5 + résultat en 131/139, sans affectation ; réouverture = **contre-passation** des à-nouveaux (jamais de suppression) ; exercice clôturé et période verrouillée refusés par la base | Les à-nouveaux reproduisent exactement le bilan ; piste d'audit complète |
| 2026-10-24 | Clôture, réouverture et déverrouillage réservés au dirigeant et à l'administrateur de cabinet (`fiscal_years:close`) ; verrouiller reste ouvert aux comptables | Actes engageants ; à confirmer avec les utilisateurs |
| 2026-10-24 | Dépôt GitHub **privé** `skaba89/kora-finance` ; livraisons par branche + pull request, fusion seulement si la CI est verte | La protection de branche exige GitHub Pro sur un dépôt privé (non active) |

## À valider par un expert-comptable guinéen

Nomenclature du plan SYSCOHADA révisé à précharger · journaux par défaut (AC, VT, BQ,
CA, MM, OD, AN) · interdiction d'imputer sur un compte de regroupement · comptes lettrables (classe 4) · comptes 131/139 et classes de résultat (6, 7, 8) à la clôture ·
report du résultat sans affectation · réouverture d'un exercice clôturé · méthode du tableau des flux de
trésorerie · taux de TVA et autres taxes en vigueur, format de déclaration · mentions
légales obligatoires des factures · durée de conservation des pièces · pertinence de
l'import FEC (format français) pour les cabinets guinéens.
