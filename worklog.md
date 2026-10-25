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

**Reste** : fournisseur S3 de production à choisir (bucket privé, clé limitée au bucket,
https) ; quota de stockage par dossier (avec les abonnements, phase 8) ; aperçu des PDF
dans le navigateur selon sa politique CSP (le téléchargement fonctionne partout) ;
purge des objets orphelins si worker et stockage sont tous deux indisponibles (journalisé
en erreur) ; 2g2 saisie guidée, 2g3 brouillons hors connexion.
