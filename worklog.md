# Journal de travail Kora Finance

Entrées datées, les plus récentes en haut. Chaque session y note ce qui a été fait,
vérifié, et ce qui reste.

## 2026-11-13 — Phase 3D : architecture Mobile Money documentée (PR #80)

**Objet** — `docs/PHASE_3D_MOMO.md` : conditions officielles des API
(momodeveloper.mtn.com : Collections/Disbursements/Remittances, sandbox,
production = contrat par marché ; developer.orange.com om-webpay : contrat
marchand OAuth2 par pays — sources consultées le 13/11/2026). Aucune
autorisation opérateur pour ce projet : **connecteurs API non implémentés**,
aucun écran ni statut « connecté », aucune activation simulée.

**Livré** : import CSV étiqueté (colonne frais → ligne `[FRAIS]` distincte,
PR #81), déduplications fichier + ligne inchangées, rapprochement 3C avec
confirmation humaine obligatoire, architecture cible des connecteurs
(config par dossier via `financial_accounts.operator`, modes IMPORT/PULL/
WEBHOOK, identifiants chiffrés futurs, jamais d'auto-posting).

**Reste** : adaptateur Excel, recollement sur export réel opérateur, journal
d'erreurs de synchronisation, connecteur pull API uniquement après contrat.

## 2026-11-13 — Make compatible PowerShell (PR #79) : première exécution réelle de l'utilisateur

**Reterrain** — première exécution sur Docker Desktop (Windows 11, PowerShell) :
`make seed` a bien atteint le conteneur api et le seed a répondu « La
démonstration existe déjà ; utilisez --reset » (pile en marche, données
prêtes) ; en revanche `make env` et `make up` échouaient car PowerShell n'a
ni `bash` ni les coreutils (`id`) sur le PATH — erreurs CreateProcess sur
`id -u`/`id -g` et « Le fichier spécifié est introuvable » sur
`./scripts/init-env.sh`.

**Corrections (Makefile)** :

- `KORA_UID`/`KORA_GID` : détection `OS=Windows_NT` + `MSYSTEM` — Git Bash
  garde `id -u`/`id -g` (comportement inchangé), PowerShell/cmd prennent 1000
  (Compose applique déjà `${KORA_UID:-1000}`) sans plus de bruit CreateProcess ;
  Linux/macOS inchangés ;
- `env` : appel explicite `bash ./scripts/init-env.sh` avec message d'action
  clair si bash manque (".env présent → passer à make up" / "Git Bash §5")
  au lieu d'une erreur Windows illisible ;
- `up` : le prérequis `env` n'est déclenché que si `.env` est absent
  (`$(wildcard .env)`) — Compose lit `.env` lui-même, donc `make up` marche
  depuis PowerShell une fois l'environnement créé.

**Documentation (`docs/DEMO.md`)** : tableau §5.1 étendu à 4 colonnes
(Windows PowerShell), nouvelle §5.8 « PowerShell (sans Git Bash) » — cibles
fonctionnelles, exception `make env`, et précision explicite : le message
« La démonstration existe déjà » n'est **pas une panne** (garde anti-doublon
volontaire du seed, pile saine).

**Validation** : `make -n up` sans `.env` (prérequis env + message), avec
`.env` touché puis supprimé (compose direct), `make help` (libellés) ;
cohérence du tableau markdown vérifiée (5 pipes par ligne). Aucun code
applicatif — pas d'impact pytest/score.

**Reste** : confirmation utilisateur sur PowerShell après pull ; suite
Phase 3D.

## 2026-11-13 — Cibles `make seed` / `make seed-reset` (PR #78) et contrôle statique de la pile Docker

**Motivation** — lancement de la pile sur Docker Desktop : le parcours était
documenté dans `docs/DEMO.md` mais le seed passait par une commande `docker
compose exec` à recopier ; deux cibles Make le raccourcissent.

- `make seed` : charge le jeu de démonstration Djouma Distribution SARL
  (équivalent exact de la commande documentée en §1) ;
- `make seed-reset` : réinitialisation complète — passe
  `KORA_DATABASE_MIGRATION_URL` interpolée par Compose depuis le `.env` (le
  conteneur `api` ne porte pas les droits DDL, séparation runtime/DDL
  inchangée) — même commande que §3 ;
- `docs/DEMO.md` §1 et §3 mentionnent les deux raccourcis (les commandes
  détaillées restent la référence).

**Contrôle statique de la pile avant lancement Docker Desktop** (aucune
modification, tout était déjà cohérent) : YAML compose valide (13 services),
fichiers montés présents (`init-roles.sh`, `garage.toml`, `bootstrap.py`),
cibles Dockerfile `runtime`/`dev` présentes (api et web), les 11 variables
obligatoires (`${VAR:?lancer make env}`) couvertes par `.env.example`,
`scripts/check-compose-budgets.py` (KF-13) en succès.

**Validation** : `make -n seed`, `make -n seed-reset`, `make help` (recettes
sèches correctes, tabulations préservées) ; aucun code applicatif touché —
pytest/lint/typecheck non requises (Makefile + docs seulement). Pas d'impact
de score.

**Reste** : exécution réelle sur Docker Desktop (Windows 11 / WSL 2) par le
porteur du projet — les pannes déjà rencontrées et leurs remèdes sont dans
`docs/DEMO.md` §5.4 ; suite du chantier Phase 3D (connecteurs Mobile Money).

## 2026-11-13 — Phase 3E finalisée : écrans de seuils/instantanés + démonstration de la tension

**Écrans manquants livrés (PR #75)** — l'API des seuils et instantanés existait
depuis §28, il manquait l'interface :

- `GET /cashflow/snapshots/{id}` (détail d'un instantané, isolation vérifiée) —
  contrat pur ajout (ancien contrat identique une fois le chemin retiré), types TS
  régénérés ;
- écran **Seuils d'alerte** (`/previsions/reglages`) : seuil critique, seuil de
  surveillance (GNF), horizon et scénario par défaut ; lecture dès
  `treasury:read`, enregistrement réservé à `treasury:manage` (audité) ;
- écran **Instantané** (`/previsions/instantanes/{id}`) : en-tête figé +
  comparaison jour à jour **prévisionnel / réalisé / écart**, totaux et écarts
  les plus marquants ;
- prévision : « Figer cette prévision » (InlineAction, scénario lié — patron 3C)
  et lien seuils ; i18n fr/en +14 clés (parité 68/68).

**Démonstration enrichie (PR #76)** — `seed_demo.apply_forecast_echeances()` :

- chèque postdaté **reçu** de Sahel Agro à +10 j (12 500 000 GNF, ENGAGE) ;
- chèque postdaté **remis** à Mamaya Import-Export à +20 j (195 000 000 GNF,
  réassort trimestriel — **tension volontaire**) ;
- brouillon de règlement Soleil Élec à +25 j (brouillons futurs exclus) ;
- facture fournisseur à régler FAC-F-2026-052 (14 750 000 GNF, non lettrée) ;
- `demo_today()` : date d'exécution dans la fenêtre octobre-novembre 2026, sinon
  date de référence documentée — échéances dans l'exercice ouvert, relevés
  **déterministes** (deux exécutions : fichiers identiques).

**Résultat du scénario vérifié sur base réelle (PG 16.2, RLS active)** :
prévision 30 j NEUTRE = **CRITIQUE**, point bas **−6 947 387 GNF le 2026-12-03**,
première date critique 3 décembre ; flux ENGAGE +12,5 M le 23/11 et −195 M le
03/12 ; `docs/DEMO.md` étapes 9-11 (tension, seuils, instantanés).

**Validation locale** : pytest **778/778** (nouveau test détail + isolation),
ruff check + format, mypy strict, ESLint 0, tsc 0, Vitest 69/69, build Next OK.
Reste à la CI (facturation) : restauration synthétique, pip-audit/SBOM, E2E.
Suivi : `AUDIT_SUIVI_20261109.md` §30.

## 2026-11-13 — Fusion des PRs 70-73, diagnostic CI définitif (facturation du compte)

**Diagnostic CI clos avec preuve officielle** : re-exécution du run de la branche
repo-hygiene (run `43262026312`, attempt 2) → **8 jobs rejetés en ~3 s, 0 step
exécuté, aucun runner attribué, aucun log**. L'annotation du check-run GitHub :

> « The job was not started because recent account payments have failed or your
> spending limit needs to be increased. Please check the 'Billing & plans' section
> in your settings »

Ce n'est donc **pas un défaut de code** : `main` est dans le même état depuis le
11/11. Constat associé : la lecture de la protection de branche renvoie 403
(« Upgrade to GitHub Pro or make this repository public ») — le paiement GitHub Pro
échouant, **la protection de branche est actuellement désactivée** côté GitHub ; la
discipline feature → PR → merge continue d'être appliquée volontairement. Chaque PR
(#70-73) porte en commentaire le statut CI honnête + la preuve locale. Action
utilisateur : Settings → Billing & plans (régler le paiement ou relever la limite),
puis re-jouer la CI sur `main`.

**Fusion** : séquence **#72 (.gitattributes) → #71 (docs Windows) → #70
(`resolve_out_dir`) → #73 (Phase 3E)** par l'API GitHub (commits de merge). Deux
résolutions de conflit réalisées sur les branches avant fusion :

- #70 : `worklog.md` (entrées C2+C3 conservées) + `docs/DEMO.md` §5.3/§5.4 passés
  au présent (le repli `resolve_out_dir` est désormais fusionné) ;
- #73 : `worklog.md` (3E au-dessus de C2/C3) + `AUDIT_SUIVI_20261109.md`
  (numérotation §27 C3 puis §28 3E restaurée).

**Revalidation complète du composé** (pile locale réelle : PostgreSQL 17.11,
Redis, S3 d'essai, Mailpit) — l'arbre fusionné est **identique bit à bit à `main`**
(arbre `515f3b5b` vérifié des deux côtés) :

- **pytest 775/775** (698 sur `main` avant fusion + 40 moteur cashflow + 11
  intégration cashflow + 5 seed-outdir + ~21 isolations/ajouts 3E) en 5 min 08 ;
- ruff check + format verts (169 fichiers) ; mypy strict **169 fichiers** OK ;
- ESLint `--max-warnings=0` ; `tsc --noEmit` 0 erreur ; **Vitest 69/69** ;
- contrat OpenAPI : `openapi.json` **identique** (85 chemins, 140 schémas).

Reste à la CI (quotas restaurés) : restauration synthétique, pip-audit/SBOM, E2E
Playwright. Suivi : `AUDIT_SUIVI_20261109.md` §29.

## 2026-11-13 — Corrections 3E après première exécution réelle de la suite

Première exécution de la suite API complète sur une pile locale réelle
(PostgreSQL 17.11 décompressé sans root, Redis réel, S3 d'essai, Mailpit) — la CI
étant indisponible côté GitHub (runners refusés au niveau du compte, 0 step).
Quatre défauts trouvés, corrigés, couverts :

- `PUT /cashflow/settings` et `POST /cashflow/snapshots` ne commitaient pas
  (flush annulé à la fermeture de session) → seuils ignorés, instantanés
  invisibles ; commit explicite après l'événement d'audit (patron invitations.py).
- Migration 0014 : FK simple `tenant_id → companies.id` manquante sur
  `cashflow_snapshot_lines` (la convention « composite + simple » de 0005) ;
  la garde alembic l'a détectée, corrigée dans la migration.
- `AssumptionsOut` tronquait les hypothèses (5 champs rejetés par pydantic) :
  modèle complété, contrat + `schema.ts` régénérés (addition pure).
- Catégories d'historique polluées par des buckets 0 (defaultdict des deux sens) :
  un flux n'alimente plus que son sens ; deux attentes de test rectifiées (moyenne
  /3 sur les décaissements, comme le moteur le fait pour les deux flux).

**Preuves** : pytest **770/770** (suite intégrale, 5 min 06) ; ruff check+format
verts (183 fichiers) ; mypy strict 168 fichiers ; tsc 0 erreur ; ESLint 0 ;
vitest 69/69. Détail : `AUDIT_SUIVI_20261109.md` §28 bis.

## 2026-11-12 — Phase 3E : prévision de trésorerie 30/60/90 jours

**Livré**
- Moteur pur (`kora/cashflow/engine.py`) : OBSERVE + ENGAGE + ESTIME, 3 scénarios
  (coefficients documentés dans `assumptions.py`, sérialisés dans chaque snapshot),
  détection de tension (seuils critique/surveillance), agrégat beyond_horizon
  (aucun flux perdu), arithmétique 100 % entière.
- Service + API : 7 endpoints sous `/cashflow/*` (prévision, export PDF/XLSX audité,
  seuils, instantanés, prévision vs réalisé), migration **0014** (3 tables tenant,
  RLS ENABLE+FORCE — renumérotée depuis 0011 : 3A/3B/3C ont pris 0011-0013 sur
  `main` entre-temps), statuts/scénarios déclarés en `Literal` et hypothèses en
  modèle pydantic dédié (`AssumptionsOut`) pour un contrat OpenAPI précis.
- Frontend : page `tresorerie/previsions` mobile-first (horizon/scénario via URL),
  graphique hebdomadaire BigInt, détail journalier, hypothèses affichées,
  instantanés ; exports branchés sur la liste blanche `exports.ts`
  (`previsions-tresorerie`) et le proxy BFF existant ; i18n fr/en fusionnés dans
  `lib/i18n` ; navigation du dossier (« Prévision de trésorerie », `treasury:read`).
- Permissions : consultation `treasury:read` (visible pour les rôles de lecture,
  cohérent avec la section Trésorerie de la 3A), écritures (seuils, figeage)
  `treasury:manage` — adoptées selon le guide d'intégration §2-5 (le main réel
  expose des permissions plus fines que `entries:*`).
- Documentation : `docs/PLAN.md` (3E cochée), `docs/DEMO.md` (étape 9),
  `AUDIT_SUIVI_20261109.md` §28.

**Adaptations au `main` réel** (guide d'intégration §2) : registre des routeurs
(`cashflow` entre statements et exports), registre des modèles (`db/models.py`),
migration renumérotée, fusion i18n, fusion DAL (4 fonctions dans `dal.ts`),
lien de navigation, permissions treasury:read/manage, contrat OpenAPI + types TS
régénérés (addition pure : 5 chemins cashflow + schémas dédiés).

**Preuves locales (uv, Python 3.13.18 — 12/11/2026)**
- pytest moteur : **40/40** ; ruff check : All checks passed ; ruff format --check :
  183 fichiers OK ; **mypy strict : Success, 168 fichiers**.
- Frontend : `tsc --noEmit` strict **0 erreur** (après typegen) ; ESLint
  `--max-warnings=0` **0 problème** ; **vitest 69/69** (dont 7 cashflow + 2 exports
  prévisions) ; contrat OpenAPI régénéré et `schema.ts` resynchronisés.
- Corrections apportées lors de l'adaptation : signature `formatMoney` du main
  (`number | bigint`), variants Badge du composant `ui/badge` (`statusVariant`),
  `noUncheckedIndexedAccess` (reduce typé, accès gardés), props `ExportLinks`
  remplacées par `previsionsExportHref` + liste blanche, import `getCompany`
  manquant, accès `company.company.currency`.

**Reste**
- Tests d'intégration `tests/test_cashflow.py` (base réelle requise) et E2E : à
  exécuter sur la pile Docker / CI à la revue du PR (quotas Actions — voir
  REVUE_INITIALE_20261112.md).
- Écrans de figeage d'instantané et de réglage des seuils (l'API est prête,
  `POST /cashflow/snapshots` et `PUT /cashflow/settings`) : PR de suivi.
- Enrichissement `seed_demo` (chèque post-daté +10 j, brouillon fournisseur +25 j)
  : PR de suivi après vérification déterministe sur base réelle.

## 2026-11-12 — C2 : guide de démarrage Windows (Git Bash) dans docs/DEMO.md

**Livré**
- `docs/DEMO.md` §5 « Démarrage Windows (Git Bash) » : correspondances Ubuntu ↔
  Windows (`MSYS_NO_PATHCONV=1`, `docker compose exec -T`, conteneur durci),
  installation GNU Make (winget), démarrage complet sans Make, diagnostic des
  cinq pannes déjà rencontrées (résolues), vérification des 3 rôles, isolation
  de la démonstration prospects.
- Commandes **exécutées et validées** en session du 12/11/2026 (Windows 11 +
  Git Bash + Docker Desktop/WSL 2) — voir AUDIT_SUIVI_20261109.md.

**Reste**
- ~~Correctif `resolve_out_dir`~~ : fait — la note du §5.3 est passée au présent
  lors de la fusion conjointe des PR demo-docs et seed-outdir (repli désormais
  automatique, §4).

## 2026-11-12 — C3 : seed_demo tolérant aux conteneurs durcis (resolve_out_dir)

**Livré**
- `kora.scripts.seed_demo` : `resolve_out_dir()` — sonde d'écriture, repli
  automatique `/tmp/kora-demo` + consigne `docker compose cp` affichée sur
  stdout si le répertoire demandé est refusé (conteneur durci : `/app` en
  lecture seule), `OSError` honnête si même le repli échoue (aucune perte
  silencieuse). Appelé dès `main()` : fail fast avant tout travail.
- `tests/test_seed_demo_out_dir.py` : 5 tests unitaires (sans base ; 2 skipif
  sur Windows — chmod de répertoire sans effet —, voie heureuse couverte partout).
- `docs/DEMO.md` §4 : comportement automatique documenté (fin du contournement
  manuel `--out /tmp/demo`) ; `AUDIT_SUIVI_20261109.md` §27.

**Preuve (locale)**
- Fonction exécutée sur les 3 cas (répertoire OK ; chmod 0o555 → repli + consigne ;
  repli chmod 0o555 → OSError) : 3/3 verts en session du 12/11/2026.
- `python -m pytest tests/test_seed_demo_out_dir.py -q` : 5 passed
  (uv, exécution du jour — voir PR).

**Reste**
- ~~Note §5.3 du guide Windows~~ : fait — mise au présent lors de la fusion
  conjointe des PR demo-docs et seed-outdir (voir `docs/DEMO.md` §5.3/§5.4).

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

## 2026-10-24 — Phase 1g : emails (mot de passe oublié, vérification, invitations)

**Décision** : sans préférence de l'utilisateur sur le fournisseur, envoi **SMTP générique**
(Brevo, Mailgun, SES, Postmark… par configuration) ; Mailpit v1.31.3 en local et en E2E.

**Livré**
- Migration 0004 : `email_tokens` (jetons à usage unique, empreinte SHA-256) et
  `invitations` (une seule en attente par adresse et par dossier).
- Worker : `request_password_reset`, `send_email_verification`, `notify_password_changed`,
  `send_invitation`, puis `deliver_email` (8 réessais espacés de 10 s à 30 min).
- API : `POST /auth/password/forgot` (202 toujours), `/auth/password/reset`,
  `/auth/email/verify`, `/auth/email/verification` (renvoi) ; `UserOut.email_verified` ;
  `POST /companies/{id}/members` renvoie `member` ou `invited` ;
  `GET/POST resend/DELETE /companies/{id}/invitations…` ; `/invitations/preview|accept|join`.
- Notification par email après tout changement ou réinitialisation de mot de passe.
- Garde-fous : quotas Redis (3 emails de compte/h, 20 invitations/dossier/24 h), invitant
  à l'adresse vérifiée, échappement HTML et anti-injection d'en-têtes, configuration
  refusée en production si SMTP non chiffré ou URL non https, boîte mémoire réservée aux tests.
- Web : pages `/mot-de-passe-oublie`, `/reinitialisation-mot-de-passe`,
  `/verification-email`, `/invitation` ; bandeau « confirmez votre adresse » avec renvoi ;
  invitations en attente (renvoyer, annuler) sur la page Utilisateurs ; FR/EN.

**Vérifié**
- `make check` : ruff, mypy strict, **219 tests pytest** (dont SMTP réel contre Mailpit),
  ESLint, tsc, 28 tests Vitest, contrat à jour ; `make web-build` OK.
- `make e2e` : **32/32, trois fois de suite** (desktop + Pixel 5), dont 4 nouveaux
  parcours qui lisent les vrais emails dans Mailpit.
- Les nouvelles routes tenant sont couvertes automatiquement par les tests d'isolation
  (404 cross-tenant, 401 sans session) + tests IDOR dédiés aux invitations.
- Revue visuelle mobile/desktop des nouveaux écrans.

**Reste à faire**
- Choisir le fournisseur SMTP de production et authentifier le domaine d'envoi
  (SPF, DKIM, DMARC) : à faire par l'utilisateur.
- Invitations côté cabinet (phase 8) ; changement d'adresse email (non prévu à ce stade).
- Tableau des membres : sur mobile, la colonne Actions impose un défilement horizontal
  (antérieur à 1g).
- Toujours en suspens depuis la phase 1 : messages d'erreur API traduits, vérification
  planifiée de la chaîne d'audit + ancrage externe, CI jamais exécutée sur GitHub.

## 2026-10-24 — Mise en ligne GitHub et CI

- Dépôt privé https://github.com/skaba89/kora-finance créé, `main` poussée.
- Premier run CI : échec du job « Contrat » — sur machine vierge, le journal du build
  Docker se mêlait au contrat exporté. Corrigé (`scripts/check-contract.sh` : image
  construite d'abord, export validé). Run suivant : **6/6 jobs verts**.
- Protection de branche : **non active** (GitHub Pro requis pour un dépôt privé).
  Livraisons désormais par branche + pull request, fusion après CI verte.

## 2026-10-24 — Phase 2a : journaux et saisie en partie double

**Livré**
- Migration 0005 : `journals`, `journal_entries`, `journal_lines`, `journal_sequences`
  (RLS FORCE), clés étrangères composites `(tenant_id, id)`, déclencheurs : création en
  brouillon uniquement, validation refusée si déséquilibrée (< 2 lignes, ∑D ≠ ∑C, total
  nul), écriture validée et ses lignes ni modifiables ni supprimables (tout rôle).
  Journaux par défaut ajoutés aux dossiers existants.
- Service : brouillons (création idempotente par identifiant client), validation
  (équilibre, exercice ouvert, comptes actifs et non regroupés, à-nouveaux au 1er jour),
  numéro sans trou par journal et exercice, contre-passation liée ; audit `entry.posted`,
  `entry.reversed`, `journal.*`.
- Permissions `journals:manage`, `entries:read|write|post` (docs/PERMISSIONS.md régénéré).
- API : `/journals`, `/entries` (filtres, pagination, totaux de page en une requête),
  `/entries/{id}/post|reversal` ; montants en chaînes (`Money`).
- Web : liste filtrée, saisie (lignes dynamiques, recherche de compte, écart en BigInt),
  détail, validation, suppression de brouillon, contre-passation, page Journaux.

**Vérifié**
- `make check` : **289 tests pytest** dont 40 séquences Hypothesis (aucun déséquilibre,
  numérotation continue), 20 validations simultanées (numéros 1..20 sans doublon),
  déclencheurs testés avec le rôle applicatif **et** le propriétaire ; 35 tests Vitest.
- `make e2e` : **36/36, trois fois de suite** ; revue visuelle mobile/desktop.
- Bug trouvé par les E2E : `crypto.randomUUID` absent hors HTTPS → `lib/uuid.ts`.

**Reste à faire (phase 2)** : 2b balance et grand livre, 2c lettrage, 2d clôture et
à-nouveaux, 2e états financiers, 2f exports, 2g pièces jointes et hors-ligne.

## 2026-10-24 — Phase 2b : balance générale et grand livre

**Livré**
- `accounting/reports.py` : balance à six colonnes (ouverture, mouvements, clôture) en
  une requête agrégée ; grand livre d'un compte avec solde progressif (fonction de
  fenêtre, NUMERIC) exact sur chaque page. Écritures validées uniquement ; à-nouveaux
  toujours dans l'ouverture.
- API `GET /trial-balance` (filtres classe, préfixe, comptes sans mouvement ; indicateur
  `balanced`, null si filtré) et `GET /ledger` ; soldes signés en chaîne.
- Web : pages Balance (sous-totaux par classe en BigInt, lien vers le grand livre) et
  Grand livre (pagination) ; présentation en fiches sur téléphone.

**Vérifié**
- Jeu de référence calculé à la main (à-nouveaux, vente avec TVA, achat, encaissement,
  brouillon exclu) ; concordance balance ↔ grand livre sur 25 écritures aléatoires ;
  pagination du solde progressif ; isolation (routes couvertes automatiquement).
- Revue visuelle : la balance à 6 colonnes débordait sur téléphone → fiches par compte.

**À valider par un expert-comptable** : présentation de la balance, traitement des
à-nouveaux dans l'ouverture.

## 2026-10-24 — Phase 2c : lettrage des comptes de tiers

**Livré**
- Migration 0006 : `letterings` + `lettering_lines` (RLS FORCE, clés composites) ;
  déclencheur de contrainte **différé** : ≥ 2 lignes validées du compte lettré, somme nulle.
- Service : lettrage manuel (contrôles explicites, code A, B, … AA par compte, numérotation
  sous verrou), délettrage, lettrage automatique par référence de pièce (casse et espaces
  ignorés) ; audit `lettering.created|deleted`. Permission `lettering:manage`.
- API : `GET /lettering/lines` (tous exercices, solde non lettré), `POST /letterings`,
  `POST /letterings/auto`, `DELETE /letterings/{id}`.
- Web : page Lettrage (cases à cocher, écart en BigInt, bouton actif à écart nul, groupes
  lettrés avec délettrage, pagination).

**Vérifié** : tests du service, de la base (lettrage déséquilibré ou sur un autre compte
refusé au commit), IDOR, matrice des permissions ; E2E desktop + mobile ; revue mobile.

## 2026-10-24 — Phase 2d : verrouillage, clôture, à-nouveaux, réouverture

**Livré**
- Migration 0007 : `fiscal_years.locked_until`, `journal_entries.origin` (MANUAL/CLOSING) ;
  déclencheur réécrit : création, modification et validation refusées dans un exercice
  clôturé ou une période verrouillée (tout rôle).
- `accounting/closing.py` : verrouillage (refusé s'il reste des brouillons ; reculer la date
  exige `fiscal_years:close`), contrôle préalable sans effet, clôture (aucun brouillon,
  exercice suivant ouvert, à-nouveaux classes 1–5 + résultat 131/139 dans le journal AN au
  1er jour), réouverture par contre-passation des à-nouveaux générés.
- Lettrage : les à-nouveaux générés sont exclus (le solde n'est pas compté deux fois) ; les
  factures et règlements restent lettrables d'un exercice à l'autre.
- API : `POST …/fiscal-years/{id}/lock|closing|reopening`, `GET …/closing-check`.
- Web : page Exercices (une carte par exercice : verrouillage, résultat, blocages, clôture,
  réouverture).

**Vérifié** : critère d'acceptation « les à-nouveaux reproduisent exactement le bilan de
clôture » testé compte par compte ; bénéfice (131) et perte (139) ; réouverture puis
nouvelle clôture après correction ; réouverture refusée si l'exercice suivant est clôturé ;
déclencheur testé en SQL direct ; matrice des permissions ; E2E desktop + mobile.

## 2026-10-24 — Phase 2e : bilan et compte de résultat

**Livré**
- Référentiels versionnés `SYSCOHADA_REVISE_2017_ETATS_V1` : postes AD…BZ, CA…DZ, TA…XI
  avec formules des totaux (`etats_syscohada_2017.csv`) ; affectation des comptes par
  préfixe le plus long et sens du solde, avec une note par choix incertain
  (`etats_affectations_2017.csv`). Validés au chargement (codes, formules, ordre).
- `accounting/statements.py` : calcul sur écritures validées à une date ; colonnes brut,
  amortissements et dépréciations, net à l'actif ; résultat de la période ajouté à CJ ;
  comptes non affectés listés. API `GET /financial-statements` avec comparatif N-1.
- Web : page États financiers (Bilan / Compte de résultat), postes vides masqués par
  défaut, fiches sur téléphone, avertissement « à valider par un expert-comptable ».

**Vérifié** : chaque compte du plan affecté au bon état ; XI se développe exactement en
produits − charges ; BZ et DZ couvrent chaque poste une fois ; jeu de référence calculé à
la main (y compris amortissement et découvert bancaire) ; comparatif N-1 après clôture ;
bilan équilibré sur 40 écritures aléatoires couvrant tout le plan.

**Reste** : TFT (2e-bis), exports PDF/Excel (2f), pièces jointes et hors-ligne (2g).

## 2026-10-24 — Phase 2f : exports PDF et Excel

**Livré**
- Dépendances (provenance vérifiée, versions de plus de deux semaines) : openpyxl 3.1.5 (MIT),
  reportlab 5.0.1 (BSD ; la 5.1.0 avait deux jours), stubs de typage ; police
  `fonts-dejavu-core` installée dans les images.
- `kora/exports` : document neutre (sections, colonnes, lignes de total) rendu en Excel
  (montants numériques, format #,##0, dates réelles) ou en PDF A4 (en-tête RCCM/NIF,
  mentions, « Page x / y »). Balance, grand livre (un compte ou tous, en deux requêtes),
  journal des écritures, états financiers (actif, passif, compte de résultat, N-1).
- API `GET /exports/{trial-balance|ledger|entries|financial-statements}?format=pdf|xlsx` ;
  chaque export tracé (`export.generated`) ; PDF refusé au-delà de 20 000 lignes.
- Web : route de téléchargement BFF (flux), boutons PDF / Excel sur Balance, Grand livre,
  Écritures, États financiers.

**Vérifié** : contenus Excel recoupés avec l'API (montants numériques), PDF valides,
nom de fichier sans accent ni balise (bogue trouvé : les lettres accentuées étaient
supprimées → normalisation NFKD), téléchargements réels en E2E ; PDF rendus en image et
relus (colonne « Réf. » élargie, zéros des lignes de détail masqués).

## 2026-10-25 — Phase 2g1 : pièces justificatives

**Livré**
- Stockage S3 local : Garage v2.4.1 (image officielle, publiée le 8 septembre), service
  `storage` + `storage-init` (`infra/garage/bootstrap.py`, API d'administration, idempotent).
  Buckets `kora` et `kora-test`. Secrets Garage et clé S3 générés par `make env`, qui
  complète désormais un `.env` existant sans toucher aux valeurs présentes.
- Dépendances : boto3 / botocore 1.43.111 (Amazon, Apache-2.0, publiés le 9 octobre ;
  versions quotidiennes → version exacte), stubs `types-boto3[s3]`.
- `kora/storage` : chiffrement AES-256-GCM par l'application (clé par objet, enveloppée par
  `KORA_ENCRYPTION_KEYS`, nom de l'objet authentifié). `kora/attachments` : type lu dans le
  contenu (PDF/JPEG/PNG/WebP), 10 Mo, 20 pièces par écriture, dédoublonnage SHA-256,
  intégrité vérifiée à chaque lecture, audit `attachment.added` / `attachment.removed`.
- Migration 0008 : table `attachments` (RLS), déclencheur : pièce jamais modifiée, non
  supprimable si l'écriture est validée. Suppression d'un brouillon = pièces purgées ;
  objet non supprimable sur le moment → tâche worker `delete_stored_object` (réessais).
- API : `POST/GET /entries/{id}/attachments`, `GET /attachments/{id}/content`,
  `DELETE /attachments/{id}` (lecture : `entries:read`, écriture : `entries:write`).
- Web : section « Pièces justificatives » sur la fiche d'écriture (brouillon et validée),
  photos réduites dans le navigateur avant l'envoi, consultation par route BFF.
- Production : `KORA_S3_ENDPOINT_URL` en https:// obligatoire (tests de configuration).

**Vérifié** : contre le vrai Garage — objet chiffré (aucun octet du PDF lisible), altération
et substitution d'objet détectées (409), purge après échec en base, retrait différé si le
stockage ne répond pas, conservation imposée par PostgreSQL (rôle applicatif et
propriétaire), lecteur sans droit d'écriture, isolation entre dossiers. E2E desktop +
mobile : PDF, photo de 1 Mo réduite en JPEG, réessai sans doublon, faux PDF refusé,
téléchargement, retrait, conservation après validation.

- `make storage-check` / `python -m kora.scripts.check_storage` : vérification d'un stockage
  (écriture, relecture, chiffrement, suppression de toutes les versions), alerte si http
  ou clé non restreinte. L'utilisateur crée un bucket Backblaze B2 pour la production.

**Reste** : configurer le bucket B2 de production (privé, sans Object Lock, « Keep only the
last version », clé limitée au bucket) et lancer la vérification ; quota de stockage par dossier (avec les abonnements, phase 8) ; aperçu des PDF
dans le navigateur selon sa politique CSP (le téléchargement fonctionne partout) ;
purge des objets orphelins si worker et stockage sont tous deux indisponibles (journalisé
en erreur) ; 2g2 saisie guidée, 2g3 brouillons hors connexion.

## 2026-10-25 — Phase 2g2 : saisie guidée

**Livré**
- `accounting/guided.py` : 7 opérations (vente encaissée, facture client, règlement client,
  dépense payée, facture fournisseur, règlement fournisseur, virement entre comptes) →
  écriture en partie double. Natures des recettes (5) et des dépenses (14) dans
  `data/saisie_guidee_v1.csv` (compte, TVA possible, note), référence `SAISIE_GUIDEE_V1`.
- Comptes proposés = comptes d'imputation actifs du dossier (un sous-compte 5521 remplace
  552) ; trésorerie 52/55/57, clients 411, fournisseurs 401 ; journal VT/AC ou BQ/MM/CA.
- TVA : montant TTC, taux TVA_NORMAL daté du dossier, comptes du taux (4431 / 4452),
  avertissement tant que le taux n'est pas vérifié auprès de la DGI.
- API `GET /guided-entries/options`, `POST /guided-entries/preview`, `POST /guided-entries`
  (brouillon, idempotent par identifiant client) ; permission `entries:write`.
- Web : page « Saisie guidée » (choix de l'opération en cartes, formulaire, aperçu de
  l'écriture, enregistrement en brouillon ou validation directe si `entries:post`).

**Vérifié** : chaque opération (lignes, journal, libellé), ventilation de la TVA, sous-comptes,
refus des choix incohérents (nature d'un autre sens, compte client utilisé comme fournisseur,
TVA sur une assurance, virement vers le même compte, journal désactivé, date hors exercice),
idempotence, droits ; propriété : toute opération, tout montant, tout taux → écriture
équilibrée. E2E desktop + mobile.

**Reste** : salaires et emprunts (non couverts : charges sociales et intérêts à paramétrer),
choix de 4432/4454 pour la TVA sur services, validation de toutes les correspondances par
un expert-comptable ; 2g3 brouillons hors connexion.

## 2026-10-25 — Déploiement sur VPS (préparation)

**Décisions de l'utilisateur** : VPS OVH dédié à Kora (le serveur de dev héberge
gestion-scolaire-pro, dont le Caddy tient les ports 80/443 : on n'y touche pas), pas
encore de domaine, emails plus tard.

**Livré**
- `KORA_EMAIL_BACKEND=disabled` : aucun envoi, avertissement journalisé (sujet seulement) ;
  page « mot de passe oublié » et bandeau d'adresse non confirmée le signalent.
- `deploy/vps/` : pile de production (Caddy 2.11.6 seul exposé, HSTS, corps limité à
  12 Mo), modèle `env.example` + `init-env.sh` (secrets générés, champs à remplir),
  `bootstrap-server.sh` (Docker officiel, ufw, unattended-upgrades, fail2ban, swap, SSH
  par clé), `deploy.sh` (main, build, vérification du stockage, migrations, démarrage),
  `backup.sh` / `restore.sh` / minuterie systemd quotidienne.
- `kora.scripts.backup` : envoi chiffré vérifié, liste, téléchargement, purge.
- `scripts/init-env.sh` accepte un modèle et une cible. Guide `docs/DEPLOIEMENT.md`.

**Vérifié** : 4 tests de sauvegarde (Garage) ; cycle réel sur la base de dev (dump de
16 Mo → chiffré → téléchargé identique → restauré deux fois dans une base séparée, mêmes
comptages, 6 déclencheurs et RLS forcée présents) ; pile de production lancée à blanc en
`KORA_ENV=production` derrière Caddy (HTTPS local) : services sains, en-têtes de sécurité,
API non joignable de l'extérieur, 6 parcours Playwright réussis, emails non envoyés
journalisés sans adresse ; Caddyfile validé par Caddy.

**Reste (côté utilisateur)** : commander le VPS, créer la clé B2 limitée au bucket,
suivre docs/DEPLOIEMENT.md. Ensuite : vrai domaine, fournisseur SMTP, bucket de
sauvegardes séparé avec Object Lock, supervision (alertes si la sauvegarde échoue).

## 2026-10-26 — Mise en production sur le VPS partagé, proxy commun

**Décisions de l'utilisateur** : finalement le même VPS que gestion-scolaire-pro
(51.75.248.4), à l'adresse `kora.51-75-248-4.sslip.io` ; puis séparation complète des deux
projets : les ports 80/443 passent à un proxy commun indépendant (`~/vps-proxy`, hors de
ce dépôt) au lieu du Caddy de gestion-scolaire-pro.

**En service** : pile `kora` (version 4ecdcb9) en mode proxy commun, stockage B2
`kora-bucket` avec une clé limitée au bucket (`kora-production`, sans droit sur les clés
ni les buckets), première sauvegarde chiffrée vérifiée, minuterie quotidienne installée.

**Livré** : `compose.proxy-externe.yml` rejoint le réseau externe `edge` (au lieu de
`kora-edge`, propre à l'ancien montage) ; `deploy.sh` le crée s'il manque ; section 3 bis
de docs/DEPLOIEMENT.md réécrite.

## 2026-10-26 — Phase 2g3a : saisie hors connexion (KF-17)

**Contexte** : travail externe fusionné entre-temps (audit de production PR #12 et
correctifs KF-01, KF-02, KF-04, KF-06, KF-10 : PR #13, #15 à #18), déployé en production
après sauvegarde (migration 0009, API et worker sans identifiant propriétaire).
L'utilisateur a choisi de faire 2g3 avant les P1 restants de l'audit.

**Livré**
- Page de dossier « Hors connexion » : préparer l'appareil (comptes d'imputation,
  journaux, options de saisie guidée, exercices ouverts ; valable 7 jours), suivre la file,
  synchroniser, corriger ou supprimer une saisie refusée.
- Page publique `/hors-connexion/saisie` (statique, mise en cache par le service worker) :
  saisie libre (éditeur existant) et guidée (formulaire existant, sans aperçu), rangées
  dans une file IndexedDB chiffrée (AES-256-GCM, clé non exportable, par utilisateur).
- Synchronisation automatique sur toute page connectée (chargement et retour du réseau),
  bandeau de suivi, verrou entre onglets ; brouillons créés une seule fois (identifiant de
  la saisie = clé d'idempotence déjà prévue par l'API). Aucune validation hors connexion.
- Déconnexion : avertissement s'il reste des saisies non synchronisées, puis effacement
  de tout ce que l'appareil conserve.
- Code commun extrait : `lib/payloads.ts` (corps d'écriture libre/guidée, revérifiés côté
  serveur), `components/guided/options.ts` (choix et libellés de la saisie guidée).

**Vérifié** : 16 nouveaux tests Vitest (corps, modèle de file, chiffrement) ; 4 scénarios
Playwright (ordinateur + mobile) avec coupure réelle du réseau : saisie libre et guidée
hors ligne, refus serveur (date hors exercice) puis correction, trois brouillons sans
doublon, validation en ligne (TVA calculée par le serveur) ; avertissement et effacement à
la déconnexion. Suite E2E complète : 60/60. API inchangée (idempotence et périodes déjà
couvertes par pytest).

**Reste** : 2g3b (photos de pièces hors connexion) ; P1 de l'audit (KF-03, 05, 07, 08,
09, 11, 12, 13).

## 2026-10-27 — 2h : tableau de bord et accueil

**Demande** : « je ne vois rien sur le frontend quand je me connecte ». Constat : aucune
erreur, mais un tableau de bord réduit à une liste de mise en route et une phrase
périmée (KF-18). Ordre validé par l'utilisateur : tableau de bord, puis phases 3 → 8.

**Livré**
- API `GET /companies/{id}/dashboard?on=` (`accounting/dashboard.py`, une requête
  agrégée) : trésorerie par compte (52, 53, 55, 57), chiffre d'affaires, produits,
  charges et résultat provisoire du mois et de l'exercice, clients et fournisseurs,
  évolution mensuelle, nombre de brouillons. Écritures validées uniquement.
- Page du dossier : raccourcis de saisie guidée, indicateurs, graphique mensuel
  (palette catégorielle validée, info-bulle souris et clavier, tableau des chiffres),
  trésorerie par compte, dernières écritures, mise en route seulement si incomplète.
  Phrase « … arrivent avec les prochaines étapes » supprimée (KF-18).
- Accueil : un seul dossier ⇒ arrivée directe sur son tableau de bord ; « Changer de
  dossier » ouvre la liste (`?liste=1`).

**Vérifié** : 4 tests pytest (dossier vide, indicateurs avec à-nouveaux, brouillon et
écriture postérieure exclus, date sans exercice, isolation) ; E2E tableau de bord
(ordinateur + mobile) ; rendu vérifié sur captures (ordinateur et téléphone).

## 2026-11-09 — Audit de suivi, déroutage de `main` (E2E) et revalidation locale

**Contexte** : audit de prolongement de l'audit initial (réf. `7a51c45`) demandé après
les phases 2g2, 2g3 et 2h. Premier constat : le run CI #44 (2026-10-27) est rouge sur
`main` depuis le merge de la PR #20 — `main` bloqué pour toute fusion.

**Constat et cause (E2E)** : échec déterministe de `hors-connexion.spec.ts` (profil
mobile, run #44 ; puis échec déterministe du premier itéral de correctif, run #45, les
deux profils). `LogoutButton` appelle `window.confirm` après une lecture IndexedDB : le
dialogue peut s'ouvrir après la résolution du clic. Deux `page.once("dialog")`
consécutifs recevaient alors le même dialogue — le second échouait « Cannot accept
dialog which is already handled! » et la déconnexion était annulée. Le motif retenu,
valable pour un confirm synchrone comme asynchrone :
`page.waitForEvent("dialog").then(dialog => dialog.accept()|dismiss())`, créé avant le
clic, achevé après — plus aucun `page.once` dans le fichier. Comportement produit
inchangé. → PR #21 (`fix/kora-e2e-dialog-deconnexion`).

**Revalidation locale (inédite : la suite API n'avait jamais tourné hors CI)** :
PostgreSQL 16 réel (rôles `kora_owner`/`kora_app`, extensions contrib), Redis réel,
Garage v2.4.1, Mailpit — migrations 0001→0009 puis **pytest 540/540 verts** (336 s),
Vitest 60/60, `tsc` strict et ESLint verts.

**Audit** : `AUDIT_SUIVI_20261109.md` — correctifs KF-01/02/04/06/10/17/18 vérifiés
fusionnés ; KF-03/05/07/08/09/11/12/13/15/16 toujours ouverts ; 14 constats nouveaux
(N-B1…N-I4) dont le réjeu idempotent sans comparaison de payload (P2) et les en-têtes
Caddy (P2) ; score de maturité pondéré **65/100** (plafonné par le périmètre produit :
phases 3-8 non commencées) et backlog mis à jour (§8).

**Reste** : fusionner la PR #21 ; ensuite, ordre recommandé : KF-08 (réauthentification
MFA), KF-03 (verrou d'exercice dans le trigger 0007), KF-05 (snapshot REPEATABLE READ
des rapports), KF-07 (verrou société), puis phase 3 (trésorerie/Mobile Money).

**KF-08 livré dans la foulée (même journée)** : réauthentification obligatoire pour
l'enrôlement de la 2FA (`/auth/mfa/setup` et `/enable` exigent le mot de passe ; les
quatre transitions du second facteur sont désormais sérialisées par verrou utilisateur,
comme la connexion). Web mis à jour (mot de passe demandé à l'activation et à la
confirmation, libellé fr/en explicite), contrat régénéré, 3 tests pytest nouveaux et
E2E 2FA complété — PR #23. Deux correctifs de tests ont suivi, poussés par la CI :
- le scénario de restauration synthétique envoie désormais le mot de passe aux deux
  appels d'enrôlement (422 depuis KF-08) — PR #24 ;
- le test de limitation de débit fige la fenêtre de comptage (frontière de minute :
  le compteur repartait à zéro entre deux requêtes) et purge Redis au départ — PR #24.
Suite API locale : 540/540 puis 542/542 avec les nouveaux cas. CI verte sur les deux
PRs avant fusion ; `main` vert après (#48 puis, à la clôture, run du merge #24).

## 2026-11-09 — KF-03 : verrou d'exercice contre la course clôture/validation

**Anomalie (audit de suivi, §4)** : le déclencheur `journal_entries_protect` (0005,
redéfini par 0007) relisait `fiscal_years` **sans verrou**, alors que `close()` verrouille
l'exercice (`closing._lock_year`) avant d'agréger les écritures validées pour générer les
à-nouveaux. Une validation engagée dans la fenêtre pouvait donc être commitée après le
calcul des à-nouveaux : l'exercice se fermait sans que ses lignes y figurent. Même course
pour `lock_period()` (période verrouillée).

**Preuve de la course** : `tests/test_closing_concurrency.py` — deux connexions réelles
(`kora_app`, RLS), barrières déterministes (`pg_blocking_pids`). Les deux tests « clôture
d'abord » et « verrouillage d'abord » étaient **rouges avant correctif** (la validation
concurrente ne bloquait pas), puis verts après.

**Correctif** (branche `feature/kora-kf03-verrou-exercice`) :
- migration `20261109_0010_verrou_exercice_cloture.py` : `CREATE OR REPLACE FUNCTION
  kora_ledger_protect_entry` recompile le déclencheur avec `SELECT … FOR UPDATE` sur
  `fiscal_years` (0007 inchangé ; downgrade vers la version 0007). La validation
  concurrente attend le commit de la clôture puis relit la version validée (READ
  COMMITTED) : CLOSED ou période verrouillée ⇒ refus, brouillon conservé ;
- `entries._fiscal_year_for(…, lock=True)` dans `_post` : même verrou côté application
  **avant** la numérotation — ordre de verrous uniforme « exercice puis séquence de
  journal » dans toutes les transactions (clôture, à-nouveaux, réouverture, validation),
  excluant tout interblocage avec `_next_number` ;
- un troisième test garantit l'interleaving inverse : une validation qui gagne la course
  figure dans les à-nouveaux (`ouv:521 = 5 050 000` vérifié via la balance).

**Vérifié** : suite API complète 545/545 (dont 3 nouveaux) sur l'environnement réel
(PostgreSQL 16, Redis, Garage, Mailpit) ; ruff, ruff format, mypy strict ; aucun changement
de contrat d'API (aucune route ni schéma modifié).

## 2026-11-09 — KF-05 : instantané REPEATABLE READ pour les rapports

**Anomalie (audit de suivi, §4)** : `account_ledger` (totaux puis lignes, `reports.py:192-199`
puis `:243-255`) et `full_ledger` (balance puis lignes, `:307` puis `:310-350`) lisaient
en READ COMMITTED : chaque requête voit son propre état de la base. Une écriture
validée entre deux requêtes produisait un rapport qui mélangeait deux instants —
soldes incohérents avec les lignes, voire `KeyError` quand un compte n'apparaissait que
dans les lignes (500 sur l'export de grand livre). Même risque pour les états
financiers N/N-1 et les quatre exports.

**Correctif** (branche `feature/kora-kf05-instantane-rapports`) :
- `db/snapshot.py` : `lecture_instantanee(tenant_id)` — transaction REPEATABLE READ
  dédiée sur une connexion neuve du pool ; l'option d'isolation est posée avant toute
  instruction (portée par le `BEGIN`), donc sans conflit avec le `set_config` du
  contexte tenant posé par le hook `after_begin`. Lecture seule, jamais commitée.
- `GET /ledger` (totaux+lignes), `GET /financial-statements` (N et N-1) et les quatre
  exports lisent leurs données sous un unique instantané ; le journal d'audit des
  exports et le commit restent sur la session de requête. `GET /trial-balance` tient
  en une requête : atomique, inchangé.

**Preuve** : `tests/test_reports_concurrency.py` — deux connexions réelles, barrières
déterministes (écoute `after_cursor_execute` sur la connexion du rapport ; validation
SQL directe intercalée, comme le test de clôture KF-03). Rouge avant correctif :
`KeyError(UUID('…'))` sur `full_ledger` ; totaux 5 000 000 vs lignes 7 000 000 sur
`account_ledger`. Vert après : 522 absent, totaux = lignes, solde exact.

**Vérifié** : suite API complète 547/547 (dont 2 nouveaux) sur l'environnement réel
(PostgreSQL 16.2, Redis 7.4.2, Garage v2.4.1, Mailpit v1.31.3) ; ruff, ruff format,
mypy strict. Aucun changement de contrat d'API. Score porté à 72,25/100.

**Reste** : KF-07 (verrou société), KF-09, KF-11, KF-12, KF-13, arbitrage
expert-comptable (KF-15/16), puis phase 3 (trésorerie/Mobile Money).

## 2026-11-09 — KF-07 : verrou de société contre les départs concurrents de dirigeants

**Anomalie (audit de suivi, §4)** : `_ensure_a_director_remains`
(`organization/service.py:268-283` au moment du constat) comptait les dirigeants
**sans verrou** sur la société (`session.get(Company, …)` simple, puis comptage des
`PME_DIRIGEANT`). Deux rétrogradations — ou deux retraits — simultanés de deux
dirigeants distincts comptaient chacun deux dirigeants : l'autre transaction n'était
pas encore commitée, donc invisible dans l'instantané READ COMMITTED de la première.
Les deux passes pouvaient aboutir : **dossier sans aucun dirigeant**, plus personne
autorisé à réinviter ou gérer les membres.

**Correctif** (branche `feature/kora-kf07-verrou-societe`) :
- `_ensure_a_director_remains` relit la société en `SELECT … FOR UPDATE` avant le
  comptage. La transaction concurrente attend le commit de la première, relit le
  comptage dans un instantané frais (READ COMMITTED : une requête = un instantané) et
  est refusée (`BusinessRuleError`) s'il ne reste que le membre qui part.
- Ordre de verrous « membership (via `_get_membership`) puis société » : uniforme dans
  les deux cas d'usage (`change_member_role`, `remove_member`), sans interblocage — le
  verrou de société est le dernier acquis, jamais détenu avant un autre verrou métier.
- Couvre aussi le retrait (`remove_member`) qui emprunte la même vérification.

**Preuve** : `tests/test_director_concurrency.py`, deux connexions réelles et barrière
déterministe (`pg_blocking_pids`), même motif que les tests KF-03 et KF-06.
**Rouge avant correctif** : la seconde rétrogradation ne bloquait pas et le dossier se
retrouvait avec 0 dirigeant. Vert après : la seconde démotion attend le verrou, est
refusée (`Le dossier doit conserver au moins un dirigeant.`) et le second dirigeant
est conservé. Un second test garantit le comportement séquentiel inchangé (retrait du
dernier dirigeant restant refusé après commit de la première démotion).

**Vérifié** : suite API complète **549/549** (dont 2 nouveaux) sur l'environnement réel
hors Docker (PostgreSQL 16.2, Redis 7.4.2, Garage v2.4.1, Mailpit v1.31.3) ; ruff,
ruff format, mypy strict. Aucun changement de contrat d'API (aucune route ni schéma
modifié).

**Déductions levées (§7)** : sécurité socle, seconde moitié de la course KF-03/KF-07
(−0,75) → socle 23. **Score : 73/100.** Reste prioritaire (§8) : KF-09 (bucket de
sauvegarde séparé), KF-11 (tags d'image + sauvegarde avant déploiement), KF-12
(supervision des sauvegardes), KF-13 (budgets et quotas), l'arbitrage
expert-comptable (KF-15/16) et la phase 3 (trésorerie/Mobile Money).

## 2026-11-09 — KF-09 : bucket et clé de sauvegarde séparés, purge sous clé d'administration

**Anomalie (audit de suivi, §4)** : les sauvegardes utilisaient `objects._client()` —
le même client S3, le même bucket et la même clé que les pièces justificatives
(`scripts/backup.py`, `storage/objects.py`, `deploy/vps/compose.yml` transmettant ces
identifiants à API et worker) ; `prune --keep-days 30` était même appelé
automatiquement chaque nuit par backup.sh. Le chiffrement protégeait la
confidentialité, pas la suppression : une application compromise (API ou worker)
pouvait détruire les pièces ET toutes leurs sauvegardes.

**Correctif** (branche `feature/kora-kf09-bucket-sauvegarde`) :

- `storage/backups_store.py` : client boto3 dédié, construit sur `BackupSettings`
  (`KORA_BACKUP_S3_*`, préfixe disjoint de la configuration runtime) — autre bucket,
  autre clé, et volontairement **aucune fonction de suppression**.
- `core/config.py` : classes séparées `BackupSettings` et `BackupAdminSettings`,
  lues uniquement par les outils de sauvegarde ; l'API et le worker ne reçoivent
  jamais ces variables.
- `scripts/backup.py` : upload/list/download passent par le stockage dédié (relecture
  SHA-256 inchangée) ; la purge `prune` exige désormais la clé d'administration
  **distincte** `KORA_BACKUP_ADMIN_S3_*` (jamais déployée sur le VPS) et garde le
  plancher des sept plus récentes ; sans cette clé elle est refusée, rien n'est
  supprimé.
- Compose (local et VPS) : service one-shot `backup` sous profil, seul destinataire
  de `KORA_BACKUP_S3_*` ; `backup.sh` et `restore.sh` passent par ce service.
- `backup.sh` : purge automatique supprimée — la rétention est administrée côté
  fournisseur (cycle de vie du bucket, Object Lock B2/S3 à dimensionner).
- `infra/garage/bootstrap.py` : bucket `kora-backups` et clé de sauvegarde dédiés, la
  clé de l'API n'y a jamais accès (étape sautée sans `S3_BACKUP_*`) ; `.env.example`
  et `deploy/vps/env.example` complétés ; `docs/DEPLOIEMENT.md` §5 réécrit (prérequis
  fournisseur : second bucket, clé sans droit de suppression, clé admin séquestrée
  hors serveur).

**Preuve** : `tests/test_backup.py` (7 tests contre le Garage réel, bucket de
sauvegarde distinct du bucket des pièces) et `tests/test_backup_isolation.py`
(6 tests de contrat : aucune composition ne transmet `KORA_BACKUP_*` aux services
applicatifs — api, worker, migrate, web, ni l'ancrage `x-api-env` ; le service
`backup` ne reçoit pas les identifiants des pièces ; `backup.sh` ne purge plus ;
modèles d'env complets ; préfixes de configuration disjoints). Le test d'acceptation
de l'audit est codé : avec les identifiants de l'application, la suppression d'une
sauvegarde (même clé d'objet) la laisse intacte ; sans clé d'administration, la purge
est refusée. Suite API exécutée intégralement sur l'environnement réel hors Docker
(PostgreSQL 16.15, Redis via fakeredis 2.34.1, Garage v2.4.1, Mailpit) :
**558/558** (dont 9 nouveaux), ruff, ruff format, mypy strict. Aucun changement de
contrat d'API (aucune route ni schéma modifié).

**Déductions levées (§7)** : sécurité socle, KF-09 (−1,5) → socle 24,5. **Score :
74,5/100.** Reste prioritaire (§8) : KF-11 (tags d'image + sauvegarde vérifiée avant
déploiement), KF-12 (supervision des sauvegardes), KF-13 (budgets et quotas),
l'arbitrage expert-comptable (KF-15/16) et la phase 3 (trésorerie/Mobile Money).

## 2026-11-09 — KF-11 : déploiement versionné, sauvegarde pré-migration imposée, rollback

**Anomalie (audit de suivi, §4 et §6)** : `deploy.sh` avançait `main`, reconstruisait
les images **sous le même tag mobile** `kora-api:prod` / `kora-web:prod` puis lançait
`compose up` et les migrations — sans copie git propre exigée, sans sauvegarde
pré-migration imposée, sans consignation de version, sans procédure de retour
arrière. Une migration refusée ou un healthcheck échoué laissait les conteneurs
précédents en place mais les tags locaux déjà écrasés : redémarrer (crash, reboot)
relançait la nouvelle image sans avoir validé la bascule, et revenir en arrière
dépendait des registres du moment.

**Correctif** (branche `feature/kora-kf11-deploiement-versionne`) :

- `deploy/vps/compose.yml` : images applicatives étiquetées par
  `${KORA_IMAGE_TAG:-prod}` (migrate, api, worker, backup, web).
- `deploy.sh` réécrit : pré-vols (`.env`, `main`, **copie git propre**, ff-only
  origin/main — commit déployé = commit CI-vert par protection de branche) ; release
  = SHA court 12 (`kora-api:<sha>`, `kora-web:<sha>`) ; `check_storage` sur la
  nouvelle version ; **sauvegarde pré-migration vérifiée imposée** (`backup.sh` sur
  l'image en cours ; première installation passée avec avertissement) ;
  `up -d --wait` ; **retour automatique** à la version précédente en cas d'échec ;
  consignation `releases.log` + `.release` / `.previous-release` ; rétention des cinq
  dernières releases.
- `rollback.sh` (nouveau) : retour à `.previous-release`, refus sans version connue,
  inspection des images avant relance.
- `backup.sh` / `restore.sh` : image épinglée sur `.release` (fallback `:prod`).
- `scripts/check-deploy-versioning.py` (nouveau, CI job API) : contrats mécaniques
  (tags paramétrés, `:prod` en dur interdit, étapes obligatoires, `bash -n`).
- `.gitignore` : `releases.log`, `.release`, `.previous-release`.
- `docs/DEPLOIEMENT.md` : §4 réécrit (release en cinq étapes, rollback, convention
  **expand/contract**), Dépannage complété.

**Vérifié**
- `python3 scripts/check-deploy-versioning.py` → code 0 (contrats + `bash -n` des
  quatre scripts).
- Suite API complète sur l'environnement réel hors Docker (PostgreSQL 16.4, Redis
  7.4.5, Garage v2.4.1 — bucket `kora-backups` créé —, Mailpit v1.33.1 aligné sur le
  Compose : variables `MP_SMTP_AUTH_*`) : **558/558**. Au passage, l'environnement de
  test local a été reconstruit après recyclage du sandbox (binaires PostgreSQL/Redis/
  Garage/Mailpit réinstallés, `scripts/api-test-env.sh` ajouté) ; l'échec initial de
  `test_envoi_smtp_reel` était un défaut d'environnement (Mailpit sans AUTH
  accepté), pas du code.
- Aucun changement de contrat d'API (aucun endpoint touché).

**Reste** : exercice complet sur staging réel (migration refusée, build indisponible,
healthcheck échoué → retour à la version connue) en attente d'accès hébergeur ;
déduction résiduelle −0,5 maintenue dans le suivi (§15). Prochaines priorités :
**KF-12** (supervision des sauvegardes), **KF-13** (budgets et quotas).

## 2026-11-10 — KF-12 : supervision des sauvegardes et de l'application

**Constat** (audit §4, P1) : la supervision se limitait aux healthchecks Compose et aux
logs. L'unité `kora-backup.service` était un oneshot sans `OnFailure=` : l'échec de la
sauvegarde quotidienne restait dans le journal sans prévenir — des jours sans sauvegarde
pouvaient s'accumuler en silence (panne du fournisseur S3, disque plein, image cassée).
Aucune sonde externe de l'application, aucun contrôle de fraîcheur de la dernière
sauvegarde (timer désactivé = sauvegardes qui s'arrêtent sans aucune erreur nulle part).

**Correctif** (branche `feature/kora-kf12-supervision-sauvegardes`) :

- `OnFailure=kora-alert@%n.service` sur `kora-backup.service` ;
- `kora-alert@.service` + `alert.sh` : trace horodatée locale
  (`backups/alertes/journal.log`) puis email d'exploitation via le conteneur `backup`
  (`python -m kora.scripts.notify`, nouveau script ; destinataire `KORA_ALERT_EMAIL`,
  nouveau réglage `alert_email`) ; anti-tempête 1 email / unité / 4 h ;
- contrôle de fraîcheur quotidien 03:45 UTC (`kora-freshness.timer` →
  `backup-status.sh` → nouvelle sous-commande `backup status --max-age-hours 26` :
  la plus récente sauvegarde du bucket dédié doit dater de moins de 26 h) ;
- sonde externe toutes les 5 minutes (`kora-probe.timer` → `probe.sh` →
  `https://<domaine>/health/ready`, deux échecs consécutifs → alerte, compteur remis à
  zéro au premier succès) ; `Caddyfile` : route étroite `handle /health/*` vers l'API —
  les sondes sont le seul chemin d'API exposé publiquement (statut ok|erreur, aucune
  donnée métier) ; le certificat TLS est couvert par la sonde ;
- `install-backup-timer.sh` : installe les sept unités d'un geste ;
- `scripts/check-supervision.py` (nouveau, CI) : contrats mécaniques (`OnFailure=`,
  timers, épinglage de release, `notify`, route Caddy, `KORA_ALERT_EMAIL` partout où
  requis, `bash -n`) ; `notify.py` honnête (ne prétend pas envoyer sans destinataire ou
  avec le backend désactivé ; HTML échappé) ;
- `deploy/vps/env.example` + `compose.yml` + `docker-compose.yml` :
  `KORA_ALERT_EMAIL` documenté et transmis au conteneur `backup`.

**Vérifié** : `python3 scripts/check-supervision.py` → code 0 ; suite API complète sur
l'environnement réel hors Docker (PostgreSQL 16.4, Redis 8.0.2, Garage v2.4.1 — bucket
`kora-backups` + clé dédiée —, Mailpit v1.33.1) : **567/567** dont 9 nouveaux (fraîcheur
: récent OK, trop ancienne refusée en fonction et en CLI, bucket vide refusé ;
notification : destinataire, échappement HTML, refus sans destinataire, refus honnête
backend désactivé, usage incomplet). Aucun changement de contrat d'API.

**Reste** : recevoir réellement un email d'alerte sur un VPS (arrêt de
`kora-backup.timer`, sonde rouge pendant une coupure) — accès hébergeur requis ; même
limite que KF-09 (Object Lock) et KF-11 (staging) ; déduction résiduelle −0,5.
Suivi : `AUDIT_SUIVI_20261109.md` §16. **Score : 77,5/100** (KF-12 : −2 → −0,5).
Prochaines priorités : **KF-13** (quota Redis des exports, `mem_limit`/`cpus`), KF-23
(contrôles taille/chemin des sauvegardes), KF-20 (SCA en CI), arbitrage expert-comptable
(KF-15/16), phase 3 (trésorerie/Mobile Money).

## 2026-11-10 — KF-13 : budgets de ressources et quotas d'exports

**Constat** (audit §4, P1) : exports synchrones sans rate limit ni quota (seule borne
`MAX_PDF_ROWS`), rendu PDF/Excel entièrement en mémoire ; aucun `mem_limit`/`cpus` sur
les conteneurs. Quelques requêtes automatisées suffisaient à saturer l'API ; un
conteneur fugueur pouvait affamer ses voisins ou l'hôte.

**Correctif** (branche `feature/kora-kf13-budgets-quotas`) :

- compteur Redis à fenêtre fixe généralisé : `kora/core/quota.py` (nouveau, fail-closed
  — panne Redis = exception, jamais de contournement silencieux), `email/quota.py`
  supprimé (invitations et récupération passent par le module commun, sans changement
  de comportement) ;
- exports : compteurs `export-user` (30/h) puis `export-company` (120/h), réglages
  `KORA_EXPORTS_PER_USER_PER_HOUR` / `KORA_EXPORTS_PER_COMPANY_PER_HOUR` ; dépassement
  → `429` + `Retry-After`, documenté dans le contrat des 4 endpoints exports ;
- les deux Compose : `deploy.resources.limits` (mémoire + CPU) sur chaque service de
  production (postgres 1g, redis 256m + `--maxmemory 200mb noeviction`, api/worker/
  backup/storage 512m, web 512m, migrate 256m, mailpit/storage-init/caddy bornés) ;
  outils de développement (profils tools/e2e) explicitement hors budget ;
  `KORA_EXPORTS_*` documentés dans `.env.example` et `deploy/vps/env.example` ;
- `scripts/check-compose-budgets.py` (nouveau, CI) : budgets attendus par service
  (changement = décision explicite au diff), maxmemory Redis, contrat quota.

**Vérifié** : suite API complète hors Docker : **573/573** dont 6 nouveaux
(`tests/test_exports_quota.py` : 429 + Retry-After, second membre bloqué par le quota
du dossier, dossiers comptés séparément, panne Redis échoue fermé, comptage par
fenêtre, panne Redis sur le module). `python3 scripts/check-compose-budgets.py` →
code 0. Contrat régénéré : `429` sur les 4 endpoints exports (openapi.json +
schema.ts, aucun autre changement). Aucune migration de base.

**Reste** : budgets à affiner avec la charge réelle de staging (déjà compté sous
KF-11) ; déduction résiduelle 0. Suivi : `AUDIT_SUIVI_20261109.md` §17.
**Score : 79/100** (KF-13 : −1,5 → 0). Prochaines priorités : KF-23 (contrôles
taille/chemin des sauvegardes), KF-20 (SCA/SBOM en CI), arbitrage expert-comptable
(KF-15/16), phase 3 (trésorerie/Mobile Money).

## 2026-11-10 — KF-23 : contrôles de taille et de chemin des sauvegardes

**Constat** (audit §4, P2) : sauvegarde chargée intégralement avant contrôle de
taille ; chemin de restauration sans contrôle ; aucun test de dépassement.

**Correctif** (branche `feature/kora-kf23-controles-sauvegarde`) :

- `backup.py` : `stat()` avant toute lecture (fichier régulier exigé, taille comparée
  au plafond AVANT chargement) ; plafond réglable `KORA_BACKUP_S3_MAX_BYTES`
  (défaut 400 Mo, aligné sur le conteneur « backup » de KF-13) ; clés imposées au
  préfixe `backups/` ; téléchargement atomique (`.partiel` + `os.replace`) ;
- `restore.sh` : clé validée par expression régulière, signature `PGDMP` vérifiée
  avant la confirmation destructrice, `trap` qui efface le dump en clair à la sortie ;
- nouveaux réglages : `backup_max_bytes` dans `BackupSettings`.

**Vérifié** : suite API complète : **578/578** dont 5 nouveaux (plafond sans lecture,
fifo refusé, clé hors préfixe refusée, répertoire refusé + atomicité, contrat
restore.sh). `bash -n` OK, garde-fous CI verts. Aucun changement de contrat d'API,
aucune migration.

**Reste** : streaming chiffré vers S3 si les dumps dépassent un jour le plafond
(documenté dans le module). Suivi : `AUDIT_SUIVI_20261109.md` §18.
**Score : 80/100** (KF-23 : −1 → 0). Prochaines priorités : KF-20 (SCA/SBOM en CI),
arbitrage expert-comptable (KF-15/16), phase 3 (trésorerie/Mobile Money).

## 2026-11-11 — KF-20 : SCA, SBOM et scan d'images dans la CI

**Constat** (audit §4, P2) : aucun audit de dépendances dans la CI (pip-audit, npm
audit, Dependabot, trivy absents). Par ailleurs le CLI `shadcn` (générateur de code,
jamais importé à l'exécution) traînait dans les dépendances de production et y
tirait 6 vulnérabilités (deepmerge, ts-morph, minimatch).

**Correctif** (branche `feature/kora-kf20-sca-sbom`) :

- `shadcn` déplacé en devDependencies → arbre de production propre (`npm audit
  --omit=dev` : 6 → 0) ;
- Makefile : `api-audit` (pip-audit sur l'environnement verrouillé `/opt/venv`),
  `web-audit` (production sans tolérance, dev sans haut ni critique), `sbom`
  (CycloneDX API + Web), cible agrégée `sca` ;
- CI : job `sca` bloquant (SBOM en artefacts 30 jours) ajouté au « Résultat » ;
- `.github/dependabot.yml` : pip, npm, github-actions, hebdomadaire lundi 04:00
  Europe/Paris ;
- `.github/workflows/security-scan.yml` : scan hebdomadaire trivy 0.65.0 des images
  runtime (HIGH/CRITICAL corrigées uniquement, rapports 90 jours, informationnel au
  départ — documenté).

**Vérifié** : pip-audit sur l'environnement verrouillé : 0 vulnérabilité connue ;
`npm audit --omit=dev --audit-level=low` : 0 (exit 0) ; `--audit-level=high` : exit 0
(2 low, 10 moderate restantes dans l'outillage dev, aucune version corrigée
publiée) ; la gate moderate échoue (exit 1) — le verrou bloque bien. SBOM : API 76
composants (CycloneDX 1.6), Web 670 (1.7). Suite web après le déplacement de shadcn :
ESLint 0 avertissement, tsc strict, Vitest 60/60, build Next OK. YAML validés ;
`make -n sca` conforme à la CI. Aucun changement Python, aucune migration, aucun
changement de contrat d'API.

**Reste** : 12 advisories dev sous verrou haut/critique + Dependabot ; trivy
informationnel jusqu'à stabilisation de la baseline. Suivi :
`AUDIT_SUIVI_20261109.md` §19. **Score : 81/100** (KF-20 : −1 → 0).
Prochaines priorités : arbitrage expert-comptable (KF-15/16), phase 3 (trésorerie /
Mobile Money), KF-14 (CSP).

## 2026-11-11 — KF-15 : arbitrage expert-comptable et TFT en méthode directe

**Constat** (audit §4, P1) : pas de TFT ni notes annexes ; la phase 2e-bis attendait
une validation de méthode avant implémentation.

**Arbitrage** (`docs/ARBITRAGE_COMPTABLE.md`) : TFT en méthode directe — flux mesurés
sur la classe 5, classés par contrepartie ligne à ligne ; ouverture portée par les
à-nouveaux ; contrôle indépendant avec le solde réel (coherent/unmapped). Notes
annexes : livraison progressive à partir de la phase 3. KF-16 : aucun taux en dur,
mentions factures en phase 4, conservation sans suppression.

**Correctif** (branche `feature/kora-kf15-tft-arbitrage`) : référentiels
`tft_syscohada_2017.csv` + `tft_affectations_2017.csv` (76 préfixes, toutes classes
hors 5) ; `accounting/cashflows.py` ; route `/cash-flow-statement` (N et N-1 sous
instantané) ; onglet TFT dans la page états-financiers (synthèse, badge de cohérence,
N-1, sections) ; i18n fr/en ; contrat régénéré.

**Vérifié** : suite API complète hors Docker : **591/591**, dont 10 nouveaux
(`tests/test_cashflows.py` : couverture du plan, expansion des totaux, classe 5
exclue, référence, multi-contreparties, cessions/subventions, à-nouveaux + comparatif,
troncature à date, invariant sur 40 écritures aléatoires, garde-fou). Ruff, mypy
strict, ESLint, tsc strict, Vitest 60/60, build Next OK. Aucune migration de base.

**Reste** : export PDF/Excel du TFT ; charges financières payées à confirmer en revue
finale. Suivi : `AUDIT_SUIVI_20261109.md` §20. **Score : 82/100** (TFT absent :
−1 → 0). Prochaines priorités : phase 3 (trésorerie/Mobile Money), revue expert
(KF-15/16), KF-14 (CSP).

## 2026-11-11 — N-B6 : plafonds de session PostgreSQL au runtime

**Constat** (audit §5, P3) : aucun statement_timeout/lock_timeout au runtime.

**Correctif** (branche `feature/kora-nb6-timeouts-session`) : réglages
`KORA_STATEMENT_TIMEOUT_MS` (défaut 60 000) / `KORA_LOCK_TIMEOUT_MS` (défaut 5 000),
0 = désactivé ; options psycopg transmises à chaque connexion du moteur runtime
(API et worker) ; migrations non concernées ; .env.example et env.example VPS
complétés.

**Vérifié** : 4 tests nouveaux, dont l'annulation réelle d'un `pg_sleep` sous
`statement_timeout=100` ; moteur de test détruit explicitement pour éviter une
ResourceWarning « unraisable » imputée au test suivant. 35/35 sur les fichiers
concernés ; ruff, mypy strict. Aucune migration, aucun changement de contrat.

**Reste** : rien. Suivi : `AUDIT_SUIVI_20261109.md` §21. **Score : 82,5/100**
(N-B6 : −0,5 → 0). Prochaines priorités : phase 3 (trésorerie/Mobile Money), revue
expert (KF-15/16), KF-14 (CSP).

## 2026-11-11 — Phase 3A : comptes financiers (banques, caisses, Mobile Money)

**Constat** (`docs/PLAN.md`, phase 3) : aucune notion de compte bancaire, de caisse ou
de portefeuille Mobile Money ; les opérations de trésorerie ne sont saisies qu'en
écritures comptables libres, sans suivi opérationnel ni contrôle de concurrence.

**Livré** (branche `feature/kora-3a-comptes-financiers`) :
- migration `0011` : `financial_accounts` (nom, type BANQUE/CAISSE/MOBILE_MONEY,
  opérateur Mobile Money normalisé ORANGE_MONEY_GN / MTN_MOMO_GN, numéro masqué,
  compte comptable lié 52x/57x) et `financial_movements` (dépôt, retrait, frais
  bancaires, virement interne) ; RLS sur les deux tables ; mouvements en ajout seul
  (déclencheur) ; contraintes de cohérence type ↔ sens ↔ liens portées par la base ;
- service `treasury/` : chaque mouvement crée **dans une même transaction** une
  écriture validée du journal de trésorerie (BQ/CA/MM selon le type de compte) et sa
  trace immuable ; le solde n'est jamais stocké — recalculé depuis le grand livre
  (une seule source de vérité, le TFT ne peut pas diverger) ; la contrepartie
  comptable est toujours fournie (capital, ventes, fournisseurs, charges…) ;
- virement interne : une écriture, deux mouvements liés (`opposite_movement_id`),
  verrous des deux comptes dans l'ordre de leurs identifiants (anti-interblocage) ;
- `entries.post_pending()` : validation sans commit pour la transaction atomique ;
- permissions `treasury:read` / `treasury:manage` (dirigeant, cabinet admin,
  comptables : gestion ; lecteur : lecture), `docs/PERMISSIONS.md` régénéré ;
- API `/treasury/accounts`, `/treasury/accounts/{id}/movements`,
  `/treasury/transfers` ; contrat + types TS régénérés ;
- page Trésorerie (liste des comptes avec soldes, historique par compte, formulaires
  compte/mouvement/virement), actions serveur, i18n fr/en, lien de navigation.

**Vérifié** (environnement réel hors Docker : PG 16.15, Redis 8.0.2, Garage 2.4.1,
Mailpit) : suite API **623/623** — dont 14 nouveaux (`tests/test_treasury.py` :
création et validations de compte, dépôt/retrait/frais avec écriture validée et
solde exact, virement lié, **immutabilité par déclencheur**, période verrouillée
refusée, isolation multi-tenant 404, lecteur 200 en lecture / 403 en écriture,
journal d'audit tracé, **deux dépôts concurrents sérialisés par le verrou de ligne
avec solde final exact**) ; matrice des permissions sondée pour les 2 permissions
nouvelles (7 rôles) ; ruff, mypy strict, contrat, ESLint, tsc, Vitest 60/60, build
Next OK. CI GitHub en attente : quota de minutes Actions épuisé (dépôt privé), PR
ouverte avec validation locale documentée.

**Reste** : sous-phases 3B (import de relevés), 3C (rapprochement), 3D (connecteurs
Mobile Money), 3E (prévisions) ; classes 52/57 portant les portefeuilles Mobile Money
à confirmer par la revue expert (KF-15/16). Suivi : `AUDIT_SUIVI_20261109.md` §22.
**Score : 83,5/100** (périmètre fonctionnel : phase 3 entamée, 3A livrée et testée :
+1). Prochaines priorités : 3B import de relevés, revue expert (KF-15/16), KF-14 (CSP).

## 2026-11-11 — Phase 3B : import de relevés bancaires (OFX/CSV)

**Contexte** : 3A en PR (#58) vérifiée localement (quota Actions toujours épuisé) ;
la priorité d'audit suivante est l'import de relevés. Branche
`feature/kora-3b-import-releves` (empilée sur la 3A).

**Livré** :
- migration `0012` (`bank_statements`, `bank_statement_lines`) : RLS + FORCE RLS,
  FKs composites tenant, empreinte SHA-256 du fichier **unique par couple
  (dossier, compte)** — le réimport du même relevé est refusé en base (première
  barrière contre le double comptage) ; lignes avec montant signé du point de vue
  du titulaire, empreinte métier (date, montant, libellé, référence) pour signaler
  les doublons entre relevés successifs, statut de rapprochement
  PENDING/MATCHED/IGNORED avec contrainte de cohérence (MATCHED ⇔ mouvement lié) ;
- parseur sur mesure sans dépendance nouvelle (`treasury/parsing.py`) : OFX 1.x
  SGML (balises souvent non fermées — BCRG, Ecobank), OFX 2.x XML, CSV à
  détection de colonnes (en-tête FR par mots-clés, sinon inférence par nature des
  données) ; montants « 2 500 000 » (espaces insécables), virgule décimale,
  colonnes débit/crédit séparées (débit = sortie), formats JJ/MM/AAAA, BOM UTF-8
  et cp1252 ; arrondi à l'unité (GNF sans sous-unité) ; format détecté au contenu
  jamais à l'extension ;
- service `treasury/statements.py` : import atomique (objet chiffré au stockage
  d'abord, base ensuite, purge à l'échec — même ordre que les pièces), verrou de
  compte sérialisant les imports concurrents, plafonds réglables
  (`KORA_STATEMENT_MAX_BYTES` = 5 Mo, `KORA_STATEMENT_MAX_LINES` = 5000) ;
  lignes ignorées/remises en attente (idempotent, MATCHED interdit hors 3C),
  suppression de relevé non rapproché avec purge de l'objet ; audit tracé à
  chaque opération (`treasury.statement.*`) ;
- API : `POST /treasury/accounts/{id}/statements` (corps brut, `filename` en
  requête, 413/409 documentés), `GET …/statements`, `GET
  /treasury/statements/{id}/lines` (doublons signalés), `POST …/lines/{id}/ignore`,
  `POST …/lines/{id}/restore`, `DELETE /treasury/statements/{id}` ; contrat +
  types TS régénérés ; permissions 3A réutilisées (aucune permission nouvelle) ;
- page Trésorerie : section « Relevés importés » (liste, import avec formulaire
  fichier dédié, consultation ligne à ligne, badges doublon et statut, tri
  écarter/remettre, suppression avec confirmation), i18n fr/en.

**Vérifié** (même environnement réel hors Docker) : **667/667** tests API — 44
nouveaux : 14 tests parseur (OFX SGML/XML, CSV en-tête FR, débit/crédit, inférence
sans en-tête, cp1252, décimales arrondies, formats refusés) + 12 tests API (import,
réimport refusé 409, même fichier sur deux comptes accepté, doublons symétriques,
ignorer/remettre idempotent, suppression, lecteur 200/403, isolation 404, 413,
plafond de lignes) + ajustements ; ruff, mypy strict, contrat, ESLint, tsc, Vitest
60/60, build Next OK, **E2E Playwright 31/31 chromium + 31/31 mobile** contre la
pile native (PG 16, Redis, Garage, Mailpit).

**Reste** : 3C rapprochement (match ligne ↔ mouvement avec confirmation humaine),
3D connecteurs, 3E prévisions ; suivi : `AUDIT_SUIVI_20261109.md` §23.

## 2026-11-12 — Fusion des PRs 55-59, `main` revalidé de bout en bout

**Diagnostic CI** : les 5 PRs (#55 React 19.3.1, #56 Playwright 1.65, #57 export TFT
(KF-15), #58 trésorerie 3A, #59 import relevés 3B) restaient rouges sans aucun défaut
de code : quota GitHub Actions épuisé (dépôt privé, spending limit 0 $) — les jobs
sont rejetés à la file en 2-3 s avec **0 étape exécutée** (sonde : re-run du job
gitleaks → même échec immédiat, aucun step).

**Fusion** : séquence **#57 → #55 → #56 → #58 → #59** par l'API GitHub (commits de
merge, aucun conflit ; #59 contient la 3A). Le #59 a été intégralement revalidé sur
sa branche avant fusion (667/674 pytest, contrat, web, E2E 62/62).

**Revalidation complète de `main` composé**, pile rootless native (PG 16.4, Redis
7.4.6, Mailpit 1.31.3 — AUTH activé pour le test SMTP réel —, Garage 2.4.1, buckets
kora/kora-test/kora-backups) :
- ruff (check + format), mypy strict : OK (156 fichiers) ;
- **674/674** tests pytest (dont test SMTP réel corrigé côté pile locale) ;
- contrat OpenAPI : `openapi.json` identique, types TS sans diff ;
- 4 checks transverses (runtime/migration, KF-11, KF-12, KF-13) : OK ;
- Web : ESLint 0 warning, tsc, **Vitest 60/60**, build Next OK ;
- E2E Playwright **62/62** (31 desktop + 31 mobile) avec React **19.3.1** et
  Playwright **1.65.0** appairés (chromium 1254) ;
- `npm audit` production : 0 vulnérabilité.

**Reste à la CI** (daemon Docker indisponible en local) : restauration synthétique
(restore-drill), pip-audit et SBOM — à rejouer dès que le quota Actions est
restauré (spending limit > 0 ou reset du 1er décembre). Suivi :
`AUDIT_SUIVI_20261109.md` §24.

## 2026-11-12 — Phase 3C : rapprochement bancaire assisté

- Migration `0013` : unicité (dossier, mouvement) — le double rapprochement est
  refusé par la base, y compris en concurrence réelle (test à deux threads :
  200 + 409).
- Moteur de propositions conservateur (même compte, montant égal, direction
  cohérente, ±180 j, jamais rapprochés ; score date/libellé ; 5 candidats) ;
  confirmation humaine obligatoire, réversible, auditée.
- API `/candidates` `/match` `/unmatch` `/reconciliation` + contrat + types TS ;
  page Trésorerie : vue d'ensemble, candidats, confirmer/retirer ; i18n fr/en.
- **698/698** pytest (12 dédiés + 12 isolation auto), contrat, 4 checks
  transverses, ESLint/tsc, Vitest 60/60, build, **E2E 64/64** (desktop + mobile,
  parcours complet de rapprochement). Fusionné via PR #67.
- Suivi : `AUDIT_SUIVI_20261109.md` §25 (score 84,5/100).

## 2026-11-12 — Jeu de données fictif pour les tests locaux (démonstration)

- `kora.scripts.seed_demo` : dossier fictif « Djouma Distribution SARL » (SARL
  guinéenne, GNF, exercice 2026), 3 utilisateurs (directeur/comptable/lecteur),
  sous-comptes tiers et trésorerie, 3 comptes financiers (banque, caisse,
  Orange Money), 74 écritures validées + 1 brouillon à valider, 36 mouvements,
  lettrage automatique de 10 factures. Tout passe par les services applicatifs.
- Génération de 3 relevés fictifs **depuis les mouvements réels** (CSV octobre,
  OFX novembre, CSV Orange Money) + 5 anomalies garanties sans candidat pour
  tester l'import 3B et le rapprochement 3C (dont une ligne à ignorer).
- `--reset` : purge via connexion propriétaire (déclencheurs d'immuabilité
  désactivés le temps de la cascade, tenant fixé, puis réactivés) — le conteneur
  `api` ne porte pas KORA_DATABASE_MIGRATION_URL par séparation des rôles.
- Guide `docs/DEMO.md` (prérequis, scénario complet, réinitialisation).
- Preuve locale : seed exécuté sur PG 16.4 réel, relevés lus par le parseur
  applicatif, importés par le service (déduplication vérifiée), **17 propositions
  de rapprochement** confirmées cohérentes, 5 anomalies sans candidat ; ruff,
  mypy strict, **698/698** pytest, contrat OpenAPI inchangé, gitleaks sans
  nouveau signalement. Suivi : `AUDIT_SUIVI_20261109.md` §26.

## 2026-11-13 — Phase 3D : import Mobile Money étiqueté (frais [FRAIS] + Excel)

- Point d'honnêteté : le document d'architecture (PR #80) décrivait la ligne
  `[FRAIS]` comme « livré » sans qu'aucune colonne frais ne soit reconnue —
  corrigé par implémentation réelle et testée (doc remise au niveau du code).
- Parseur : rôle d'en-tête `fee` (« frais », « commission », « fee ») prioritaire
  sur débit/crédit/montant ; commission non nulle → ligne distincte `[FRAIS] …`
  (montant toujours négatif, date/référence partagées, jamais de solde inventé) ;
  même cycle que toute ligne : `PENDING`, rapprochement humain, zéro écriture auto.
- Excel `.xlsx` : détection par contenu (ZIP + `xl/workbook.xml`), `.xlsm` refusé
  explicitement, lecture openpyxl `read_only`/`data_only` (formules jamais
  évaluées), lecture tabulaire partagée avec le CSV (`_lines_from_rows`).
- Migration 0015 : contrainte `format` élargie à `XLSX` ; descente purge
  explicitement les relevés Excel (RLS forcée levée le temps de la purge,
  rétablie dans la même transaction) ; aller-retour complet testé.
- API : `format: XLSX` dans la réponse ; OpenAPI régénéré (86 chemins/141
  schémas) + types TS. Front : accept `.xlsx`, i18n fr/en (commission → ligne
  distincte `[FRAIS]`).
- Aucun connecteur activé ni simulé : la CI opérateur reste suspendue à un
  contrat marchand (cf. `docs/PHASE_3D_MOMO.md` §2/§4).
- Validation : **794/794** pytest (16 nouveaux), ruff, mypy strict, ESLint 0,
  `tsc` 0, Vitest **69/69**. CI toujours bloquée (facturation GitHub).
- Suivi : `AUDIT_SUIVI_20261109.md` §31 ; doc `docs/PHASE_3D_MOMO.md` à jour.

## 2026-11-13 — Phase 4A : référentiel des tiers (clients et fournisseurs)

- Socle de la facturation : table `partners` par dossier — un tier est client et/ou
  fournisseur (au moins un sens exigé), jamais supprimé (désactivation seule, les
  factures et lettrages à venir restent rattachés à la fiche).
- Mentions obligatoires des factures portées dès la fiche (ARBITRAGE_COMPTABLE.md) :
  raison sociale (nom, unique par dossier sans tenir compte de la casse), NIU/NCC ou
  NIF, RCCM, adresse ; coordonnées des relances (email, téléphone, contact) pour 4D.
- Comptes de tiers par défaut (411x client, 401x fournisseur) : pré-remplissage
  validé par le service (classe + compte actif + appartenance au dossier), jamais une
  écriture automatique — le lettrage et les sous-comptes du dossier restent libres.
- Migration 0016 : contraintes en base (au moins un sens, champs non vides), index
  fonctionnel d'unicité du nom, RLS `tenant_isolation` forcée ; aller-retour complet
  et `alembic check` (parité modèle/migrations) testés.
- Permissions : `partners:read` (tous les rôles de dossier) et `partners:manage`
  (dirigeant, comptable, cabinet) ; docs/PERMISSIONS.md régénéré.
- API : GET (filtres q/kind/active + pagination), POST, GET/{id}, PATCH partiel
  (convention du dépôt) ; audit chaîné `partner.created`/`partner.updated` ;
  OpenAPI régénéré (**88 chemins / 144 schémas**, pur ajout) + types TS.
- Front : page « Tiers » fr/en (recherche, filtres client/fournisseur, affichage des
  désactivés, création, édition préremplie, désactivation/réactivation avec
  confirmation) ; entrée de navigation visible avec `partners:read`.
- Garde-fou testé : créer ou modifier un tier n'écrit **aucune** écriture
  (journal des écritures vérifié vide après créations).
- Validation : **825/825** pytest (19 nouveaux), ruff, mypy strict, ESLint 0,
  `tsc` 0, Vitest **69/69**. CI toujours bloquée (facturation GitHub) — à rejouer.
- Suivi : `AUDIT_SUIVI_20261109.md` §32.

## 2026-11-14 — Phase 4B : devis, factures et avoirs à numérotation sans trou

- Socle du cycle ventes (PR #83) : migration 0017 — `document_sequences` (dernier
  numéro par type de document et par exercice), `sales_documents` (en-tête unique
  devis/facture/avoir), `sales_document_lines` (quantités en millièmes, remise en
  points de base, taux de TVA daté figé à l'émission) ; RLS `tenant_isolation`
  forcée sur les trois tables.
- Numérotation sans trou : réplique du protocole des journaux comptables
  (`JournalSequence`) — upsert inoffensif, verrou FOR UPDATE, incrément dans la
  même transaction que l'émission. Un brouillon n'est jamais numéroté (modifiable
  et supprimable sans consommer de numéro) ; une annulation conserve le numéro
  (jamais de réutilisation) ; un échec après l'incrément est un ROLLBACK qui
  restaure le compteur — propriété prouvée par test.
- Critère du PLAN vérifié : **100 émissions concurrentes = 100 numéros consécutifs**
  (connexions PostgreSQL réelles, fils concurrents, ensemble exact 1..100 vérifié,
  compteur final = 100).
- Cycles de vie : devis numéroté à l'envoi (accepté/refusé garde son numéro,
  conversion en facture brouillon), facture émise irréversible (annulation par
  avoir de contrepassation → CANCELLED dans la même transaction, ou annulation
  directe), avoir partiel ou annulateur (unicité du lien de contrepassation,
  second refus propre 409 dès la création).
- Mentions légales des factures guinéennes figées à l'émission dans des
  instantanés JSONB (tier : nom/NIU/RCCM/adresse ; émetteur : dossier) ;
  avertissements non bloquants si mentions manquantes (règle dure avec le PDF
  en 4B-bis).
- Montants HT/TVA/TTC toujours recalculés par le service à partir des lignes
  (jamais saisis) ; taux datés re-résolus à la date du document ; arrondis
  comptables demi-point vers +∞, cas tabulés testés.
- Permissions `sales:read` (tous les rôles de dossier) et `sales:manage`
  (dirigeant, comptable, cabinet) ; matrice sondée via l'API,
  docs/PERMISSIONS.md régénéré.
- API `/companies/{id}/sales` : liste filtrable (type, statut), création,
  PATCH partiel du brouillon, émission, envoi, décision, conversion, annulation,
  suppression de brouillon ; audit chaîné (`sales_document.created/.updated/
  .issued/.sent/.decided/.cancelled/.deleted`) ; OpenAPI régénéré
  (**95 chemins / 154 schémas**, pur ajout) + types TypeScript.
- Front fr/en : page « Ventes » (filtres type/statut, création en 3 lignes avec
  taux ou exonération motivée, émission/envoi avec confirmation explicite que le
  numéro est définitif, décision, conversion, annulation, suppression) ;
  navigation visible avec `sales:read`.
- Garde-fou testé : aucun chemin du module ventes n'écrit en comptabilité
  (journal des écritures vérifié vide après le cycle complet) — l'intégration
  comptable reste la Phase 4E avec validation humaine.
- Validation : **878/878** pytest sur la pile réelle hors Docker (PostgreSQL 16.2
  + btree_gist compilé, fakeredis serveur, Moto S3, Mailpit v1.31.3 — procédure
  reconstruite après recyclage du bac à sable) = 825 existants + **23 nouveaux**
  (ventes) + 30 sondes d'isolation automatiques pour les 10 nouvelles routes ;
  ruff, mypy strict (179 fichiers), ESLint 0, `tsc` 0, Vitest **69/69** ;
  migrations aller-retour + `alembic check`. Dérive de format préexistante sur
  la migration 0016 corrigée au passage (ruff format, CI jamais passée).
- CI toujours bloquée (facturation GitHub) — à rejouer après régularisation.
- Suivi : `AUDIT_SUIVI_20261109.md` §33.

## 2026-11-15 — Phase 4B-bis : PDF conforme des ventes et règle dure des mentions

**Objet** — rendre le produit vendable : les documents de vente numérotés (4B)
deviennent des documents remis au client — PDF conforme avec les mentions légales
exigées (ARBITRAGE_COMPTABLE.md, KF-16 : raison sociale, NIU/NCC ou NIF, adresse,
montants HT / TVA / TTC, référence de l'exercice), et règle dure à l'émission.

**Livré** :
- `kora/sales/pdf.py` : rendu PDF consommant exclusivement les données figées à la
  numérotation (instantanés JSONB émetteur/tier, numéro, dates, lignes, taux datés) —
  jamais les fiches vivantes ; blocs émetteur/client, timbre des documents hors usage
  (« FACTURE ANNULÉE », « DEVIS REFUSÉ »), mentions d'origine (« Devis d'origine »,
  « Annule et remplace la facture »), tableau des lignes (millièmes et points de base
  convertis sans flottant, motif d'exonération), totaux décomposés par taux, notes,
  référence de l'exercice ; numéro d'affichage « FAC-2026-00042 » (l'entier sans trou
  reste stocké) ; polices et conventions partagées avec les exports comptables.
- Route `GET /api/v1/companies/{id}/sales/{doc}/pdf` : `sales:read`, brouillon refusé,
  quota d'exports KF-13 (compteurs partagés), audit `sales_document.exported` ; nom de
  fichier commercial (`facture-FAC-2026-00042-acme.pdf`) ; contrat régénéré
  (**96 chemins**, pur ajout), types TS à jour.
- Front fr/en : bouton PDF sur les documents numérotés via BFF
  `/dossiers/{id}/ventes/{doc}/pdf` (le navigateur n'appelle jamais l'API), avis sur
  la règle dure dans le formulaire de création.
- **Règle dure à l'émission** : facture et avoir refusent de naître sans NIU/NCC et
  adresse du client, NIF et adresse de l'émetteur (422 AVANT le compteur : aucun
  numéro consommé) ; le devis, document commercial, reste averti sans être bloqué.
- **Corrections d'hygiène héritées de main** : registre Alembic sans `kora.models.sales`
  (`alembic check` échouait depuis le merge 4B — tables 4B vues comme « à supprimer »)
  corrigé ; `uv.lock` désynchronisé de `pyproject.toml` réaligné (`make api-lock`) ;
  pypdf ajouté au groupe dev pour l'extraction du texte des PDF dans les tests.

**Validation** : pytest **891/891** sur la pile réelle hors Docker (PG 16.2 + btree_gist,
fakeredis, Moto S3 + buckets, Mailpit AUTH — pile reconstruite après recyclage) =
878 existants + **10 nouveaux** (PDF et règle dure) + 3 sondes d'isolation de la
nouvelle route ; ruff 0 ; mypy strict 0 (181 fichiers) ; ESLint 0 ; tsc 0 ;
Vitest **69/69** ; migrations aller-retour 0017 → base → 0017 + `alembic check` ;
aperçus visuels relus (facture complète, facture annulée, devis refusé, avoir
annulateur).

**Reste** : CI toujours bloquée (facturation GitHub) — à rejouer après régularisation ;
envoi du PDF par email/WhatsApp, règlements et lettrage (4C), balance âgée (4C/4D).
- Suivi : `AUDIT_SUIVI_20261109.md` §34.

## 2026-11-17 — Phase 4C : règlements clients, lettrage commercial et balance âgée

**Objet** — rendre le produit vendable : les factures numérotées (4B) deviennent
encaissables, avec le solde restant dû et la balance âgée — le suivi des créances
exigé par le cahier des charges (§51), cœur commercial du SaaS.

**Livré** :
- `kora/sales/payments.py` : règlement = encaissement d'un montant strictement
  positif affecté à une ou plusieurs factures émises du même tier (lettrage
  commercial). Le montant n'est jamais saisi : recalculé = somme des
  affectations. Solde restant dû = TTC − affectations − avoirs partiels émis,
  **calculé en lecture** (aucun statut dérivé stocké, aucune dérive possible).
  Contrôle du solde sous verrou FOR UPDATE des factures, ordre trié par
  identifiant (pas d'interblocage) : deux règlements concurrents ne peuvent pas
  excéder le TTC ensemble. Date d'encaissement dans un exercice ouvert, mode de
  paiement borné (Mobile Money en premier usage réel), règlement immuable
  (correction = suppression journalisée puis re-saisie).
- Interlock 4B/4C : une facture qui porte des règlements ne s'annule plus — ni
  sans avoir (`cancel`), ni par avoir annulateur (`issue` avec
  `reverses_document_id`) : les règlements se suppriment d'abord.
- Migration 0018 : `sales_payments` + `sales_payment_allocations` (RLS
  `tenant_isolation` forcée, FK composites, unicité (règlement, facture),
  CASCADE au règlement / RESTRICT à la facture ; suppression par CASCADE de la
  base — sans relation ORM, l'ordre de suppression appartient à PostgreSQL).
- Routes API : `GET/POST /payments`, `GET/DELETE /payments/{id}` (filtres tier,
  facture, dates), `GET /receivables/aging` (buckets à-échoir / 1-30 / 31-60 /
  61-90 / 90+ à une date arbitraire) ; `DocumentOut` enrichi additivement
  (`outstanding_ttc`, `payment_status` — None hors facture émise). Contrat
  régénéré : **99 chemins** (3 ajoutés, 0 supprimés), 161 schémas (7 ajoutés,
  0 supprimés) — diff strictement additif.
- Permissions `sales:read`/`sales:manage` réutilisées (aucune nouvelle entrée) ;
  audit `sales_payment.created` / `sales_payment.deleted` dans la chaîne SHA-256.
- Front fr/en : page Ventes avec colonne « Solde dû » (badge Non lettré /
  Partiel / Payé), formulaire d'encaissement (facture non soldée, montant, date,
  mode Mobile Money en tête, référence), liste des règlements avec factures
  lettrées et suppression confirmée, balance âgée en cinq buckets ; actions via
  BFF, 38 clés i18n, types TS régénérés.

**Validation** : pytest **921/921** sur la pile réelle hors Docker (PG 16.2 +
btree_gist, fakeredis, Moto S3 + buckets, Mailpit AUTH — pile reconstruite après
le 5e recyclage du sandbox) = 891 existants + **15 nouveaux** (règlements,
course concurrente, interlock, RLS, audit, balance âgée, zéro-écriture) + 15 de
marge de comptage des suites existantes ; course critique : **20 règlements
concurrents de 1 000 sur TTC 10 000 → exactement 10 succès + 10 refus 422,
somme lettrée 10 000, solde zéro** ; ruff 0 ; mypy strict 0 (183 fichiers) ;
ESLint 0 ; tsc 0 ; Vitest 69/69 ; migrations aller-retour 0018 → 0017 → 0018 +
`alembic check` propre ; contrat et types TS committés.

**Reste** : CI toujours bloquée (facturation GitHub — jobs tués à ~3 s) : à
rejouer après régularisation du compte ; PDF de bordereau de règlement (4C-bis
éventuel), envoi par email/WhatsApp, relances (4D), intégration comptable (4E).
- Suivi : `AUDIT_SUIVI_20261109.md` §35.

## 2026-11-17 — Phase 4D : relances de factures échues

**Objet** — compléter le cycle commercial : les factures échues non soldées
(4B/4C) deviennent relançables, avec un historique immuable et un email réel au
client — exigence du cahier des charges (relances), cœur du suivi de recouvrement.

**Livré** :
- `kora/sales/reminders.py` : une relance vise une facture ÉMISE, ÉCHUE
  (échéance strictement passée à la date du rappel ; sans échéance = jamais
  échue, convention balance âgée) et NON SOLDÉE (solde 4C : TTC − affectations −
  avoirs partiels émis). Le niveau (1re, 2e relance…) est compté sous verrou
  FOR UPDATE de la facture — jamais saisi. Doublon du jour intercepté par
  relecture sous verrou + unicité (dossier, facture, jour) en base : deux
  courses concurrentes se sérialisent, traduites en 409. Relance immuable :
  aucune suppression ni modification ; adresse destinataire figée à l'envoi.
- Migration 0019 `sales_reminders` : RLS `tenant_isolation` forcée, FK
  composites (facture, tier) RESTRICT, canal borné à EMAIL par CHECK (WhatsApp
  = évolution après contrat opérateur, même discipline que la 3D).
- Worker : `send_sales_reminder` compose l'email depuis l'état persisté (tenant
  lié explicitement — RLS ferme toute session sans tenant) puis le confie à
  `deliver_email` ; gabarit `invoice_reminder` fr/en (montant, retard, échéance,
  message personnalisé). La panne de la file n'annule pas la relance :
  `email_queued` porté par la réponse, renvoi journalisé
  (`sales_reminder.resent`) via `POST /reminders/{id}/resend`.
- Routes : `GET /receivables/overdue` (candidates à date arbitraire : solde dû,
  retard, historique, email du tier), `GET/POST /reminders` (filtres facture,
  tier, fenêtre de dates, pagination) ; `DocumentOut` enrichi additivement
  (`reminders_count`). Contrat régénéré : **102 chemins** (3 ajoutés, 0
  supprimés), 168 schémas (7 ajoutés, 0 supprimés) — diff strictement additif.
- Permissions `sales:read`/`sales:manage` réutilisées ; audit
  `sales_reminder.created` / `sales_reminder.resent` dans la chaîne SHA-256 ;
  zéro écriture comptable (garde-fou testé — 4E à venir).
- Front fr/en : page Ventes avec carte « Relances de factures échues »
  (candidates : retard, relances déjà envoyées, avertissement email manquant),
  formulaire de relance (facture échue, message personnalisé facultatif),
  historique immuable avec renvoi confirmé ; actions via BFF, 33 clés i18n,
  types TS régénérés.

**Validation** : pytest **934 verts** en tranches sur la pile réelle hors Docker
(PG 16.2 + btree_gist, fakeredis, Moto S3, Mailpit) = **12 nouveaux** dans
`test_sales_reminders.py` ; course critique : **20 relances concurrentes le
même jour → 1 × 201 + 19 × 409**, historique à une ligne ; le test de
synchronisation modèles/migrations a intercepté le contraignant d'unicité
absent du modèle (corrigé avant merge) ; ruff 0 ; mypy strict 0 (185 fichiers) ;
ESLint 0 ; tsc 0 ; Vitest 69/69 ; build Next.js OK ; migrations aller-retour
0019 → 0018 → 0019 + `alembic check` propre ; contrat et types TS committés.
`test_isolation_tenants` (313 paramètres = toutes les routes) scindé en 7 lots
sous la limite de 10 min du sandbox — vert intégralement.

**Reste** : CI toujours bloquée (facturation GitHub) : à rejouer après
régularisation du compte ; planification automatique des relances hors périmètre
(acte commercial humain et journalisé) ; intégration comptable (4E) avec
validation humaine, envoi des documents par email/WhatsApp (4D-bis éventuel),
achats (phase suivante).
- Suivi : `AUDIT_SUIVI_20261109.md` §36.

## 2026-11-18 — Phase 4E : intégration comptable des ventes (acte explicite du comptable)

**Objet** — fermer le cycle de vente ouvert en 4B : les documents émis et les
règlements deviennent des écritures validées du grand livre. La comptabilisation
est un acte explicite (permission `entries:post`), jamais un effet de bord : le
garde-fou testé depuis la 4A reste vrai, la 4E n'ajoute que l'action délibérée
qui le rompt.

**Livré** :
- Migration 0020 : colonnes `entry_id` NULLables sur `sales_documents` et
  `sales_payments`, FK composites RESTRICT vers `journal_entries` (pattern des
  mouvements de trésorerie) — NULL tant que non comptabilisé ; RLS déjà forcée
  sur les tables (0017/0018), rien à ajouter.
- `kora/sales/accounting.py` : facture émise → journal des ventes VT (débit
  411x au TTC, crédit du compte de produits au HT par groupe de taux, crédit du
  compte collecté de chaque taux — 4431 TVA normale) ; avoir → écriture inverse ;
  règlement → journal de trésorerie selon le mode (571 caisse au journal CA,
  521 banque au journal BQ ou MM) créancier du compte de tiers. Comptes résolus
  dans le plan du dossier : compte client par défaut de la fiche sinon 411,
  produits 701 sauf choix explicite, TVA = compte collecté du taux daté (refus
  clair si le réglage manque). Date = fait générateur (émission / encaissement) :
  exercice ouvert et non verrouillé exigé. Montants issus des instantanés
  d'émission — jamais recalculés. Exonération → HT au compte de produits, sans
  ligne de TVA.
- Course critique : 20 comptabilisations concurrentes de la même facture =
  1 écriture + 19 refus 409 (verrou du document, la seconde lecture voit
  `entry_id` rempli avant tout INSERT).
- Interlocks symétriques : règlement comptabilisé → suppression refusée jusqu'à
  la contre-passation de son écriture ; facture comptabilisée → annulation
  refusée jusqu'à la contre-passation ; après contre-passation, la correction
  passe (audit complet conservé).
- Routes `POST /sales/{id}/entry` et `POST /payments/{id}/entry`
  (`entries:post`) ; audit `sales_document.posted` / `sales_payment.posted` ;
  `DocumentOut`/`PaymentOut` enrichis additivement (`entry_id`). Contrat :
  **104 chemins** (2 ajoutés), 170 schémas (2 ajoutés) — pur ajout (3 champs
  `entry_id` nullables sur des réponses + une description), types TS régénérés.
- Front fr/en : colonne « Compta » avec badges « Comptabilisée » /
  « Comptabilisé », bouton Comptabiliser (confirmation d'acte définitif) visible
  avec `entries:post`, avis d'en-tête réécrit ; actions via BFF, types TS.

**Validation** : pytest **18 nouveaux** (`test_sales_accounting.py` : écritures
attendues au compte près, exonération, avoir inverse, refus devis/brouillon/
annulée, double comptabilisation, course 20 fils, règlements CA/MM/BQ,
interlocks avec contre-passation, exercice verrouillé, compte de regroupement
refusé / sous-compte accepté, taux sans compte collecté, garde-fou « cycle sans
action → grand livre vide », isolation, lecteur 403) ; régression par tranches
sur la pile réelle hors Docker (PG 16.2 + btree_gist recompilé contre les
binaires pgserver — `PG_CONFIG` en argument make, l'option d'environnement
prenait le pg_config système PG 17 —, fakeredis 2.34.1 serveur TCP (2.40 perd
son CLI), Moto S3 + buckets, Mailpit v1.33.1 ; pile et scripts reconstruits
après recyclage du bac à sable : `scripts/stack.py` + `scripts/test-env.sh`) ;
ruff 0 ; mypy strict 0 ; ESLint 0 ; tsc 0 ; Vitest 69/69 ; build Next.js OK ;
migrations aller-retour 0020 → 0019 → 0020 + `alembic check` propre.

**Reste** : CI toujours bloquée (facturation GitHub) : à rejouer après
régularisation du compte ; envoi des documents par email/WhatsApp (4D-bis
éventuel) ; imputation par famille de produits (plusieurs comptes 70x par
document) = évolution future ; achats (phase suivante) ; arbitrage
expert-comptable KF-15/16 avant données réelles.
- Suivi : `AUDIT_SUIVI_20261109.md` §37.
