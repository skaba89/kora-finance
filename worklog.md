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
