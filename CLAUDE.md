# Kora Finance — instructions pour Claude Code

Plateforme SaaS de gestion financière et comptable pour les PME guinéennes et les
cabinets comptables : comptabilité SYSCOHADA révisé, rapprochement Mobile Money et
bancaire, états financiers prêts pour un dossier de crédit, assistance IA.
**Produit de production, pas une démo** : chaque livraison est complète, testée et sécurisée.

Le parcours Ventes est organisé en Documents, Encaissements et Recouvrement. Le lien de création du tableau de bord ouvre le formulaire de brouillon pour les rôles autorisés.

Le chantier Kora Premium est documenté dans `docs/STYLE_UI.md` §10 : Inter,
tokens sémantiques, titres, conteneur élargi et navigation repliable. Continuer par petits lots UX,
avec validation de la CI et recette visuelle avant fusion.

Journal daté des sessions : `worklog.md`. Le lire en début de session.

## État d'avancement

| Phase | Contenu | État |
|---|---|---|
| 0 | Fondations du dépôt : monorepo, Docker, CI, harnais de tests | ✅ livrée (2026-10-23) |
| 1 | Socle : auth, multi-tenant + RLS, RBAC, organisation, plan comptable, taxes, audit chaîné, PWA | ✅ livrée (2026-10-23) ; 1g emails ✅ (2026-10-24) — reste listé dans `worklog.md` |
| 2 | Comptabilité générale + états financiers | ✅ livrée — 2a saisie, 2b balance/grand livre, 2c lettrage, 2d clôture, 2e bilan et CR, 2f exports, 2g1 pièces, 2g2 saisie guidée, 2g3a hors connexion, 2h tableau de bord (2026-10-27) ; 2e-bis TFT en méthode directe ✅ (2026-11-11) ; reste 2g3b photos de pièces hors connexion (`docs/PLAN.md`) |
| 3 | Trésorerie, Mobile Money, rapprochement | ✅ livrée — 3A comptes financiers ✅ (2026-11-11), 3B import relevés OFX/CSV ✅ (2026-11-11), 3E prévisionnel 30/60/90 ✅ (2026-11-12), 3C rapprochement assisté ✅ (2026-11-12), 3D import Mobile Money étiqueté ✅ (2026-11-13) |
| 4 | Ventes et achats | ✅ livrée — 4A référentiel tiers ✅ (2026-11-13), 4B devis/factures/avoirs sans trou ✅ (2026-11-14), 4B-bis PDF conforme ✅ (2026-11-15), 4C règlements/lettrage/balance âgée ✅ (2026-11-17), 4D relances ✅ (2026-11-17), 4E comptabilisation des ventes ✅ (2026-11-18), 4F achats/décaissements/échéancier/comptabilisation ✅ (2026-11-18), 4D-bis envoi email du document avec PDF ✅ (2026-11-18), B2 relances automatiques configurables ✅ (2026-11-19), B3 acomptes clients/avances fournisseurs/trop-perçus/remboursements/affectation ultérieure ✅ (2026-11-19), B4 échéanciers clients/export de la balance âgée/indicateurs de recouvrement et DSO ✅ (2026-11-20) ; reste imputation multi-comptes, WhatsApp (compte Business requis) (`docs/PLAN.md`) |
| 5 | Import et migration | En cours — 5A CSV, 5B FEC, 5C Excel, 5D1 contrôle métier, 5D2a catalogue tenant, 5D2b staging et maintenance, 5D2c1 précontrôle et 5D2c2 quotas intégrés ; 5D2c3 API fusionnée, 5D2c4 interface de précontrôle en validation |
| 6 | Dossier de financement partageable | — |
| 7 | Assistant IA | — |
| 8 | Espace cabinet et abonnements | — |

Durcissement production livré du 2026-11-09 au 2026-11-11 (KF-03 verrou d'exercice,
KF-05 instantanés REPEATABLE READ, KF-07 verrou de société, KF-09 bucket de sauvegarde
séparé, KF-11 déploiement versionné + sauvegarde pré-migration, KF-12 supervision des
sauvegardes, KF-13 budgets de ressources et quotas d'exports, KF-23 contrôles de taille
et de chemin des sauvegardes, KF-20 SCA/SBOM/scan d'images en CI, N-B6 plafonds de
session PostgreSQL) — détails dans `worklog.md` et `AUDIT_SUIVI_20261109.md`.

Le cahier des charges complet et les critères d'acceptation de chaque phase sont dans
`docs/PLAN.md`.

