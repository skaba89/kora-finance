# Kora Finance

Gestion financière et comptable pour les PME guinéennes et les cabinets comptables :
comptabilité SYSCOHADA révisé, rapprochement Mobile Money et bancaire, états financiers
prêts pour un dossier de crédit.

## Démarrage

Prérequis : Docker (avec Compose v2) et `make`. Aucun Node ni Python local n'est nécessaire.

```bash
make env     # génère .env avec des secrets aléatoires
make up      # construit et démarre la pile, attend que tout soit sain
```

| Service | URL |
|---|---|
| Application web | http://127.0.0.1:3100 |
| API | http://127.0.0.1:8100 — docs : http://127.0.0.1:8100/api/docs |
| PostgreSQL | 127.0.0.1:55432 (rôles `kora_owner` / `kora_app`, mots de passe dans `.env`) |
| Redis | 127.0.0.1:56379 |

## Vérifications

```bash
make check   # lint, typage, tests API et web, contrat d'API (comme la CI)
make e2e     # tests de bout en bout Playwright (desktop + mobile)
make help    # toutes les commandes
```

## Mise en production : points obligatoires

- L'API ne doit **pas** être exposée sur internet : seul le serveur web l'appelle
  (`KORA_API_INTERNAL_URL`). Elle fait confiance à `KORA_TRUSTED_PROXY_COUNT` proxys pour
  l'IP client (limitation de débit, audit).
- `KORA_PUBLIC_URL` doit commencer par `https://` (cookies `Secure`, `upgrade-insecure-requests`).
- Secrets à fournir par l'hébergeur : `KORA_JWT_SECRET` (≥ 64 caractères),
  `KORA_ENCRYPTION_KEYS` (clé(s) Fernet), mots de passe des rôles `kora_owner` / `kora_app`.
- Migrations : exécuter `alembic upgrade head` (rôle `kora_owner`) avant de démarrer l'API.
- Emails (mot de passe oublié, vérification d'adresse, invitations) : SMTP de n'importe
  quel fournisseur (Brevo, Mailgun, Amazon SES, Postmark…), envoyé par le **worker**,
  qui doit donc tourner. Variables : `KORA_SMTP_HOST`, `KORA_SMTP_PORT`,
  `KORA_SMTP_SECURITY` (`starttls` ou `tls` ; `none` refusé en production),
  `KORA_SMTP_USERNAME`, `KORA_SMTP_PASSWORD`, `KORA_EMAIL_FROM` (domaine authentifié
  SPF/DKIM/DMARC chez le fournisseur, sinon les emails finissent en indésirables),
  `KORA_WEB_PUBLIC_URL` (URL https du frontend, pour les liens).
- En local, tous les emails sont capturés par Mailpit : http://localhost:58025.
- Les pièces justificatives sont stockées (chiffrées) dans Garage, serveur S3 local sur
  127.0.0.1:53900. Après une mise à jour du dépôt, `make env` complète `.env` avec les
  nouvelles variables sans toucher aux valeurs existantes.

### Vérifier un stockage S3 de production (Backblaze B2 ou autre)

`make storage-check` vérifie le stockage de la pile locale. Pour tester un bucket de
production depuis ce poste avant le déploiement (le secret est saisi sans écho et
n'apparaît ni à l'écran ni dans l'historique du shell) :

```bash
read -rs KORA_S3_SECRET_ACCESS_KEY && export KORA_S3_SECRET_ACCESS_KEY
docker compose run --rm --no-deps \
  -e KORA_S3_ENDPOINT_URL=https://s3.<région>.backblazeb2.com \
  -e KORA_S3_REGION=<région> \
  -e KORA_S3_BUCKET=<bucket> \
  -e KORA_S3_ACCESS_KEY_ID=<keyID> \
  -e KORA_S3_SECRET_ACCESS_KEY \
  api python -m kora.scripts.check_storage
unset KORA_S3_SECRET_ACCESS_KEY
```

La commande écrit, relit et supprime un objet chiffré, et signale un point d'accès non
https ou une clé qui voit d'autres buckets (code de sortie 0 = tout est bon). Sur B2 :
bucket privé, sans Object Lock, règle de cycle de vie « Keep only the last version »,
clé d'application limitée au bucket.

Documentation projet : `CLAUDE.md` (architecture, règles, décisions, avancement),
`docs/PLAN.md` (phases et critères d'acceptation), `worklog.md` (journal daté).
