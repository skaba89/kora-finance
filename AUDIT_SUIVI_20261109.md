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
