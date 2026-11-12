# Audit de suivi — Kora Finance

Date : 9 novembre 2026 — dépôt privé `skaba89/kora-finance`

Référence courante : `4a9fa1a798ea5705f89f71d41f2feece3e0412e9` (`main`, merge PR #20 du
2026-10-27). Audit de prolongement de l'audit initial du 2026-10-26 (référence figée
`7a51c45258301e8cfc50a0305ce023e08d286202`, documents `AUDIT_GLOBAL.md`,
`AUDIT_SECURITE.md`, `AUDIT_COMPTABILITE.md`, `AUDIT_PRODUCTION.md`,
`BACKLOG_PRIORISE.md`). Le présent document **vérifie les correctifs annoncés**, examine
**le code ajouté depuis** (2g2 saisie guidée, 2g3 hors connexion, 2h tableau de bord) et
met à jour le **score de maturité** et le **backlog**. Aucune donnée de production
consultée, aucun déploiement effectué.

## 1. Preuve d'exécution nouvelle (par rapport à l'audit initial)

L'audit initial n'avait pas pu exécuter les tests (pas de PostgreSQL local). Cette fois
la suite a été exécutée intégralement **sur un environnement réel reconstruit hors
Docker** : PostgreSQL 16 (rôles `kora_owner`/`kora_app`, base `kora_test`, extensions
contrib dont `btree_gist`), Redis 7 (protocole réel), Garage v2.4.1 (S3, buckets
`kora`/`kora-test`), Mailpit (SMTP).