Le chantier de modularité par tenant (benchmark Tiime/Pennylane et adaptation
africaine) est désormais cadré par `docs/MODULARITE.md`. Le catalogue pur M1
et la persistance M2 versionnée et auditée ne modifient pas les droits effectifs ;
les gardes serveur précèdent toute activation commerciale ou administrative.
M3a prépare l'annuaire et le contexte d'administration sans droit comptable ;
M3b expose les routes HTTP d'administration et de lecture tenant. M4a applique
la restriction aux nouveaux calculs et exports prévisionnels, en conservant
les instantanés historiques et le RBAC existant.
M5a (PR #159 fusionnée, CI verte) livre l'écran d'administration des modules
FR/EN réservé à la plateforme ; la recette métier reste à confirmer. Le lot
M6 (offres et licences) doit rester distinct des choix administratifs et du RBAC.

## Architecture

```
apps/api/      FastAPI + SQLAlchemy 2 (sync) + Alembic + Pydantic v2 — package `kora` (src/kora)
               └ worker Dramatiq dans le même code (src/kora/worker), même image Docker
apps/api/openapi.json         contrat d'API exporté (committé, vérifié en CI)
apps/web/      Next.js 16 App Router + TypeScript strict + Tailwind 4 + shadcn/ui (radix-nova)
apps/web/src/lib/api/schema.ts  types TS générés depuis openapi.json (ne pas éditer)
infra/postgres/init-roles.sh  rôles et bases PostgreSQL (local + CI)
infra/garage/  Garage (S3 local) : configuration + bootstrap.py (nœud, clé, buckets ; idempotent)
scripts/       init-env.sh (secrets : .env local ou deploy/vps/.env), check-contract.sh, check-runtime-db-separation.py, check-deploy-versioning.py, check-supervision.py, check-compose-budgets.py
deploy/vps/    production sur un VPS dédié : compose.yml (Caddy seul exposé), Caddyfile,
               bootstrap-server.sh, deploy.sh, backup.sh / restore.sh + supervision systemd
               (kora-backup/freshness/probe/alert + alert.sh/backup-status.sh/probe.sh ; KF-12)
               (guide : docs/DEPLOIEMENT.md)
.github/workflows/ci.yml      CI : mêmes commandes `make` qu'en local
```

Pile locale (`docker-compose.yml`, ports sur 127.0.0.1 uniquement) :
postgres 16 (55432) · redis 7 (56379) · mailpit (UI 58025) · storage = Garage v2.4.1 (S3 53900) ·
storage-init (one-shot) · migrate (one-shot) · api (8100) · worker · web (3100).
Buckets : `kora` (pile), `kora-test` (pytest, contre le vrai Garage).
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
             closing.py (verrouillage de période, clôture, à-nouveaux, réouverture),
             statements.py + data/etats_*.csv (bilan et compte de résultat SYSCOHADA),
             guided.py + data/saisie_guidee_v1.csv (saisie guidée : opération → écriture)
             dashboard.py (indicateurs du tableau de bord : une requête agrégée, écritures validées)
audit/       journal chaîné SHA-256 (écriture, vérification)
storage/     objets chiffrés (AES-256-GCM, clé par objet enveloppée par KORA_ENCRYPTION_KEYS)
             dans un service S3 compatible (boto3, adressage par chemin) ;
             backups_store.py : sauvegardes dans un bucket/clé S3 DÉDIÉS (KF-09), client
             distinct, aucune suppression — rétention côté fournisseur, purge manuelle
             avec la clé d'administration hors VPS
attachments/ pièces justificatives des écritures (type lu dans le contenu, dédoublonnage
             par SHA-256, conservation après validation, purge différée par le worker)
exports/     document neutre → Excel (openpyxl) ou PDF (reportlab, police DejaVu de l'image)
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
public/sw.js        service worker : pages publiques « hors connexion » et « saisie hors connexion »
                    + /_next/static ; rien d'authentifié en cache
lib/offline         saisie hors connexion : IndexedDB chiffrée (AES-GCM, clé non exportable),
                    file d'attente, synchronisation idempotente (components/offline)
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
make storage-check  # écrit/relit/supprime un objet chiffré dans le S3 configuré (voir README)
# Production (sur le serveur) : deploy/vps/deploy.sh, backup.sh, restore.sh — docs/DEPLOIEMENT.md
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
- Le sélecteur de dossier utilise la liste autorisée du DAL sous Suspense, avec
  confirmation explicite et retour au tableau de bord du dossier cible (voir `docs/UX_TOPBAR.md`).
- `usePathname()` renvoie le chemin réécrit : pour l'URL visible, lire `window.location`
  après hydratation (voir `components/nav-link.tsx`).
- Les tests E2E tournent sur desktop et mobile (Pixel 5) : une colonne masquée sur
  mobile (`hidden sm:table-cell`) n'est pas visible pour Playwright.
- Après une navigation client, Next 16 **garde la page précédente dans le DOM (masquée)** :
  `getByLabel` peut alors trouver deux champs ; préférer `getByRole`, qui ignore le masqué.
- Service worker, IndexedDB chiffrée et `crypto.subtle` exigent un contexte sécurisé : en E2E
  (http://web:3000), `e2e/hors-connexion.spec.ts` lance le **Chromium complet**
  (`channel: "chromium"`) avec `--unsafely-treat-insecure-origin-as-secure` ; le shell
  headless par défaut ignore ce drapeau.
- Liens vers `/hors-connexion/saisie` : `<a>` (navigation complète servie par le service
  worker), jamais `<Link>`, qui échouerait sans réseau.
- `crypto.randomUUID()` n'existe qu'en HTTPS/localhost (absent en E2E sur http://web:3000) :
  utiliser `uuidV4()` de `lib/uuid.ts`.
- Tableaux larges (balance, grand livre) : fiches `sm:hidden` sur téléphone + tableau
  `hidden sm:table`. En E2E, `getByRole` ignore la variante masquée (rôle `row` sur
  ordinateur, `listitem` sur mobile, voir `e2e/etats.spec.ts`).
- Montants affichés avec des espaces fines insécables (fr-FR) : dans une regex, `\s`.
- Dialogues `window.confirm` en E2E : brancher le traitement sur l'attente,
  `page.waitForEvent("dialog").then(dialog => dialog.accept()|dismiss())`, créé avant le
  clic et achevé après lui. Deux `page.once` consécutifs peuvent recevoir le même
  dialogue si le confirm s'ouvre après la résolution du clic (logout hors connexion :
  lecture IndexedDB avant confirm) — « already handled » et déconnexion annulée ; à
  l'inverse, un confirm **synchrone** bloque le clic tant que le dialogue n'est pas
  traité, donc attendre puis cliquer ne marche pas non plus (échecs CI #44/#45).
- Montants : chaînes de chiffres (unités mineures) de bout en bout ; saisie par
  `parseAmount`, sommes en BigInt (`lib/amounts.ts`), affichage par `formatMoney`.
- `KpiCard` est une primitive visuelle : reçoit un montant déjà formaté et ne
  réalise aucun calcul ; ne pas y ajouter de conversions financières.
- `DataTable` reste une table sémantique ; conserver pagination et filtres
  globaux côté serveur, ne jamais trier uniquement une page en prétendant trier
  le jeu complet. Préférences URL validées par `table-preferences.ts`.
  Fixer le `thead` entier pour les en-têtes à plusieurs lignes ; `desktopOnly`
  masque aussi la zone de défilement lorsque des fiches mobiles existent.

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
| 2026-10-24 | États financiers pilotés par deux référentiels CSV versionnés (postes et formules ; affectation des comptes par préfixe le plus long et sens du solde) ; résultat de la période ajouté à CJ ; comptes non affectés signalés, jamais ignorés | Les règles se corrigent sans toucher au code de calcul ; des tests garantissent que chaque compte du plan est affecté et que XI = produits − charges |
| 2026-10-24, arbitré 2026-11-11 | TFT (2e-bis) en méthode directe : flux réels de la classe 5 classés par contrepartie, référentiels versionnés, contrôle cohérence avec le solde réel | `docs/ARBITRAGE_COMPTABLE.md` ; classement des charges financières payées à confirmer en revue finale |
| 2026-10-24 | Exports : document neutre rendu en Excel (montants numériques exacts, Decimal) ou PDF (A4, police DejaVu installée dans l'image, pas de repli silencieux) ; relayés en flux par une route Next (BFF) ; chaque export tracé dans l'audit ; PDF limité à 20 000 lignes (Excel au-delà) | Pas d'accès direct du navigateur à l'API ; traçabilité des sorties de données |
| 2026-10-24 | Dépôt GitHub **privé** `skaba89/kora-finance` ; livraisons par branche + pull request, fusion seulement si la CI est verte | La protection de branche exige GitHub Pro sur un dépôt privé (non active) |
| 2026-10-25 | Stockage S3 local = **Garage v2.4.1** (image officielle `dxflrs/garage`), initialisé par son API d'administration ; production = fournisseur S3 managé (à choisir), en https | MinIO ne publie plus d'images gratuites ; Garage est versionné et léger. Le code ne dépend que de l'API S3 |
| 2026-10-25 | Pièces **chiffrées par l'application** (AES-256-GCM, clé aléatoire par objet, enveloppée par les clés maîtres ; nom de l'objet en donnée authentifiée) ; empreinte SHA-256 vérifiée à chaque lecture | Le fournisseur de stockage ne voit jamais le contenu ; une altération ou une substitution d'objet est détectée |
| 2026-10-25 | Type de fichier lu dans le **contenu** (PDF, JPEG, PNG, WebP), jamais l'extension ; 10 Mo et 20 pièces par écriture (paramétrables) ; même fichier sur la même écriture = une seule pièce | Pas de fichier exécutable stocké ; réessais en 3G sans doublon |
| 2026-10-25 | Pièce d'une écriture validée **non retirable** (service + déclencheur PostgreSQL) ; ajout toujours possible ; pièce jamais modifiée | Conservation des justificatifs ; durée légale à valider par un expert-comptable |
| 2026-10-25 | Envoi en **corps brut** (pas de multipart) ; côté web par Server Action (limite portée à 11 Mo), photos réduites dans le navigateur (2000 px, JPEG) ; consultation par une route BFF | Pas de dépendance multipart ; envoi léger en 3G ; le navigateur ne parle jamais au stockage |
| 2026-10-25 | Saisie guidée : 7 opérations fixes (vente encaissée, facture client, règlement client, dépense payée, facture fournisseur, règlement fournisseur, virement interne) ; natures des recettes/dépenses dans un CSV versionné ; l'**API construit l'écriture** (aperçu puis brouillon idempotent), le web ne fait que transmettre les choix | Une seule source de vérité comptable ; correspondances corrigeables sans code, à valider par un expert-comptable |
| 2026-10-25 | Saisie guidée : montant saisi **TTC**, TVA = taux TVA_NORMAL du dossier à la date (HT arrondi au plus proche, TVA = complément), avertissement si le taux n'est pas vérifié ; comptes proposés = comptes d'imputation (sous-comptes à la place du parent) ; journal = VT/AC pour les factures, BQ/MM/CA selon le compte de trésorerie | Pas de taux codé en dur ; aucune imputation sur un compte de regroupement |
| 2026-10-25 | Production sur un **VPS OVH dédié** (pas sur le serveur de dev, qui héberge d'autres projets) : Compose + Caddy (HTTPS Let's Encrypt), images construites sur le serveur depuis `main`, migrations par le service `migrate` ; Render abandonné | Choix de l'utilisateur ; isolation des données financières ; pas de registre d'images à gérer |
| 2026-10-25 | Sans nom de domaine : `<ip>.sslip.io` ; emails `KORA_EMAIL_BACKEND=disabled` (chaque email non envoyé journalisé sans destinataire, l'interface le signale) | Domaine et fournisseur SMTP pas encore choisis ; HTTPS exigé dès le départ |
| 2026-10-25 | Sauvegardes : `pg_dump` (même version que le serveur) chiffré par l'application, vérifié par relecture, dans le bucket S3 sous `backups/`, 30 jours (7 toujours gardées) ; restauration testée (données, déclencheurs, RLS identiques) | Une sauvegarde non vérifiée ou non restaurable ne compte pas |
| 2026-10-26 | Saisie hors connexion : on **saisit** sans réseau, on ne **valide** rien ; chaque saisie devient un brouillon à la synchronisation (identifiant créé sur l'appareil = clé d'idempotence de l'API) ; données du dossier téléchargées à la demande, valables 7 jours ; saisie guidée sans aperçu (l'API calcule la TVA à la synchronisation) | La comptabilité reste décidée par le serveur (équilibre, périodes, audit) ; pas de seconde implémentation des règles de TVA dans le navigateur |
| 2026-10-26 | Données hors connexion chiffrées dans IndexedDB (AES-256-GCM, clé WebCrypto **non exportable**, identifiant lié au chiffré), séparées par utilisateur, effacées à la déconnexion (avertissement si des saisies ne sont pas synchronisées) ; synchronisation par Server Action, verrou Web Locks entre onglets, sans Background Sync (absent sur iPhone et Firefox) | Protège contre la copie des fichiers du navigateur ; limite assumée et affichée : lisible par qui utilise le navigateur ouvert |
| 2026-10-27 | Tableau de bord sur écritures **validées** uniquement : trésorerie = comptes 52, 53, 55, 57 ; chiffre d'affaires = 70 ; charges = classe 6 ; résultat provisoire = classes 6 à 8 (avant inventaire) ; clients = 41, fournisseurs = 40 ; brouillons seulement comptés ; un seul dossier ⇒ accueil direct sur son tableau de bord (`/dossiers?liste=1` pour la liste) | Indicateurs cohérents avec la balance et les états ; regroupements à valider par un expert-comptable |
| 2026-11-09 | L'enrôlement du second facteur (`/auth/mfa/setup`, `/enable`) exige la **réauthentification** (mot de passe) et les quatre transitions 2FA sont sérialisées par verrou de ligne utilisateur | KF-08 : un access token volé ne doit pas pouvoir installer un facteur contrôlé par l'attaquant ; même protocole de verrou que la connexion (PR #18) |
| 2026-11-09 | Le déclencheur des écritures verrouille l'exercice (`FOR UPDATE` sur `fiscal_years`, migration 0010) et la validation applicative prend le même verrou avant la numérotation (`entries._fiscal_year_for(lock=True)`) | KF-03 : une validation engagée pendant une clôture ne peut plus échapper aux à-nouveaux (elle attend le commit de la clôture puis est refusée) ; ordre de verrous uniforme « exercice puis numérotation », pas d'interblocage |
| 2026-11-09 | Les rapports multi-requêtes (grand livre d'un compte, grand livre complet, états financiers N/N-1, les quatre exports) lisent leurs données sous un **instantané REPEATABLE READ dédié** (`db/snapshot.py` : `lecture_instantanee`), jamais en READ COMMITTED requête par requête | KF-05 : une validation concurrente entre deux requêtes mélangeait deux instants (totaux ≠ lignes, KeyError → 500 sur l'export) ; l'option d'isolation est posée sur une connexion neuve avant le `set_config` tenant, et la transaction (lecture seule) n'est jamais commitée |
| 2026-11-09 | Toute vérification « le dossier garde au moins un dirigeant » relit la société en `SELECT … FOR UPDATE` **avant** le comptage (`organization/service.py`) | KF-07 : deux rétrogradations simultanées de deux dirigeants comptaient chacune deux membres et pouvaient vider le dossier ; la seconde transaction attend le commit de la première puis relit un comptage frais. Ordre de verrous « membership puis société », sans interblocage |
| 2026-11-09 | Les sauvegardes vivent dans un **bucket et une clé S3 dédiés** (`storage/backups_store.py`), transmis au seul service `backup` du Compose — jamais à l'API/worker ; la clé de sauvegarde ne porte aucun droit de suppression, la purge (`prune`) exige la clé d'administration distincte `KORA_BACKUP_ADMIN_S3_*` hors VPS | KF-09 : une application compromise pouvait détruire les pièces ET leurs sauvegardes (même bucket, même clé, `prune` automatique) ; désormais la destruction des pièces n'atteint pas les sauvegardes, et la rétention est administrée côté fournisseur |
| 2026-11-09 | Chaque déploiement VPS est une **release identifiée par le SHA du commit** : images étiquetées `kora-api:<sha>` / `kora-web:<sha>` (`KORA_IMAGE_TAG`, plus d'écrasement de `:prod` avant la bascule), **sauvegarde pré-migration vérifiée imposée** (`backup.sh`, image en cours), `up -d --wait`, **retour automatique** à la version précédente en cas d'échec, consignation `releases.log` ; `rollback.sh` pour un retour manuel ; contrats vérifiés en CI (`scripts/check-deploy-versioning.py`) ; convention expand/contract documentée (le schéma n'est jamais migré en arrière) | KF-11 : un déploiement écrasait les tags mobiles sans sauvegarde imposée ni retour arrière — une migration refusée ou un healthcheck échoué laissait un état non reproductible ; désormais chaque version déployée est reconstruisible à l'identique et le retour à la version connue est automatique |
| 2026-11-10 | La sauvegarde et l'application sont **supervisées** : `OnFailure=kora-alert@%n.service` sur les unités systemd (sauvegarde, fraîcheur, sonde), contrôle quotidien de fraîcheur de la dernière sauvegarde (`backup status --max-age-hours 26`, timer 03:45 UTC), sonde externe toutes les 5 minutes sur `https://<domaine>/health/ready` (route Caddy étroite `/health/*` → API, certificat TLS inclus), alerte email anti-tempête via `kora.scripts.notify` (destinataire `KORA_ALERT_EMAIL`) + trace locale `backups/alertes/journal.log` ; contrats vérifiés en CI (`scripts/check-supervision.py`) | KF-12 : l'échec de la sauvegarde quotidienne (oneshot systemd sans `OnFailure=`) passait inaperçu — des jours sans sauvegarde pouvaient s'accumuler en silence ; désormais un échec de sauvegarde, une sauvegarde trop ancienne ou une application injoignable déclenchent une alerte d'exploitation tracée |
| 2026-11-10 | Les exports et les conteneurs sont **budgétés** : quota Redis à fenêtre fixe sur `/exports/*` (30/h par utilisateur, 120/h par dossier, réglages `KORA_EXPORTS_*`, `429` + `Retry-After`, panne Redis = échec fermé), compteur générique `kora.core.quota` fail-closed partagé avec les emails ; `deploy.resources.limits` (mémoire + CPU) sur chaque service des deux Compose, Redis `--maxmemory 200mb --maxmemory-policy noeviction` ; contrats verrouillés en CI (`scripts/check-compose-budgets.py`) | KF-13 : des exports synchrones illimités (rendu PDF/Excel en mémoire) et des conteneurs sans budget permettaient à quelques requêtes automatisées de saturer l'API ou à un conteneur fugueur d'affamer ses voisins et l'hôte ; désormais l'excès renvoie 429 et un conteneur fugueur est borné avant de nuire |
| 2026-11-10 | Les sauvegardes sont **contrôlées à l'entrée et à la sortie** : `stat()` AVANT lecture (fichier régulier, taille ≤ plafond `KORA_BACKUP_S3_MAX_BYTES`, défaut 400 Mo aligné sur le conteneur « backup »), clés imposées au préfixe `backups/`, téléchargement atomique (`.partiel` + `os.replace`) ; `restore.sh` valide la clé par expression régulière, vérifie la signature `PGDMP` avant la confirmation destructrice et efface le dump en clair par un `trap` | KF-23 : un fichier surdimensionné saturait la mémoire avant d'être refusé, et une restauration pouvait remplacer les données par un fichier corrompu (jamais vérifié) ; désormais rien d'invalide n'est lu ni restauré, et aucune copie en clair ne traîne |

## À valider par un expert-comptable guinéen

Nomenclature du plan SYSCOHADA révisé à précharger · journaux par défaut (AC, VT, BQ,
CA, MM, OD, AN) · interdiction d'imputer sur un compte de regroupement · comptes lettrables (classe 4) · comptes 131/139 et classes de résultat (6, 7, 8) à la clôture ·
report du résultat sans affectation · réouverture d'un exercice clôturé · **affectation des comptes
aux postes du bilan et du compte de résultat** (`accounting/data/etats_affectations_2017.csv`,
colonne `note`) · présentation des états · comptes 13 non affectés présentés en CJ · méthode du tableau des flux de
trésorerie · taux de TVA et autres taxes en vigueur, format de déclaration · mentions
légales obligatoires des factures · durée de conservation des pièces · ajout d'une pièce à une écriture d'un exercice clôturé (autorisé aujourd'hui) · **regroupements du tableau de bord** (`accounting/dashboard.py` : trésorerie 52/53/55/57, chiffre d'affaires 70, résultat provisoire classes 6 à 8) · **correspondances de la saisie guidée** (`accounting/data/saisie_guidee_v1.csv`, comptes 4431/4452 pour la TVA, journaux par opération, virement interne sans compte 585) · pertinence de
l'import FEC (format français) pour les cabinets guinéens.

Le portail plateforme M5b ajoute un accueil FR/EN et le total réel des dossiers ;
aucune donnée comptable ni indicateur commercial fictif (`docs/MODULARITE.md`).

M6a1 introduit les versions d'offres commerciales sans attribution de droits,
prix ni mutation de configuration ; voir `docs/MODULARITE.md`.

M6a2 définit les périodes de licence et leurs états commerciaux, sans effet
sur les permissions ; persistance et audit à livrer dans M6b.

M6b1 prépare le stockage global des offres (0028), en lecture seule pour le
runtime, sans attribution ni changement des permissions.