| Contrôle | Résultat | Portée |
|---|---|---|
| Migrations Alembic 0001→0009 (rôle `kora_owner`) | Réussies | Vrai PostgreSQL 16, RLS + triggers installés |
| **pytest complet** | **540 passés, 0 échec** (336 s) | Vrai PG + Redis + Garage + Mailpit |
| Vitest (apps/web) | 12 fichiers, 60/60 | Local |
| `tsc --noEmit` (typegen + strict) | Réussi | Local |
| ESLint `--max-warnings=0` | Réussi | Local |
| CI sur `main` (run #44 du 2026-10-27) | **ÉCHEC du job E2E** | API, Web, contrat, secrets, restore : verts |

La suite CI était verte sur la branche `tableau-de-bord` (run #43) avant le merge de la
PR #20, et rouge sur `main` ensuite (run #44) : **`main` était bloqué pour tout merge
depuis le 2026-10-27.** Cause, incident et correctif : §3.

## 2. Vérification des correctifs de l'audit initial

| ID | Objet | Statut | Preuve dans le code actuel |
|---|---|---|---|
| KF-01 | Trigger des lignes : parent de destination non contrôlé | **CORRIGÉ** | Migration `20261026_0009_protection_rattachement_lignes.py:46-55` : changement de rattachement interdit + `SELECT … FOR UPDATE` du parent, aligné sur `entries._lock_entry` (`apps/api/src/kora/accounting/entries.py:177-185`) |
| KF-02 | Secret `kora_owner` transmis à l'API/worker | **CORRIGÉ** | `deploy/vps/compose.yml:79-80` : `KORA_DATABASE_MIGRATION_URL` réservé au service `migrate` ; `x-api-env` (:15-39) n'a que `kora_app` ; `core/config.py:119-129` sépare `MigrationSettings` ; vérification mécanique en CI (`scripts/check-runtime-db-separation.py`, job `api`) |
| KF-04 | Injection de formule Excel | **CORRIGÉ** | `exports/xlsx.py:19-24` `_append_literal` force `data_type="s"` ; appliqué à tous les points d'écriture (:45, :78, :80, :86) ; `tests/test_xlsx_security.py` |
| KF-06 | Compteur d'échecs de connexion non atomique | **CORRIGÉ** | `auth/service.py:135-140` `with_for_update()` ; compteur MFA verrouillé `auth/mfa.py:150-152` ; test de concurrence réel `tests/test_login_concurrency.py` (PR #18) |
| KF-10 | Reprise après perte du VPS non démontrée | **CORRIGÉ côté dépôt** | Job CI « Restauration synthétique » (ci.yml:83-95) : `scripts/restore-drill.py` vérifie données (digests SHA-256), révision Alembic, triggers (refus d'UPDATE sur POSTED), RLS + FORCE RLS, chaînes d'audit, chiffrement ; limites assumées dans `docs/RESTORE_DRILL.md:37-52` (`production_pra_validated: False`) |
| KF-17 | PWA : saisies hors connexion | **CORRIGÉ** (2g3a, PR #19) | `lib/offline/*` (IndexedDB chiffrée AES-256-GCM, clé non exportable), `public/sw.js`, `components/offline/*` ; 16 tests Vitest + 4 scénarios E2E |
| KF-18 | Tableau de bord périmé | **CORRIGÉ** (2h, PR #20) | `accounting/dashboard.py`, page dashboard, accueil direct ; 4 tests pytest + E2E |
| KF-22 | Enfilement après commit sans outbox | **PARTIEL** | Purge différée avec réessais (`attachments/service.py:251-262`, `worker/tasks.py:52-56`) ; pas d'outbox durable (`worker/enqueue.py:26-34`) ni réconciliation d'objets S3 orphelins (cf. §4, NOUVEAU-B4) |

## 3. Incident bloquant détecté et corrigé (P0 infrastructure)

**Constat.** Run CI #44 sur `main` (2026-10-27) : le job E2E échoue sur
`e2e/hors-connexion.spec.ts` (profil mobile, 2 tentatives) — `main` rouge bloque toute
fusion ultérieure (règle projet : fusion seulement si la CI est verte).

**Cause (bug de test, pas de produit).** `LogoutButton` (`components/offline/logout-button.tsx:36-37`)
appelle `window.confirm` **après** une lecture IndexedDB (`unsyncedCount`) : le dialogue
peut donc s'ouvrir **après** la résolution du clic. Le test enchaînait deux
`page.once("dialog")` (renoncer puis confirmer) : si le premier dialogue s'ouvrait après
l'enregistrement du second handler, les deux handlers recevaient le même dialogue — le
premier le fermait (`dismiss`), le second échouait avec
`Cannot accept dialog which is already handled!`, le `confirm` était clos par
« renoncer » et la déconnexion n'avait pas lieu. Les deux erreurs du log CI et l'URL
restée sur `/dossiers/{id}/hors-connexion` confirment ce scénario.

**Correctif (PR #21, branche `fix/kora-e2e-dialog-deconnexion`).** Un seul gestionnaire
par dialogue, branché sur l'attente elle-même :
`page.waitForEvent("dialog").then(dialog => dialog.accept()|dismiss())`, créé avant le
clic et achevé après — le dialogue est traité dès son ouverture (pendant ou après le
clic) et aucun `page.once` ne subsiste dans le fichier. Premier itéral (attendre le
dialogue puis cliquer) rejeté par la CI run #45 : le `confirm()` **synchrone** de
« Valider » bloque le clic tant que le dialogue n'est pas traité — le motif
`.then(handle)` corrige les deux timings. Aucune modification produit.

## 4. Anomalies vérifiées toujours présentes (référentiel initial)

| ID | Objet | Priorité | Preuve actuelle |
|---|---|---|---|
| KF-03 | Clôture vs écritures concurrentes : le trigger 0007 et `_fiscal_year_for` lisent `fiscal_years` **sans** verrou, alors que `close()` verrouille l'exercice (`closing.py:47-55`) — une validation concurrente peut être absente des à-nouveaux | P1 | `alembic/versions/20261024_0007_cloture.py:43-44` ; `entries.py:83-89` |
| KF-05 | Lectures multi-requêtes sans snapshot : `account_ledger` (totaux puis lignes), `full_ledger` (balance puis lignes) en READ COMMITTED — export/écran possiblement incohérent sous validation concurrente | P1 | `reports.py:192-199/243-255`, `:307/310-350` ; aucun `REPEATABLE READ` dans `src/` |
| KF-07 | Dernier dirigeant : comptage sans verrou sur la société — deux rétrogradations simultanées de deux dirigeants peuvent laisser un dossier sans dirigeant | P1 | `organization/service.py:268-283` (aucun `with_for_update()` sur `Company`) |
| KF-08 | Activation MFA sans réauthentification récente : `/auth/mfa/setup|enable` n'exigent que le jeton d'accès (asymétrique : `disable` exige mot de passe + code) ; setups concurrents écrasent le secret sans verrou | P1 | `api/v1/mfa.py:54-64` ; `auth/mfa.py:101-114`, `:117-129` ; `auth/deps.py:36` |
| KF-09 | Sauvegardes et pièces partagent bucket et droits de suppression (une clé S3 pour tout) | P1 | `scripts/backup.py:58-59,77-78,101-102` ; `storage/objects.py:88,100,111` ; `compose.yml:34-39` |
| KF-11 | Déploiement sans tag d'image ni sauvegarde préalable imposée (amélioré : main-only, ff-only, check_storage — `deploy.sh:13-33`) | P1 | `deploy.sh:31-36` ; images `kora-api:prod` figées écrasées (`compose.yml:77,86,100,111`) |
| KF-12 | Supervision limitée aux healthchecks et logs ; échec de sauvegarde quotidienne sans alerte (`kora-backup.service` oneshot sans `OnFailure=`) | P1 | `api/health.py:34-66` ; `deploy/vps/kora-backup.service:6-9` |
| KF-13 | Aucun budget global : exports synchrones sans rate limit ni quota (seule borne `MAX_PDF_ROWS`), aucun `mem_limit`/`cpus` sur les conteneurs | P1 | `api/v1/exports.py:70-131` ; `exports/service.py:27` ; compose sans `deploy.resources` |
| KF-14 | CSP avec `script-src 'self' 'unsafe-inline'` (compromis documenté, Next Cache Components) | P2 | `proxy.ts:45-63` (commentaire :38-44) |
| KF-15 | Jeu d'états SYSCOHADA incomplet (pas de TFT ni notes annexes) — **à arbitrer par un expert-comptable** | P1 | `docs/PLAN.md:40` (2e-bis non livré) |
| KF-16 | Règles fiscales et exercices à arbitrer (TVA, mentions factures, conservation) — **à valider par un expert-comptable** | P1 | `CLAUDE.md` « À valider par un expert-comptable guinéen » |
| KF-20 | Aucun SCA/SBOM/scan d'image en CI (pip-audit, npm audit, Dependabot, trivy) | P2 | `.github/workflows/ci.yml` : aucun job SCA |
| KF-23 | Sauvegarde chargée intégralement avant contrôle de taille ; chemin de restauration sans contrôle ; aucun test de dépassement | P2 | `scripts/backup.py:51-55` (`read_bytes()` avant `MAX_BYTES`), `:71-73` ; `restore.sh:13-14` |

## 5. Constats nouveaux (code ajouté ou revue transversale)

| Réf | Objet | Priorité | Preuve |
|---|---|---|---|
| N-B1 | Réjeu idempotent sans comparaison de payload : ré-POSTer le même `id` avec des lignes différentes renvoie 200 et jette le nouveau payload silencieusement (première version gagne) | P2 | `entries.py:250-257` ; `guided.py:442-449` ; `lib/actions/offline.ts:84-99` |
| N-B2 | Clé d'idempotence scopée tenant, pas utilisateur : un membre du même dossier peut « consommer » l'`id` d'un autre (pas de fuite nouvelle, lecture déjà permise) | P3 | `entries.py:251-255` |
| N-B3 | Ajout de pièce sur écriture validée possible puis irrévocable (le trigger 0008 ne couvre que UPDATE/DELETE) — comportement non décidé, non testé | P3 | `attachments/service.py:133-188` ; `20261025_0008…py:81-95` |
| N-B4 | Objet S3 orphelin si crash entre `put` et commit DB (pas de réconciliation périodique) | P3 | `attachments/service.py:165-187` |
| N-B5 | Garde-fou AST « SQL interpolé » ne couvre pas `op.execute(f"…")` des migrations (usage actuel sûr : constantes figées) | P3 | `tests/test_guardrails.py:30-39` vs `20261024_0005…py:322-333` |
| N-B6 | Aucun `statement_timeout`/`lock_timeout` par défaut au runtime (une lecture d'export peut retenir des verrous) | P3 | `db/session.py` ; `init-roles.sh:31` (`TEMPORARY` au rôle app, révocable) |
| N-W1 | `logoutAction` ne supprime pas le cookie MFA (jeton à usage unique, courte durée — négligeable) | P3 | `lib/actions/auth.ts:80-81` vs `:35` |
| N-W2 | Champ `status` de la file hors connexion en clair hors AAD (altération locale → re-envoi, sans conséquence grâce à l'idempotence serveur) | P3 | `lib/offline/store.ts:20,121,158` |
| N-W3 | `formatRate` et hauteurs du graphique mensuel passent par un float (affichage seul ; montants métier intégralement en BigInt) | P3 | `lib/format.ts:47` ; `monthly-chart.tsx:39-42` |
| N-W4 | Trous de tests sur le code récent : boucle `syncPending` (verrous Web Locks, arrêts), `store.ts` (courses IndexedDB), mapping d'erreurs de `actions/offline.ts`, contenu du cache du service worker (aucune vérification « rien d'authentifié en cache ») | P2 | `lib/offline/sync.ts`, `store.ts`, `actions/offline.ts`, `sw.js` |
| N-I1 | En-têtes de sécurité absents du Caddyfile production (CSP, `X-Content-Type-Options`, `frame-ancestors`, `Referrer-Policy` — le proxy Next les pose côté app mais le domaine de premier niveau n'a ni XCTO ni Referrer-Policy propres) | P2 | `deploy/vps/Caddyfile:13-16` ; `compose.proxy-externe.yml:6-13` |
| N-I2 | Résidu de dump déchiffré si `restore.sh` échoue (suppression en fin de succès seulement, pas de `trap`) | P3 | `deploy/vps/restore.sh:23` |
| N-I3 | Images de base flottantes (`postgres:16-alpine`, `redis:7-alpine`, `python:3.13-slim`, `node:24-bookworm-slim`) + `build --pull` : builds non reproductibles (le pinning par digest supprimerait la dérive) | P3 | `deploy/vps/compose.yml`, `docker-compose.yml` ; `deploy.sh:31` |
| N-I4 | `credential.helper store` recommandé dans la doc de déploiement (jeton en clair sur disque) — un deploy key ou `cache` serait préférable | P3 | `docs/DEPLOIEMENT.md:36-38` |

## 6. Points forts vérifiés (preuves positives)

- **Isolation tenant** : RLS `FORCE` + policy sur toute table métier, réapplication
  `SET LOCAL` à chaque transaction (`db/tenant.py:15,22-33`), rôle `kora_app`
  NOSUPERUSER/NOBYPASSRLS/NOINHERIT (`infra/postgres/init-roles.sh:20-23`), **garde-fou
  automatique** exigeant RLS FORCE sur toute nouvelle table à `tenant_id`
  (`tests/test_isolation_tenants.py:162-179`) et couverture cross-tenant de toute
  nouvelle route.
- **Immuabilité comptable imposée par PostgreSQL** : triggers 0005/0007/0009 (équilibre,
  statut POSTED, verrouillage de période, rattachement des lignes), contre-passation
  uniquement, numérotation verrouillée par journal/exercice.
- **Montants** : entiers de bout en bout (BIGINT, chaînes à l'API, BigInt côté web) ;
  TVA de la saisie guidée en entiers avec invariant d'équilibre vérifié par Hypothesis
  (`tests/test_guided.py:116-138`) ; aucun flottant métier constaté.
- **BFF** : jetons jamais accessibles au JavaScript (cookies httpOnly, `server-only`),
  CSP stricte hors script-src, anti-open-redirect (`safeNextPath`), zéro
  `dangerouslySetInnerHTML`, `rel="noopener"` systématique.
- **Hors connexion** : chiffrement AES-256-GCM à clé non exportable, AAD liant
  enregistrement et identifiants, purge par utilisateur à la déconnexion, service worker
  limité aux pages publiques et `/_next/static`, synchronisation idempotente sans
  validation côté client.
- **Exploitation** : séparation migration/runtime vérifiée mécaniquement en CI sur les
  trois compositions ; sauvegarde chiffrée avec relecture SHA-256 et plancher de
  rétention ; restore drill complet (données, triggers, RLS, chiffrement, refus
  inter-tenant) ; documentation qui annonce honnêtement ses limites.
- **Qualité** : 540 tests API (dont Hypothesis, attaques SQL d'invariants, concurrence
  réelle), 60 tests Vitest, 62 E2E ordinateur+mobile, contrat OpenAPI bloquant,
  dépendances épinglées, actions CI par SHA.

## 7. Score de maturité (pondéré, avec preuves)

Méthode : cinq dimensions pondérées, chaque déduction appuyée par une anomalie
référencée. Les phases non commencées comptent pour leur poids (c'est un écart de
périmètre, pas un défaut de qualité).

| Dimension | Poids | Score | Justification synthétique |
|---|---|---|---|
| Sécurité du socle (auth, RBAC, RLS, crypto, secrets) | 25 | **19** | Argon2id, JWT typés + rotation avec détection de réutilisation, 2FA TOTP, RLS FORCE testée automatiquement, chiffrement AES-256-GCM, secrets hors dépôt, gitleaks CI. Déductions : KF-08 (−2), KF-03/KF-07 courses (−1,5), KF-09 (−1,5), KF-14 CSP inline (−1), N-B6 timeouts (−0,5), KF-05 pour l'export (−0,5) |
| Intégrité comptable SYSCOHADA | 25 | **18** | Partie double, immuabilité par triggers, lettrage différé, clôture/à-nouveaux/réouverture, états pilotés par CSV versionnés, dashboard cohérent. Déductions : KF-03 (−2), KF-05 (−2), KF-15/KF-16 non arbitrés par un expert (−2), TFT absent (−1) |
| Périmètre fonctionnel produit | 20 | **7** | Livré : socle, comptabilité générale complète, saisie guidée, hors connexion, tableau de bord (phases 0-2h). Absents : trésorerie/Mobile Money (phase 3), ventes/achats (4), imports (5), dossier de financement (6), IA (7), abonnements (8) — cf. `docs/PLAN.md` |
| Exploitation / production | 15 | **8,5** | Sauvegarde chiffrée vérifiée, restore drill en CI, séparation des secrets vérifiée, rôles moindre privilège. Déductions : KF-11 (−2), KF-12 (−2), KF-13 (−1,5), KF-23 (−1) |
| Qualité logicielle (tests, CI, docs) | 15 | **12,5** | 540 API + 60 unitaires + 62 E2E verts (exécutés localement cette fois), garde-fous AST, contrat bloquant, docs honnêtes. Déductions : incident E2E `main` (−1, corrigé PR #21), KF-20 SCA absent (−1), N-W4 trous de tests récents (−0,5) |
| **Total** | **100** | **65 / 100** | Socle sécurisé et fortement testé ; le score est surtout plafonné par le périmètre produit (phases 3-8) et les arbitrages experts |

Chemin vers 99/100 : P1 ci-dessus (≈ +9), supervision/déploiement (≈ +4), phases 3 à 8
(≈ +13), arbitrages expert-comptable et preuve PRA réelle (≈ +4), SCA/durcissements P2
(≈ +4).

## 8. Backlog priorisé mis à jour (delta par rapport à `BACKLOG_PRIORISE.md`)

**Séquencement recommandé (par risque, dépendance, valeur) :**

1. **[P0, en cours]** Fusionner la PR #21 (E2E déterministe) → `main` de nouveau vert.
2. **[P1]** KF-08 : réauthentification (mot de passe) pour `/auth/mfa/setup|enable`,
   verrou utilisateur sur la transition, notification et invalidation des autres
   sessions. Autonome, testable (pytest + E2E).
3. **[P1]** KF-03 : verrou `fiscal_years … FOR UPDATE` dans le trigger 0007 (ou advisory
   lock par exercice) + tests à deux connexions avec barrières (clôture/validation
   simultanées).
4. **[P1]** KF-05 : snapshot `REPEATABLE READ` (ou requête unifiée) pour
   balance/grand-livre/états/exports + test d'interleaving.
5. **[P1]** KF-07 : verrou `Company` avant comptage des dirigeants + test concurrent.
6. **[P1]** KF-09 : bucket/clé de sauvegarde séparés, rétention administrée côté
   fournisseur (B2 Object Lock sans verrou de conformité… à dimensionner) — partiellement
   opérationnel (accès hébergeur).
7. **[P1]** KF-11 : tag d'image par SHA court + sauvegarde réussie imposée avant
   `deploy.sh` (rollback documenté).
8. **[P1]** KF-12 : `OnFailure=` sur `kora-backup.service`, sonde externe
   `/health/ready`, contrôle de fraîcheur de la dernière sauvegarde.
9. **[P1]** KF-13 : quota Redis sur les exports (modèle `email/quota.py`),
   `mem_limit`/`cpus` sur api/worker/postgres.
10. **[P1 métier]** KF-15/KF-16 : arbitrage expert-comptable guinéen (TFT, affectations,
    TVA, mentions) — **blocant avant données réelles**, hors code.
11. **[P2]** N-W4 (tests sync/store/actions offline + cache SW), N-I1 (en-têtes Caddy),
    KF-20 (SCA/SBOM + Dependabot), KF-23 (stat avant lecture, streaming, `trap`
    restore.sh), N-B1 (comparaison de payload à l'idempotence : 409 ou `content_hash`).
12. **[P3]** N-B2..B6, N-W1..W3, N-I2..I4.
13. **[Phases produit]** Phase 3 (trésorerie, Mobile Money, rapprochement) puis 4-8 dans
    l'ordre validé du 2026-10-27.

## 9. Limites de ce suivi

Audit statique + exécution locale de la suite API : pas de pentest dynamique
authentifié, pas d'essai de charge, pas d'accès au VPS réel ni au fournisseur S3 de
production. Les constats de concurrence (KF-03, KF-05, KF-07) restent « étayés par le
code », non reproduits dynamiquement — les tests de validation proposés au §8 visent
exactement ces reproductions. Le verdict de l'audit initial est inchangé sur le fond :
**le socle comptable et sécurité est réel, fortement testé et s'améliore ; l'ouverture
commerciale générale reste conditionnée aux P1, aux arbitrages expert-comptable et aux
phases produit restantes.**

## 10. Mise à jour du jour même (clôture de session)

Traité juste après la rédaction de ce rapport, avec CI verte avant chaque fusion :

- **Incident `main` résolu** : PR #21 (motif E2E des dialogues confirm) fusionnée,
  run #48 de `main` vert. Les PR #22 (présent rapport) et #23 (KF-08) ont été
  fusionnées par le mainteneur ; la #23 étant passée avant la CI verte, le job
  « Restauration synthétique » a flanché sur `main` (run #51) — corrigé et
  revalidé par la PR #24 (mot de passe transmis au semis du drill), fusionnée
  **après** CI 7/7 verte.
- **KF-08 : CORRIGÉ** (PR #23 + #24). `/auth/mfa/setup` et `/auth/mfa/enable` exigent
  le mot de passe ; les quatre transitions du second facteur sont sérialisées par
  verrou de ligne utilisateur ; tests nouveaux (422/401) et E2E complétés ; contrat
  régénéré. La déduction KF-08 (−2) du §7 est levée : score porté à **67/100**.
- **Flake de rate-limit réparé au passage** (PR #24) : le test fige désormais la
  fenêtre de comptage (frontière de minute) et purge Redis — même famille que
  l'incident E2E du §3, à noter dans N-W4 pour les suites (tests du §6 frontend).
- Reste prioritaire (§8) : KF-03, KF-05, KF-07, KF-09, KF-11, KF-12, KF-13, puis
  l'arbitrage expert-comptable (KF-15/16) et la phase 3 (trésorerie/Mobile Money).

## 11. KF-03 : corrigé le jour même (suite de la session)

**Correctif** (branche `feature/kora-kf03-verrou-exercice`, commit `1994ec1`) :

- **Migration 0010** (`20261109_0010_verrou_exercice_cloture.py`) : le déclencheur
  `journal_entries_protect` relit désormais l'exercice en `SELECT … FOR UPDATE`
  (`fiscal_years`) — 0007 inchangé, le downgrade restitue sa version. Une validation
  engagée pendant une clôture ou un verrouillage de période attend le commit concurrent,
  relit la version validée (READ COMMITTED) et est refusée si l'exercice est CLOSED ou la
  période verrouillée — le brouillon est conservé.
- **Verrou applicatif assorti** : `entries._fiscal_year_for(…, lock=True)` dans `_post`,
  pris **avant** la numérotation (`_next_number`). Ordre de verrous uniforme « exercice
  puis séquence de journal » dans toutes les transactions (clôture, à-nouveaux,
  réouverture, validation), ce qui exclut tout interblocage — y compris le cas d'un
  à-nouveaux manuel dans l'exercice suivant pendant une clôture.

**Preuve** : `tests/test_closing_concurrency.py`, deux connexions réelles et barrières
`pg_blocking_pids`. Les deux tests « clôture d'abord » et « verrouillage d'abord » étaient
rouges avant correctif (la validation concurrente ne bloquait pas) ; le troisième
(l'interleaving inverse) garantit qu'une validation qui gagne la course figure bien dans
les à-nouveaux. Suite API exécutée intégralement sur l'environnement réel (PostgreSQL 16,
Redis, Garage, Mailpit) : **545/545** (dont 3 nouveaux), ruff, mypy strict ; contrat
d'API inchangé.

**Déductions levées (§7)** : intégrité comptable KF-03 (−2) → 20 ; sécurité socle, moitié
de la course KF-03/KF-07 (−0,75, KF-07 reste ouvert) → 21,75. **Score : 69,75/100.**
Reste prioritaire (§8) : KF-05 (snapshot REPEATABLE READ des rapports), KF-07, KF-09,
KF-11, KF-12, KF-13, l'arbitrage expert-comptable (KF-15/16) et la phase 3.

## 12. KF-05 : corrigé le jour même (suite de la session)

**Correctif** (branche `feature/kora-kf05-instantane-rapports`, PR #28) :

- **`db/snapshot.py`** : `lecture_instantanee(tenant_id)` — le calcul d'un rapport
  multi-requêtes s'effectue dans une transaction **REPEATABLE READ** dédiée, sur une
  connexion neuve du pool. L'option d'isolation est posée **avant toute instruction**
  (portée par le `BEGIN` de psycopg) : elle ne peut pas entrer en conflit avec le
  `set_config('app.tenant_id', …)` du hook `after_begin`, qui reste la première
  instruction de la transaction (RLS et contexte tenant inchangés). Lecture seule :
  la transaction n'est jamais commitée, elle est annulée en fin de bloc.
- **Points d'entrée couverts** : `GET /companies/{id}/ledger` (totaux puis lignes),
  `GET /companies/{id}/financial-statements` (exercices N et N-1 sous le même
  instantané) et les quatre exports (`balance`, `grand-livre`, `ecritures`,
  `etats-financiers`) — le document entier vient d'un seul instantané ; l'écriture au
  journal d'audit et le commit restent sur la session de requête. `GET /trial-balance`
  tient en une seule requête : atomique, inchangé.

**Preuve** : `tests/test_reports_concurrency.py`, deux connexions réelles et barrières
déterministes (écoute `after_cursor_execute` sur la connexion du rapport ; la validation
SQL directe se commit exactement entre les deux requêtes — même motif que le test de
clôture KF-03). **Rouge avant correctif** (READ COMMITTED, reproduit puis corrigé) :

- `full_ledger` avec un compte 522 validé entre les deux requêtes :
  **`KeyError(UUID('…'))`** — l'export de grand livre aurait répondu 500 ;
- `account_ledger` du compte 521 avec une validation intercalée : totaux
  **5 000 000** vs lignes **7 000 000**, `total=1` vs 2 lignes affichées.

Après correctif : 522 absent, totaux = lignes = 5 000 000, solde exact, et la
validation concurrente est bien en base (c'est l'instantané qui l'écarte du rapport).
Suite API exécutée intégralement sur l'environnement réel (PostgreSQL 16.2, Redis
7.4.2, Garage v2.4.1, Mailpit v1.31.3) : **547/547** (dont 2 nouveaux), ruff,
ruff format, mypy strict. Aucun changement de contrat d'API.

**Déductions levées (§7)** : intégrité comptable KF-05 (−2) → 22 ; sécurité socle,
KF-05 pour l'export (−0,5) → 22,25. **Score : 72,25/100.** Reste prioritaire (§8) :
KF-07 (verrou société), KF-09, KF-11, KF-12, KF-13, l'arbitrage expert-comptable
(KF-15/16) et la phase 3 (trésorerie/Mobile Money).

## 13. KF-07 : corrigé le jour même (suite de la session)

**Correctif** (branche `feature/kora-kf07-verrou-societe`) :

- **Verrou de société** : `_ensure_a_director_remains`
  (`organization/service.py:268-292`) relit la société en `SELECT … FOR UPDATE` avant
  le comptage des `PME_DIRIGEANT` (elle faisait un `session.get(Company, …)` sans
  verrou, cf. §4 KF-07). Deux rétrogradations — ou deux retraits — simultanés de deux
  dirigeants distincts sont sérialisées : la seconde attend le commit de la première,
  relit le comptage dans un instantané frais (READ COMMITTED) et est refusée
  (`BusinessRuleError`) s'il ne reste que le membre qui part. Avant correctif, les deux
  comptages se croisaient (l'autre transaction pas encore commitée, donc invisible) et
  le dossier pouvait se retrouver **sans aucun dirigeant**.
- **Ordre de verrous** « membership (`_get_membership`) puis société » : uniforme dans
  `change_member_role` et `remove_member` (qui partagent la vérification) ; le verrou
  de société est acquis en dernier, ce qui exclut tout interblocage avec les autres
  verrous métier.

**Preuve** : `tests/test_director_concurrency.py`, deux connexions réelles et barrière
déterministe (`pg_blocking_pids`), même motif que KF-03 (§11) et KF-06. **Rouge avant
correctif** (reproduit puis corrigé) : la seconde démotion ne bloquait pas et le
dossier finissait avec 0 dirigeant. Après correctif : la seconde démotion attend le
verrou de société, est refusée, le second dirigeant est conservé (1 dirigeant) ; un
second test garantit le comportement séquentiel inchangé. Suite API exécutée
intégralement sur l'environnement réel hors Docker (PostgreSQL 16.2, Redis 7.4.2,
Garage v2.4.1, Mailpit v1.31.3) : **549/549** (dont 2 nouveaux), ruff, ruff format,
mypy strict. Aucun changement de contrat d'API.

**Déductions levées (§7)** : sécurité socle, seconde moitié de la course KF-03/KF-07
(−0,75) → 23. **Score : 73/100.** Reste prioritaire (§8) : KF-09 (bucket de sauvegarde
séparé), KF-11 (tags d'image + sauvegarde avant déploiement), KF-12 (supervision des
sauvegardes), KF-13 (budgets et quotas), l'arbitrage expert-comptable (KF-15/16) et la
phase 3 (trésorerie/Mobile Money).

## 14. KF-09 : corrigé le jour même (suite de la session)

**Correctif** (branche `feature/kora-kf09-bucket-sauvegarde`) :

- Bucket et clé S3 **dédiés** aux sauvegardes (`KORA_BACKUP_S3_*`) : nouveau module
  `storage/backups_store.py` (client boto3 distinct, **aucune fonction de
  suppression**), classes de configuration séparées (`BackupSettings`,
  `BackupAdminSettings`) lues uniquement par les outils de sauvegarde. Le Compose
  (local et VPS) ne transmet ces variables qu'au service one-shot `backup` (profil
  dédié) — jamais à api/worker/migrate/web ni à l'ancrage partagé `x-api-env`.
- **Purge débranchée du chemin automatique** : backup.sh n'appelle plus `prune` ; la
  rétention est administrée côté fournisseur (cycle de vie du bucket ; Object Lock
  B2/S3 sans verrou de conformité, à dimensionner). La purge manuelle exige la clé
  d'administration distincte `KORA_BACKUP_ADMIN_S3_*`, conservée hors VPS, et garde
  toujours les sept plus récentes ; sans elle elle est refusée.
- `infra/garage/bootstrap.py` : bucket `kora-backups` + clé de sauvegarde limitée à
  ce bucket (la clé de l'API n'y a jamais accès) ; `.env.example` et
  `deploy/vps/env.example` complétés ; docs/DEPLOIEMENT.md §5 réécrit (prérequis
  fournisseur explicites : second bucket, clé en lecture/écriture sans suppression,
  séquestration de la clé d'administration hors du serveur).

**Preuve** : `tests/test_backup.py` — 7 tests contre le Garage réel avec bucket de
sauvegarde distinct : upload relu et vérifié, objet altéré refusé, **suppression par
le chemin applicatif (identifiants des pièces) sans effet sur la sauvegarde**, purge
refusée sans clé d'administration (rien n'est supprimé), purge admin conforme au
plancher des sept, clients boto3 distincts. `tests/test_backup_isolation.py` — 6
tests de contrat mécanique : aucune composition ne transmet `KORA_BACKUP_*` aux
services applicatifs (y compris via l'ancrage `x-api-env`), le service `backup` ne
reçoit pas les identifiants des pièces, backup.sh ne purge plus, modèles d'env
complets, préfixes de configuration disjoints. Suite API exécutée intégralement sur
l'environnement réel hors Docker (PostgreSQL 16.15, Redis via fakeredis 2.34.1,
Garage v2.4.1, Mailpit) : **558/558** (dont 9 nouveaux), ruff, ruff format, mypy
strict. Aucun changement de contrat d'API.

**Déductions levées (§7)** : sécurité socle, KF-09 (−1,5) → 24,5. **Score :
74,5/100.** Reste prioritaire (§8) : KF-11 (tags d'image + sauvegarde vérifiée avant
déploiement), KF-12 (supervision des sauvegardes), KF-13 (budgets et quotas),
l'arbitrage expert-comptable (KF-15/16) et la phase 3 (trésorerie/Mobile Money).

## 15. KF-11 : corrigé le jour même (suite de la session)

**Correctif** (branche `feature/kora-kf11-deploiement-versionne`) :

- `deploy/vps/compose.yml` : les images applicatives sont étiquetées par la variable
  de release `KORA_IMAGE_TAG` (`kora-api:${KORA_IMAGE_TAG:-prod}`,
  `kora-web:${KORA_IMAGE_TAG:-prod}`) — l'alias `:prod` n'est plus écrasé avant la
  bascule, la pile en place continue de tourner sur ses images pendant le build.
- `deploy.sh` réécrit, en cinq étapes : **pré-vols** (`.env` complet, branche `main`,
  **copie git propre** — `status --porcelain --untracked-files=no` —, avance
  `--ff-only` sur `origin/main` : le commit déployé est exactement un commit validé
  par la CI, la protection de branche n'acceptant qu'une PR verte) ; **release**
  (SHA court 12 comme tag d'image immuable, `check_storage` sur la nouvelle version) ;
  **sauvegarde pré-migration vérifiée imposée** (`backup.sh` exécuté avec l'image en
  cours, `pg_dump` relu et déchiffré ; sauf première installation, postgres absent,
  avec avertissement explicite) ; **bascule** (`up -d --wait`, migrations par le
  service `migrate`) avec **retour automatique** à la version précédente en cas
  d'échec (migration refusée, healthcheck) ; **consignation** (`releases.log` :
  date, SHA, IDs des images ; `.release` / `.previous-release` ; rétention locale des
  cinq dernières releases).
- `rollback.sh` (nouveau) : retour à `.previous-release` — refuse sans version connue,
  vérifie la présence locale des images, réépingle `KORA_IMAGE_TAG` et repasse
  `up -d --wait` ; les volumes ne sont jamais touchés.
- `backup.sh` / `restore.sh` : image épinglée sur `.release` (fallback `:prod`) — les
  outils de sauvegarde/restauration n'exécutent jamais une image non consignée.
- `.gitignore` : état de release local au serveur (`releases.log`, `.release`,
  `.previous-release`).
- `scripts/check-deploy-versioning.py` (nouveau, job API de la CI) : contrats
  mécaniques sur les sources — tags paramétrés et interdiction de `kora-api:prod` /
  `kora-web:prod` en dur dans le Compose VPS, étapes obligatoires de `deploy.sh` (SHA,
  ff-only, copie propre, backup imposé avant `up -d --wait`, rollback automatique,
  releases.log), contrats de `rollback.sh` (refus sans version, inspection des images),
  épinglage de `backup.sh` / `restore.sh`, et `bash -n` des quatre scripts.
- `docs/DEPLOIEMENT.md` §4 réécrit (release en cinq étapes, retour arrière manuel,
  **convention expand/contract** : le schéma n'est jamais migré en arrière, tout
  changement destructif est reporté à une migration ultérieure) ; Dépannage complété
  (rollback, liste des versions).

**Preuve** : `python3 scripts/check-deploy-versioning.py` ajouté à la CI (job API) ;
syntaxe bash des quatre scripts vérifiée. Suite API exécutée intégralement sur
l'environnement réel hors Docker (PostgreSQL 16.4, Redis 7.4.5, Garage v2.4.1 avec le
bucket `kora-backups`, Mailpit v1.33.1 avec les mêmes variables `MP_SMTP_AUTH_*` que
le Compose) : **558/558**. Aucun changement de contrat d'API.

**Reste** : l'exercice complet sur staging réel — simuler migration refusée, build
indisponible et healthcheck échoué puis rejouer le retour à la version connue —
nécessite l'accès hébergeur (même limite que KF-09 pour l'Object Lock) ; le chemin de
retour est implémenté et vérifié mécaniquement (contrats statiques + syntaxe), pas
encore rejoué sur le VPS. Déduction résiduelle maintenue : −0,5.

**Déductions levées (§7)** : exploitation/production, KF-11 (−2 → −0,5) → +1,5.
**Score : 76/100.** Reste prioritaire (§8) : KF-12 (supervision des sauvegardes :
`OnFailure=`, sonde externe, contrôle de fraîcheur), KF-13 (budgets et quotas :
quota Redis des exports, `mem_limit`/`cpus`), l'arbitrage expert-comptable (KF-15/16)
et la phase 3 (trésorerie/Mobile Money).

## 16. KF-12 : corrigé le jour même (suite de la session)

**Correctif** (branche `feature/kora-kf12-supervision-sauvegardes`) :

- `deploy/vps/kora-backup.service` : `OnFailure=kora-alert@%n.service` — tout échec de
  la sauvegarde quotidienne déclenche désormais l'alerte (oneshot systemd : sans ce
  lien, un échec restait dans le journal, personne n'était prévenu).
- `deploy/vps/kora-alert@.service` + `alert.sh` (nouveaux) : unité d'alerte instanciable
  — trace locale horodatée (`backups/alertes/journal.log`), puis email d'exploitation
  via le conteneur `backup` (`python -m kora.scripts.notify`, destinataire
  `KORA_ALERT_EMAIL`) ; image épinglée à la release (KF-11) ; **anti-tempête** : au plus
  un email par unité défaillante et par 4 h, la trace reste écrite à chaque fois.
- **Contrôle de fraîcheur** : `kora-freshness.service`/`.timer` (quotidien 03:45 UTC,
  après la sauvegarde de 02:30) → `backup-status.sh` →
  `python -m kora.scripts.backup status --max-age-hours 26` (nouvelle sous-commande
  `status` + `freshness()` dans `kora.scripts.backup` : la sauvegarde la plus récente
  du bucket dédié doit dater de moins de 26 h, sinon échec → `OnFailure=`). Le cas
  « sauvegarde qui ne tourne plus sans jamais échouer » (timer désactivé, serveur
  éteint à 02:30, `Persistent=true` non joué) est couvert.
- **Sonde externe** : `kora-probe.service`/`.timer` (toutes les 5 minutes) → `probe.sh`
  → `https://<domaine>/health/ready` : la chaîne complète HTTPS → Caddy → API →
  PostgreSQL/Redis, **certificat TLS inclus**, depuis l'hôte (hors réseau Docker).
  Deux échecs consécutifs (compteur `backups/sonde-etat`, remis à zéro au premier
  succès) → code 1 → `OnFailure=` → alerte. `Caddyfile` : route étroite
  `handle /health/* { reverse_proxy api:8000 }` — les sondes (`/health/live`,
  `/health/ready`, statut ok|erreur des dépendances, aucune donnée métier) sont les
  seuls chemins d'API exposés publiquement.
- `apps/api/src/kora/scripts/notify.py` (nouveau) : notification d'exploitation —
  **honnête** : sans `KORA_ALERT_EMAIL` (nouveau réglage `alert_email` de la config) ou
  avec `KORA_EMAIL_BACKEND=disabled`, l'alerte n'est pas prétendue envoyée (message
  explicite, code de sortie 1) ; corps HTML échappé ; aucun secret transmis.
- `deploy/vps/install-backup-timer.sh` : installe les sept unités (sauvegarde,
  fraîcheur, sonde, alerte + trois timers) d'un seul geste.
- `scripts/check-supervision.py` (nouveau, CI job API) : contrats mécaniques —
  `OnFailure=` sur les trois unités, modèle d'alerte présent, calendriers des deux
  timers, épinglage de release, appel `backup status`, `notify`, route Caddy,
  `KORA_ALERT_EMAIL` dans config/Compose/env.example, `bash -n` des trois scripts.
- `deploy/vps/env.example` (+ `compose.yml`, `docker-compose.yml`) :
  `KORA_ALERT_EMAIL` documenté et transmis au conteneur `backup`.

**Preuve** : suite API complète sur l'environnement réel hors Docker (PostgreSQL 16.4,
Redis 8.0.2, Garage v2.4.1 avec bucket `kora-backups` + clé dédiée, Mailpit v1.33.1) :
**567/567** — dont 9 nouveaux : fraîcheur (récent OK, trop ancienne refusée en
fonction et en CLI, bucket vide refusé) et notification (destinataire, échappement
HTML, refus sans destinataire, refus honnête backend désactivé, usage incomplet).
`python3 scripts/check-supervision.py` → code 0. Aucun changement de contrat d'API.

**Reste** : l'exercice sur VPS réel (recevoir réellement l'email d'alerte après
arrêt de `kora-backup.timer`, et la sonde rouge pendant une coupure) exige l'accès
hébergeur — même limite que KF-09 (Object Lock) et KF-11 (staging). Déduction
résiduelle maintenue : −0,5.

**Déductions levées (§7)** : exploitation/production, KF-12 (−2 → −0,5) → +1,5.
**Score : 77,5/100.** Reste prioritaire (§8) : KF-13 (budgets et quotas : quota Redis
des exports, `mem_limit`/`cpus`), KF-23 (contrôles taille/chemin des sauvegardes),
l'arbitrage expert-comptable (KF-15/16) et la phase 3 (trésorerie/Mobile Money).

## 17. KF-13 — Budgets de ressources et quotas d'exports (2026-11-10)

**Constat** (§4, P1) : aucun budget global — les exports synchrones n'avaient ni rate
limit ni quota (seule borne `MAX_PDF_ROWS = 20 000` lignes), et aucun
`mem_limit`/`cpus` sur les conteneurs : quelques requêtes automatisées (`/exports/*`
en boucle, rendu PDF/Excel entièrement en mémoire) suffisaient à saturer l'API, et un
conteneur fugueur pouvait affamer ses voisins ou l'hôte.

**Correctif** (branche `feature/kora-kf13-budgets-quotas`) :

- `apps/api/src/kora/core/quota.py` (nouveau) : le compteur Redis à fenêtre fixe
  quitte `email/quota.py` (supprimé) — générique et fail-closed : une panne Redis
  lève l'exception, la protection n'est jamais désactivée silencieusement ; clés
  `quota:{scope}:{sujet}:{fenêtre}` ; invitations et récupération de compte passent
  par ce module, comportement inchangé ;
- `exports/service.py` : deux compteurs avant toute lecture sous instantané —
  `export-user` (30/h par utilisateur) puis `export-company` (120/h par dossier) ;
  dépassement → `429` avec `Retry-After` (fenêtre de l'heure), documenté dans le
  contrat OpenAPI des 4 endpoints (`429: {"model": ErrorResponse}`) ;
- `core/config.py` : `exports_per_user_per_hour` / `exports_per_company_per_hour`
  (réglages `KORA_EXPORTS_*`, défauts 30/120) ;
- `docker-compose.yml` + `deploy/vps/compose.yml` : `deploy.resources.limits`
  (mémoire + CPU) sur chaque service de production (postgres 1g/1.0, redis 256m/0.5,
  api 512m/1.0, worker 512m/1.0, web 512m/0.5, storage 512m/1.0, backup 512m/1.0,
  migrate 256m/0.5, mailpit, storage-init et caddy bornés) ; Redis :
  `--maxmemory 200mb --maxmemory-policy noeviction` — au-delà du budget, les
  compteurs échouent fermés plutôt qu'un OOM hôte ; les outils de développement
  (profils tools/e2e) restent explicitement hors budget ; réglages `KORA_EXPORTS_*`
  transmis aux conteneurs, documentés dans `.env.example` et `deploy/vps/env.example` ;
- `scripts/check-compose-budgets.py` (nouveau, CI job API) : budgets attendus par
  service (toute valeur modifiée ou service nouveau exige une décision explicite au
  diff), maxmemory Redis, contrat quota (config, compteurs, 429, fail-closed).

**Preuve** : suite API complète hors Docker (PostgreSQL 16.4, Redis 8.0.2, Garage
v2.4.1, Mailpit) : **573/573** — dont 6 nouveaux (`tests/test_exports_quota.py`) :
quota utilisateur → 429 + Retry-After ; quota par dossier borne l'ensemble des
membres (second membre bloqué avec compteur utilisateur vierge) ; dossiers comptés
séparément ; panne Redis → exception traversante (échec fermé, jamais d'export
dégradé) ; comptage par fenêtre ; panne Redis sur le module. `python3
scripts/check-compose-budgets.py` → code 0. Contrat d'API régénéré : `429` ajouté
aux 4 endpoints exports (openapi.json + schema.ts, +76 lignes, aucun autre
changement).

**Reste** : les budgets (512m API, 1g PostgreSQL…) sont des valeurs de départ pour
un VPS modeste, à affiner avec la charge réelle de staging — exercice déjà compté
sous KF-11 ; déduction résiduelle : 0 (le garde-fou mécanique verrouille le contrat).

**Déductions levées (§7)** : exploitation/production, KF-13 (−1,5 → 0) → +1,5.
**Score : 79/100.** Reste prioritaire (§8) : KF-23 (contrôles taille/chemin des
sauvegardes), KF-20 (SCA/SBOM en CI), l'arbitrage expert-comptable (KF-15/16) et la
phase 3 (trésorerie/Mobile Money).

## 18. KF-23 — Contrôles de taille et de chemin des sauvegardes (2026-11-10)

**Constat** (§4, P2) : la sauvegarde était chargée intégralement en mémoire
(`read_bytes()`) AVANT le contrôle de taille — un fichier de 50 Go (ou un fifo, un
périphérique) saturait la mémoire avant d'être refusé ; le chemin de restauration ne
contrôlait rien (clé libre, fichier déchiffré jamais vérifié avant la confirmation
destructrice, copie en clair qui pouvait traîner) ; aucun test de dépassement.

**Correctif** (branche `feature/kora-kf23-controles-sauvegarde`) :

- `scripts/backup.py` : contrôle par `stat()` AVANT toute lecture — fichier régulier
  exigé (fifo/périphérique refusé sans lire un octet), taille comparée au plafond
  AVANT chargement ; plafond devenu réglage `KORA_BACKUP_S3_MAX_BYTES`
  (`backup_max_bytes`, défaut 400 Mo, aligné sur le budget de 512 Mo du conteneur
  « backup » — KF-13), plancher 1 Mo ; clés imposées au préfixe des sauvegardes
  (`backups/`, ni `..`, ni `//`) en téléchargement ; écriture du fichier déchiffré
  atomique (`.partiel` + `os.replace`) : aucun fichier tronqué ne peut être confondu
  avec un dump restaurable ;
- `deploy/vps/restore.sh` : clé imposée au format `backups/kora-….dump.enc`
  (expression régulière) ; signature `PGDMP` du dump déchiffré vérifiée AVANT la
  confirmation destructrice ; `trap` qui efface `backups/restauration.dump` à la
  sortie (échec, abandon ou succès) — jamais de copie en clair qui traîne ;
- `core/config.py` : `backup_max_bytes` documenté dans `BackupSettings`.

**Preuve** : suite API complète hors Docker : **578/578**, dont 5 nouveaux
(`tests/test_backup.py`) : plafond dépassé refusé sans lecture (bucket vide ensuite),
fichier spécial refusé, clé hors préfixe refusée, destination répertoire refusée +
écriture atomique sans `.partiel` résiduel, contrat restore.sh (clé, PGDMP avant
confirmation, trap). `bash -n restore.sh` OK ; les trois garde-fous CI restent verts.

**Reste** : le traitement reste en mémoire sous le plafond (adapté à des dumps de
quelques centaines de Mo) ; si les bases grossissent au-delà, le streaming chiffré
vers S3 (multipart) est du travail futur explicitement documenté dans le module —
le plafond rend ce choix sûr et visible. Déduction résiduelle : 0.

**Déductions levées (§7)** : exploitation/production, KF-23 (−1 → 0) → +1.
**Score : 80/100.** Reste prioritaire (§8) : KF-20 (SCA/SBOM en CI), l'arbitrage
expert-comptable (KF-15/16) et la phase 3 (trésorerie/Mobile Money).

## 19. KF-20 — SCA, SBOM et scan d'images dans la CI (2026-11-11)

**Constat** (§4, P2) : aucun audit de dépendances dans la CI — pip-audit, npm audit,
Dependabot et trivy tous absents. Une vulnérabilité introduite par une dépendance
entrait en production sans aucun garde-fou.

**Correctif** (branche `feature/kora-kf20-sca-sbom`) :

- `shadcn` déplacé des dépendances de production vers les dépendances de
  développement (`apps/web/package.json`) : le CLI de génération de code n'est jamais
  importé à l'exécution (vérifié : zéro import dans `src/`), ses transitives
  vulnérables (deepmerge, ts-morph, minimatch) sortent de l'arbre de production.
  Résultat : `npm audit --omit=dev` passe de 6 vulnérabilités à **0** ;
- Makefile : `api-audit` (pip-audit sur l'environnement verrouillé du conteneur dev,
  `/opt/venv` — exactement ce que ruff/mypy/pytest utilisent), `web-audit`
  (production sans tolérance : `--omit=dev --audit-level=low` ; arbre de
  développement sans haut ni critique : `--audit-level=high`), `sbom` (CycloneDX via
  `cyclonedx-py` et `@cyclonedx/cyclonedx-npm`, sortis dans `sbom/`), cible agrégée
  `sca` ;
- CI : nouveau job **bloquant** `sca` dans `ci.yml` (mêmes conteneurs épinglés que
  les autres jobs), ajouté aux `needs` du « Résultat » ; SBOM conservés en artefacts
  (30 jours) ;
- `.github/dependabot.yml` (nouveau) : écosystèmes pip (`apps/api`), npm (`apps/web`)
  et github-actions, veille hebdomadaire lundi 04:00 Europe/Paris, PR limitées à 10
  par écosystème ;
- `.github/workflows/security-scan.yml` (nouveau) : scan hebdomadaire des images
  runtime API et Web par trivy 0.65.0 (image épinglée, même convention que gitleaks),
  HIGH/CRITICAL corrigées uniquement (`--ignore-unfixed`), rapports en artefacts
  (90 jours) ; informationnel à l'installation, passage en bloquant après
  stabilisation de la baseline (documenté dans le fichier).

**Preuve** : `pip-audit` sur l'environnement verrouillé : **aucune vulnérabilité
connue**. `npm audit --omit=dev --audit-level=low` : **0 vulnérabilité** (exit 0) ;
`npm audit --audit-level=high` : exit 0 (2 low, 10 moderate, toutes dans l'outillage
de développement : shadcn/@shadcn/registry via deepmerge
GHSA-gcqx-w48m-w2h4, minimatch GHSA-g3hv-75wg-m249 via ts-morph et
typescript-eslint 8.72.2 — aucune version corrigée publiée à ce jour) ; la même
commande avec `--audit-level=moderate` échoue (exit 1), preuve que le verrou bloque.
SBOM générés et validés : API **76 composants** (CycloneDX 1.6), Web **670
composants** (CycloneDX 1.7). Suite web réexécutée après le déplacement de shadcn :
ESLint (0 avertissement), tsc strict, Vitest **60/60**, build Next de production OK.
Les trois fichiers YAML validés par un parseur ; `make -n sca` reprend exactement les
commandes conteneurisées de la CI.

**Reste** : les 12 advisories de l'arbre de développement subsistent (pas de
version corrigée disponible) — sous verrou « haut/critique », surveillées par
Dependabot ; le scan trivy hebdomadaire est informationnel au départ (baseline des
images à stabiliser avant de le rendre bloquant) ; Dependabot s'activera à la
détection du fichier par GitHub. Déduction résiduelle : 0.

**Déductions levées (§7)** : qualité logicielle, KF-20 (−1 → 0) → +1.
**Score : 81/100.** Reste prioritaire (§8) : l'arbitrage expert-comptable
(KF-15/16), la phase 3 (trésorerie/Mobile Money), KF-14 (CSP) et la vérification en
staging (KF-11).

## 20. KF-15 — Arbitrage expert-comptable et TFT en méthode directe (2026-11-11)

**Constat** (§4, P1) : jeu d'états SYSCOHADA incomplet (pas de TFT ni notes annexes) —
à arbitrer par un expert-comptable. La phase 2e-bis était restée ouverte « méthode à
valider avant implémentation ».

**Arbitrage** (`docs/ARBITRAGE_COMPTABLE.md`, nouveau) : le TFT est livré en **méthode
directe** — les flux sont les mouvements réels des comptes de trésorerie (classe 5,
même définition que le bilan), classés d'après la contrepartie de chaque écriture
valide, ligne à ligne (une écriture « remboursement + intérêts » est ventilée
automatiquement). Trois sections (opérationnel, investissement, financement) encadrées
par la trésorerie d'ouverture et de clôture ; les à-nouveaux (origine CLOSING) portent
l'ouverture, même convention que le bilan. Un contrôle indépendant recalcule le solde
réel de la classe 5 à la date de coupure : toute divergence (`coherent = false`) ou
contrepartie sans affectation (`unmapped_accounts`) est signalée, jamais ignorée.
Classement des charges financières payées (opérationnel) documenté et à confirmer en
revue finale ; notes annexes arbitrées en livraison progressive (phase 3+) ; KF-16
closé côté produit (aucun taux codé en dur, mentions factures planifiées phase 4,
conservation sans suppression).

**Correctif** (branche `feature/kora-kf15-tft-arbitrage`) :

- référentiels versionnés `tft_syscohada_2017.csv` (lignes, sections, totaux) et
  `tft_affectations_2017.csv` (76 préfixes couvrant toutes les classes hors 5) ;
  chaque compte du plan est affecté (test), la variation XV couvre chaque ligne une
  fois exactement (test d'expansion) ;
- `accounting/cashflows.py` : moteur TFT (mouvements par écriture, ventilation par
  contrepartie, ouverture par à-nouveaux, contrôle indépendant) ;
- route `GET /companies/{id}/cash-flow-statement` (N et N-1 sous le même instantané
  REPEATABLE READ, comme les autres états) ; contrat d'API régénéré ;
- web : onglet « Tableau des flux de trésorerie » dans les états financiers
  (synthèse ouverture/variation/clôture, badge de cohérence, N-1 en comparaison,
  sections et postes, postes nuls masqués par défaut) ; i18n fr/en ; le marqueur
  « TFT à venir » est retiré.

**Preuve** : suite API complète hors Docker : **591/591**, dont 10 nouveaux
(`tests/test_cashflows.py` : couverture du plan, expansion des totaux, classe 5
exclue, jeu de référence, ventilation multi-contreparties, acquisitions/cessions/
subventions + virements internes sans flux, ouverture par à-nouveaux + comparatif
N-1, troncature à date, invariant de cohérence sur 40 écritures aléatoires, garde-fou
contrepartie inconnue). Ruff, mypy strict, ESLint, tsc, Vitest 60/60, build Next OK ;
contrat bloquant à jour (67 chemins). Les affectations couvrent les 520 comptes du
plan (test), y compris les racines et nœuds intermédiaires.

**Reste** : export PDF/Excel du TFT (même chemin que les exports des autres états) ;
classement des charges financières payées à confirmer par la revue finale ; notes
annexes livrées progressivement à partir de la phase 3 (cf. arbitrage §2).
Déduction résiduelle KF-15 : TFT livré (−1 → 0) ; la déduction « arbitrage expert »
(−2) reste ouverte jusqu'à la revue finale documentée par un inscrit à l'ONECCA.

**Déductions levées (§7)** : intégrité comptable, TFT absent (−1 → 0) → +1.
**Score : 82/100.** Reste prioritaire (§8) : la phase 3 (trésorerie/Mobile Money),
la revue expert-comptable finale (KF-15/16 : −2 résiduels), KF-14 (CSP) et la
vérification en staging (KF-11).

## 21. N-B6 — Plafonds de session PostgreSQL au runtime (2026-11-11)

**Constat** (§5, P3) : aucun `statement_timeout`/`lock_timeout` par défaut au runtime —
une lecture d'export pouvait retenir des verrous indéfiniment.

**Correctif** (branche `feature/kora-nb6-timeouts-session`) :

- `core/config.py` : `statement_timeout_ms` (défaut 60 000) et `lock_timeout_ms`
  (défaut 5 000), réglables via `KORA_STATEMENT_TIMEOUT_MS` / `KORA_LOCK_TIMEOUT_MS`,
  0 pour désactiver (à éviter en production) ; documentés dans `.env.example` et
  `deploy/vps/env.example` (activés par défaut sur le VPS) ;
- `db/session.py` : les options psycopg sont passées à chaque connexion du moteur du
  runtime (API et worker). Les migrations (rôle propriétaire, DDL long) ne sont pas
  concernées.

**Preuve** : 4 tests nouveaux (`tests/test_runtime_settings.py`) : réglages et
surcharge d'environnement, validation (négatif refusé), chaîne d'options générée
(vide quand 0), et **annulation réelle** — une connexion avec
`statement_timeout=100` exécutant `pg_sleep(1)` lève bien l'erreur de dépassement.
Le moteur du test est détruit explicitement (`dispose()`) : une connexion oubliée au
ramasse-miettes déclenchait une ResourceWarning « unraisable » imputée au setup du
test suivant (course de nettoyage, corrigée). Suite locale : 35/35 sur les fichiers
concernés (runtime_settings, cashflows, statements), ruff + mypy strict verts.

**Reste** : déduction résiduelle 0.
**Déductions levées (§7)** : sécurité du socle, N-B6 (−0,5 → 0) → +0,5.
**Score : 82,5/100.** Reste prioritaire (§8) : la phase 3 (trésorerie/Mobile Money),
la revue expert-comptable finale (KF-15/16), KF-14 (CSP) et la vérification en
staging (KF-11).

## 22. Phase 3A — Comptes financiers : banques, caisses, Mobile Money (2026-11-11)

**Constat** (`docs/PLAN.md`) : phase 3 entièrement à livrer ; aucune notion d'opéré
de trésorerie hors écritures libres.

**Livré** (branche `feature/kora-3a-comptes-financiers`) : migration `0011`
(`financial_accounts`, `financial_movements` : RLS, immuabilité par déclencheur,
contraintes type ↔ sens ↔ liens en base) ; service trésorerie — chaque mouvement
(dépôt, retrait, frais, virement interne) crée **atomiquement** une écriture validée
du journal de trésorerie (BQ/CA/MM) et sa trace immuable, avec verrous `FOR UPDATE`
sérialisant les mouvements concurrents (virements : ordre par identifiants,
anti-interblocage) ; solde toujours recalculé du grand livre (jamais stocké) ;
permissions `treasury:read`/`treasury:manage` (matrice régénérée et sondée sur les
7 rôles) ; API `/treasury/*` (contrat 70 chemins) ; page Trésorerie complète
(comptes, soldes, historique, formulaires), i18n fr/en.

**Preuve** : 623/623 tests API hors Docker (PG 16.15, Redis 8.0.2, Garage 2.4.1,
Mailpit réels), dont 14 trésorerie — dépôts concurrents sérialisés avec solde final
exact, immutabilité refusée par la base, période verrouillée refusée, isolation 404,
audit tracé ; ESLint, tsc, Vitest 60/60, build Next OK. CI GitHub en attente : quota
Actions épuisé (dépôt privé) — validation locale documentée dans la PR.

**Reste** : 3B (import relevés), 3C (rapprochement), 3D (connecteurs), 3E
(prévisions) ; classement des portefeuilles Mobile Money (52) à confirmer en revue
expert. **Déductions §7** : périmètre fonctionnel, phase 3 entamée (+1).
**Score : 83,5/100.** Prochaines priorités : 3B import de relevés, revue expert
(KF-15/16), KF-14 (CSP), vérifications staging (KF-11).

## 23. Phase 3B — Import de relevés bancaires OFX/CSV (2026-11-11)

**Constat** (`docs/PLAN.md`, §8) : après la 3A (comptes financiers), le lien
opérationnel avec les banques exige l'import des relevés — aujourd'hui, les
écritures de trésorerie ne naissent que d'une saisie manuelle.

**Correctif** (branche `feature/kora-3b-import-releves`, empilée sur la 3A) :

- migration `0012` : `bank_statements` + `bank_statement_lines` (RLS + FORCE RLS,
  FKs composites tenant, trigger de cohérence par CHECK — MATCHED ⇔ mouvement lié) ;
  empreinte du fichier **unique par (dossier, compte)** : réimport refusé en base ;
  empreinte métier des lignes pour le signalement des doublons entre relevés qui
  se recouvrent ;
- parseur sans dépendance : OFX 1.x SGML (balises non fermées), OFX 2.x XML, CSV
  à en-tête FR ou inféré des données ; débit/crédit séparés → signe correct ;
  espaces insécables, virgule décimale, JJ/MM/AAAA, cp1252 ; arrondi GNF au plus
  près, lignes sans date ni montant jamais inventées ;
- service : import atomique avec objet original chiffré au stockage (traçabilité,
  litige banque), verrou de compte anti-imports concurrents, plafonds réglables
  (5 Mo / 5 000 lignes), tri des lignes (ignorer/remettre, idempotent, MATCHED
  réservé à la 3C), suppression d'un relevé non rapproché ; audit complet ;
- API + contrat + types TS ; page Trésorerie augmentée (liste, import, lignes,
  doublons signalés, tri, suppression), i18n fr/en ; permissions 3A réutilisées.

**Preuve** : **667/667** tests API hors Docker (PG 16.15, Redis, Garage, Mailpit
réels), dont 26 nouveaux (14 parseur + 12 API : dédup, doublons symétriques,
idempotence du tri, lecteur 200/403, isolation 404, 413, plafond de lignes) ;
ruff, mypy strict, contrat, ESLint, tsc, Vitest 60/60, build Next OK ; E2E
Playwright **31/31 chromium + 31/31 mobile** contre la pile native. CI GitHub
toujours en attente de quota ; validation locale documentée dans la PR.

**Reste** : 3C (rapprochement ligne ↔ mouvement, proposition assistée avec
confirmation humaine obligatoire), 3D (connecteurs Orange/MTN — API officielles
seulement), 3E (prévisions de trésorerie 30/60/90 jours).
**Déductions §7** : périmètre fonctionnel, phase 3 poursuivie (3B livrée) : +0,5.
**Score : 84/100.** Prochaines priorités : 3C rapprochement, revue expert
(KF-15/16), KF-14 (CSP), vérifications staging (KF-11).

## 24. Fusion des PRs 55-59 sur `main` — pile composée revalidée (2026-11-12)

**Constat** : les 5 PRs ouverts (#55 React 19.3.1, #56 Playwright 1.65, #57 export
TFT KF-15, #58 trésorerie 3A, #59 import relevés 3B) restaient « en erreur » sans
défaut de code : quota GitHub Actions épuisé (dépôt privé, spending limit 0 $). Les
jobs sont rejetés à la file en 2-3 secondes avec **0 étape exécutée** (sonde de
re-run documentée). Sans spending limit, aucune CI ne peut tourner avant le reset du
1er décembre.

**Décision** : re-vérification locale intégrale puis fusion séquentielle
**#57 → #55 → #56 → #58 → #59** (API GitHub, commits de merge, aucun conflit ; le
#59 contient la 3A et a été revalidé sur sa branche avant fusion : 667/674 pytest,
contrat, web, E2E 62/62).

**Preuve sur `main` composé** (pile rootless native : PG 16.4, Redis 7.4.6, Mailpit
1.31.3 avec AUTH, Garage 2.4.1 — buckets `kora`, `kora-test`, `kora-backups`) :
ruff check + format OK ; mypy strict OK (156 fichiers) ; **674/674** tests pytest
(dont le test SMTP réel contre Mailpit) ; contrat OpenAPI — `openapi.json` identique
et types TS régénérés sans diff ; 4 checks transverses (séparation
runtime/migration, versionnement KF-11, supervision KF-12, budgets/quotas KF-13) OK
; ESLint 0 warning, tsc strict, **Vitest 60/60**, build Next OK ; E2E Playwright
**62/62** (31 desktop + 31 mobile) sur les versions appairées React **19.3.1** et
Playwright **1.65.0** (chromium 1254) ; `npm audit` production : 0 vulnérabilité.

**Reste à la CI** (daemon Docker indisponible en sandbox) : restauration synthétique
(restore-drill), pip-audit et SBOM CycloneDX — à rejouer dès que le quota Actions
est restauré.

**Reste** : inchangé — 3C rapprochement (confirmation humaine obligatoire), revue
expert (KF-15/16), KF-14 (CSP), vérifications staging (KF-11), puis 3D connecteurs
et 3E prévisions. **Déductions §7** : aucune variation — le score ne bouge pas, la
preuve d'intégration s'ajoute à la 3A/3B déjà comptabilisées. **Score : 84/100.**

## 25. Phase 3C — Rapprochement bancaire assisté (2026-11-12)

**Constat** (`docs/PLAN.md`, §8) : après la 3B, les relevés importés s'accumulent
sans être confrontés au grand livre. Le rapprochement ligne ↔ mouvement est le
geste quotidien du dirigeant : il doit être assisté mais jamais automatisé.

**Correctif** (branche `feature/kora-3c-rapprochement`) :

- migration `0013` : unicité (dossier, mouvement) sur `bank_statement_lines` —
  deux lignes, même issues de deux relevés distincts, ne peuvent pas désigner le
  même mouvement : le double comptage devient impossible en base ;
- moteur conservateur (`kora/treasury/reconciliation.py`) : candidats du **même
  compte**, montant **strictement égal**, direction cohérente (entrée ⇔ DEBIT),
  fenêtre ±180 jours, mouvement jamais rapproché ; score de ressemblance (date
  exacte +30, ≤3 j +18, ≤7 j +8, mot de libellé commun +10), 5 candidats au plus ;
  **aucun appariement automatique** — les écarts (agios, arrondis) se traitent par
  un mouvement dédié, pas par un rapprochement forcé ;
- confirmation réversible : verrous ligne puis mouvement (ordre unique),
  re-vérification complète sous verrou, contrainte unique en dernier rempart
  (`IntegrityError` → 409 propre) ; dé-rapprochement remettant la ligne en
  attente et le mouvement en disponibilité ; audit
  `treasury.reconciliation.matched` / `.unmatched` (relevé, ligne, mouvement,
  écriture) ;
- vue d'ensemble par compte : compteurs PENDING/MATCHED/IGNORED, montant restant
  à expliquer (somme des lignes en attente), mouvements libres ;
- API `/candidates`, `/match`, `/unmatch`, `/reconciliation` (contrat 74 chemins,
  types TS régénérés) ; page Trésorerie augmentée : bandeau de vue d'ensemble,
  panneau de candidats par ligne (écart en jours, écriture liée), Confirmer /
  Retirer avec confirmation ; i18n fr/en.

**Preuve** : **698/698** tests API hors Docker (PG 16.4, Redis, Garage, Mailpit
réels), dont 12 nouveaux (classement des candidats, exclusions compte/montant/
direction/déjà-rapproché, double rapprochement refusé **y compris en concurrence
réelle** : deux confirmations simultanées → 200 + 409, une seule ligne MATCHED,
montant/direction/compte incohérents refusés, réversibilité complète, vue
d'ensemble, lecteur propose mais ne confirme pas (403), isolation 404) — la suite
d'isolation générique a automatiquement couvert les 4 nouvelles routes (+12) ;
ruff, mypy strict, contrat, 4 checks transverses, ESLint, tsc, Vitest 60/60,
build Next OK ; E2E Playwright **64/64** (nouveau parcours complet desktop +
mobile : compte → mouvement → import CSV → candidats → confirmer → MATCHED →
retirer → PENDING).

**Reste** : 3D connecteurs Orange/MTN Money (API officielles uniquement), 3E
prévisions de trésorerie 30/60/90 jours ; revue expert (KF-15/16), KF-14 (CSP),
vérifications staging (KF-11). **Déductions §7** : périmètre fonctionnel, phase 3
poursuivie (3C livrée) : +0,5. **Score : 84,5/100.** Prochaines priorités :
revue expert (KF-15/16), 3E prévisions, KF-14 (CSP), vérifications staging
(KF-11).

## 26. Jeu de données fictif pour les tests locaux (2026-11-12)

**Constat d'origine** : l'utilisateur ne peut pas tester le produit chez lui sans
données. Kora n'expédie aucun jeu d'essai : un dossier vierge ne démontre ni la
saisie guidée, ni le lettrage, ni l'import de relevés, ni le rapprochement.

**Livré** : `kora.scripts.seed_demo` (script de démonstration, hors API — aucune
route touchée) :

- dossier fictif « Djouma Distribution SARL » (SARL guinéenne, GNF, exercice 2026),
  3 utilisateurs aux trois rôles PME, sous-comptes clients/fournisseurs et de
  trésorerie, 3 comptes financiers (BANQUE/CAISSE/MOBILE_MONEY ORANGE_MONEY_GN) ;
- 74 écritures validées + 1 brouillon volontaire, 36 mouvements de trésorerie,
  10 lettrages automatiques — **tout via les services applicatifs** (aucune
  écriture directe, même imputation TVA que l'application) ;
- 3 relevés fictifs générés **depuis les mouvements réels** (CSV octobre, OFX
  novembre, CSV Orange Money) + 5 anomalies garanties sans candidat (agios,
  commission recouvrement, commission agent, remise de chèque inconnue, alerte
  SMS à ignorer) pour exercer l'import 3B puis le rapprochement 3C ;
- `--reset` : purge par connexion propriétaire — les tables tenant sont sous RLS
  forcée et le grand livre en ajout seul, donc le script désactive le temps de la
  cascade les 4 déclencheurs d'immuabilité, fixe le tenant courant puis les
  réactive dans une transaction unique ; `KORA_DATABASE_MIGRATION_URL` est exigé
  explicitement (le conteneur `api` ne le porte pas : séparation runtime/DDL).
- Guide utilisateur : `docs/DEMO.md`.

**Preuve (locale, PG 16.4/Redis/Garage/Mailpit réels)** : seed exécuté puis
re-exécuté avec `--reset` (sortie déterministe) ; les 3 relevés sont lus par le
parseur applicatif, importés par le service (double import refusé — déduplication
vérifiée), et le moteur de rapprochement propose un candidat pour les 17 lignes
connues avec exactement 5 lignes sans candidat ; ruff, mypy strict,
**698/698** pytest (aucun test modifié), contrat OpenAPI inchangé, gitleaks sans
nouveau signalement (les 5 alertes existantes sont celles déjà connues des tests).

**Limites** : les pièces jointes démontrées restent celles des tests E2E ; les
fichiers de relevés sont générés dans le conteneur (`--out`) et doivent être
récupérés côté poste pour l'import via l'interface. Aucune donnée réelle : tous
les noms, RCCM et NIF sont inventés.

**Score** : pas de changement fonctionnel ni de sécurité sur le produit — le
moteur existant est simplement démontrable de bout en bout. **Score : 84,5/100**
(inchangé).

## 27. C3 — seed_demo : repli automatique du répertoire de sortie (2026-11-12)

**Constat d'origine (validé en session Windows 11 + Docker, 2026-11-12)** :
`python -m kora.scripts.seed_demo --out demo` échoue avec
`PermissionError: '/app/demo'` — le conteneur API est durci (utilisateur non-root
`kora`, `/app` monté en lecture seule) et refuse toute écriture hors `/tmp`. Le
contournement documenté (`--out /tmp/demo` puis `docker compose cp`) restait
manuel et non guidé.

**Livré** : `resolve_out_dir(requested) -> tuple[Path, str | None]` dans
`kora.scripts.seed_demo`, appelé dès `main()` (fail fast, avant toute écriture en
base) :

1. sonde d'écriture (fichier `.kora-seed-probe` créé puis supprimé) ;
2. répertoire demandé inscriptible → utilisé tel quel, aucun message ;
3. sinon → repli `/tmp/kora-demo` + consigne exacte affichée sur stdout :
   `mkdir -p ./demo-export && docker compose cp api:/tmp/kora-demo/. ./demo-export/` ;
4. repli lui-même refusé → l'`OSError` d'origine remonte : **aucune perte
   silencieuse** de fichiers de démonstration.

`docs/DEMO.md` §4 mis à jour (comportement automatique au lieu du contournement
manuel).

**Preuve (locale, bac à sable Linux)** : fonction exécutée sur les 3 cas —
répertoire inscriptible utilisé sans message ; répertoire chmod 0o555 → repli
`/tmp` + consigne complète ; repli lui-même chmod 0o555 → `OSError` honnête.
Tests unitaires `tests/test_seed_demo_out_dir.py` : 5 cas (2 marqués skipif sur
Windows où le chmod de répertoire est sans effet ; la voie heureuse reste couverte
partout). Syntaxe du module vérifiée ; la suite d'intégration complète reste à
exécuter sur la pile Docker (CI à confirmer — quotas Actions).

**Score** : confort d'usage de la démonstration, aucun changement de production ni
de sécurité. **Score : 84,5/100** (inchangé).

## 28. Phase 3E — Prévision de trésorerie 30/60/90 jours (2026-11-12)

**Livré** (branche `feature/kora-cashflow-forecast`, un seul PR : backend + frontend +
migration + tests + docs) :

- **Moteur pur** `kora/cashflow/engine.py` : trois sources — OBSERVE (soldes réels),
  ENGAGE (écritures validées datées dans le futur), ESTIME (moyenne des mois complets
  passés) ; trois scénarios (optimiste/neutre/prudent, coefficients documentés dans
  `assumptions.py` et sérialisés dans chaque sortie) ; détection de tension (première
  date sous le seuil critique) ; agrégat `beyond_horizon` (aucun flux au-delà de
  l'horizon n'est perdu) ; arithmétique 100 % entière (BigInt côté TS, int côté API,
  aucune division flottante).
- **API** 7 endpoints sous `/cashflow/*` : prévision, export PDF/XLSX **inscrit au
  journal d'audit**, seuils (GET/PUT), instantanés (GET/POST), prévision vs réalisé.
  Consultation `treasury:read` (rôles de lecture inclus), écritures `treasury:manage`
  — la prévision ne modifie jamais la comptabilité.
- **Migration 0014** (renumérotée depuis 0011 : 3A/3B/3C ont pris 0011-0013) :
  `cashflow_settings`, `cashflow_snapshots`, `cashflow_snapshot_lines` — tables
  tenant, RLS ENABLE+FORCE, policy `tenant_isolation`, FK composites (tenant_id, id).
- **Frontend** : page `tresorerie/previsions` mobile-first (horizon/scénario portés
  par l'URL), graphique hebdomadaire BigInt + détail journalier, hypothèses affichées
  (« Comment ce chiffre est calculé »), brouillons futurs exclus listés, instantanés ;
  exports via la liste blanche `exports.ts` (kind `previsions-tresorerie`) et le
  proxy BFF ; navigation du dossier `treasury:read` ; i18n fr/en fusionnés.
- **Contrat** : statuts/scénarios en `Literal`, hypothèses en modèle `AssumptionsOut`
  (plus de `dict[str, object]`) — `schema.ts` régénéré (addition pure vérifiée).

**Adaptations au `main` réel** (les 5 points du guide d'intégration) : registre des
routeurs, registre des modèles `db/models.py`, migration renumérotée (parent 0013),
fusion i18n fr/en, fusion DAL (4 fonctions), lien de navigation, permissions
`treasury:*` (plus fines que `entries:*`), contrat + types TS resynchronisés.

**Preuves locales (uv, Python 3.13.18, 2026-11-12)** : pytest moteur **40/40** ;
ruff check + format : verts (183 fichiers) ; **mypy strict : 168 fichiers OK** ;
`tsc --noEmit` strict **0 erreur** ; ESLint `--max-warnings=0` **0 problème** ;
vitest **69/69** ; `openapi.json` + `schema.ts` régénérés, addition pure sémantique
vérifiée hors chemins cashflow.

**Limites (levées le 13/11)** : les tests d'intégration et la garde alembic ont
été exécutés sur une pile locale réelle (PostgreSQL 17.11, Redis, S3 d'essai,
Mailpit) — voir le complément ci-dessous. Restent les écrans de figeage et de
réglage des seuils (PR de suivi, l'API existe) et l'enrichissement du seed
(chèque post-daté, brouillon fournisseur futur).

### 28 bis. Corrections à l'ouverture du PR (2026-11-13)

La première exécution **réelle** de la suite complète (jusque-là bloquée : aucun
PostgreSQL local, CI indisponible) a révélé quatre défauts, corrigés et couverts :

1. **Transactions jamais validées** : `PUT /cashflow/settings` et
   `POST /cashflow/snapshots` ne faisaient qu'un `flush()` — annulé à la fermeture
   de la session par requête. Les seuils paramétrés étaient ignorés par la
   prévision et les instantanés invisibles au listing. Correction : `db.commit()`
   explicite après l'événement d'audit (patron `invitations.py`/`treasury.py`),
   transaction unique couvrant données + audit.
2. **FK manquante dans la migration 0014** : la garde autogenerate
   (`test_modeles_et_migrations_synchronises`) a détecté l'écart entre le modèle
   `CashflowSnapshotLine` (FK simple `tenant_id → companies.id`, CASCADE) et la
   table créée (FK composite seulement). Corrigé dans la migration — la convention
   « les deux clés » est celle de `journal_lines` (0005). Référence docstring du
   modèle rectifiée (0011 → 0014, renumérotation).
3. **Hypothèses tronquées dans la réponse API** : `AssumptionsOut` déclarait 8
   champs et pydantic rejetait silencieusement les 5 autres
   (`categories_inflow/outflow`, `treasury_scope`, `committed_rule`,
   `estimated_rule`). Modèle complété, contrat régénéré (`openapi.json`,
   `schema.ts`, addition pure).
4. **Catégories polluées par des buckets 0** : chaque flux matérialisait sa
   catégorie dans les DEUX sens via defaultdict (ex. `FOURNISSEURS: 0` dans les
   encaissements). Correction : un flux n'alimente que son sens.

Deux attentes de test rectifiées (elles oubliaient la moyenne /3 sur les
décaissements — le moteur applique Σ/N aux deux flux, documenté et couvert par
les 40 tests moteur).

**Preuve complète (2026-11-13, pile locale réelle : PostgreSQL 17.11 + Redis +
S3 d'essai + Mailpit)** : **pytest 770/770** (suite intégrale, y compris 11
intégration cashflow, garde alembic, sauvegardes, SMTP réel) en 5 min 06 ; ruff
check + format verts (183 fichiers) ; mypy strict 168 fichiers OK ; `tsc --noEmit`
0 erreur ; ESLint 0 ; vitest 69/69.

**Score** : première projection de trésorerie de Kora — aide à la décision sans
toucher au grand livre, aucune écriture inventée, permissions cohérentes avec la
3A. Attend la revue + CI pour créditer le score. **Score : 84,5/100** (inchangé en
l'état, PR ouvert).

## 29. Fusion des PRs 70-73 sous blocage CI de facturation (2026-11-13)

**Diagnostic CI clos avec preuve officielle** (même signature que §24, cette fois
documentée par GitHub lui-même) : re-exécution du run `43262026312` (branche
repo-hygiene, attempt 2) → 8 jobs rejetés en ~3 s, **0 step exécuté, aucun runner
attribué, aucun log** ; l'annotation du check-run renvoie :

> « The job was not started because recent account payments have failed or your
> spending limit needs to be increased. Please check the 'Billing & plans' section
> in your settings »

Cause racine : **paiement du compte GitHub échoué / limite de dépenses** — pas un
défaut de code (`main` rouge depuis le 11/11, y compris sur des PR passées
anciennes). Constat associé : l'API de protection de branche renvoie 403
(« Upgrade to GitHub Pro or make this repository public ») : faute de paiement Pro,
**aucune protection de branche n'est active côté GitHub** en ce moment. La
discipline du projet (branche `feature/kora-*` → validation locale complète → PR →
merge uniquement après vérifications) continue d'être appliquée intégralement, par
engagement, même sans contrainte GitHub.

**Fusion** : séquence **#72 (.gitattributes) → #71 (docs Windows) → #70
(`resolve_out_dir`) → #73 (Phase 3E)** par l'API GitHub. Conflits résolus sur
branches avant fusion (historique des PR conservé) :

1. #70 : `worklog.md` (entrées C2+C3 toutes deux conservées) ; `docs/DEMO.md`
   §5.3/§5.4 passés au présent — le repli automatique est désormais fusionné ;
2. #73 : `worklog.md` (3E au-dessus de C2/C3, « les plus récentes en haut ») ;
   `AUDIT_SUIVI_20261109.md` renuméroté proprement (§27 C3, §28 3E).

**Revalidation du composé** : l'arbre de la branche 3E fusionnée et celui de
`main` après les quatre merges sont **identiques bit à bit** (arbre git
`515f3b5b` vérifié des deux côtés) — la preuve ci-dessous vaut donc pour `main` :

| Contrôle | Résultat |
|---|---|
| pytest complet (PG 17.11 + Redis + S3 d'essai + Mailpit réels) | **775/775** (5 min 08) |
| ruff check + format | verts (169 fichiers) |
| mypy `--strict` | verts (169 fichiers) |
| ESLint `--max-warnings=0` | verts |
| `tsc --noEmit` (typegen + strict + noUncheckedIndexedAccess) | 0 erreur |
| Vitest | **69/69** |
| Contrat OpenAPI (`export_openapi` vs `openapi.json` committé) | **identique** (85 chemins, 140 schémas) |

Reste à la CI quand la facturation sera régularisée : restauration synthétique
(restore-drill), pip-audit/SBOM, E2E Playwright — à re-jouer sur `main`. Chaque PR
fusionné porte un commentaire public « Statut CI : blocage facturation du compte »
avec l'annotation officielle citée.

**Score** : même politique qu'aux §24 et §25 — preuve locale complète mais CI
encore indisponible : **84,5/100** (inchangé ; le crédit +0,5 attendu pour 3E sera
attribué dès confirmation CI). Action utilisateur requise : GitHub Settings →
Billing & plans (régler le paiement ou relever la limite de dépenses), puis
re-jouer les workflows sur `main`.
