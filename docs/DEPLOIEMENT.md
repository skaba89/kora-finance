# Déploiement de Kora Finance sur un VPS

Un serveur dédié à Kora, une pile Docker Compose (`deploy/vps/compose.yml`) :

```
internet ──443──▶ Caddy (HTTPS automatique) ──▶ web (Next.js) ──▶ api (FastAPI) ──▶ PostgreSQL
                                                                   │                  Redis ◀── worker
                                                                   └──▶ Backblaze B2 (pièces, sauvegardes)
```

Seul Caddy est joignable depuis internet (ports 80/443). PostgreSQL, Redis, l'API et le
worker ne publient aucun port. L'API refuse de démarrer en production sans HTTPS
(`KORA_WEB_PUBLIC_URL`, stockage S3) et sans SMTP chiffré lorsque les emails sont actifs.

## 1. Prérequis

| Élément | Choix | Remarque |
|---|---|---|
| Serveur | VPS OVH, Ubuntu 24.04, 2 vCPU / 4 Go / 40 Go | Dédié à Kora : pas d'autre application, pas d'environnement de développement |
| Adresse | Nom de domaine **ou** `<ip-avec-tirets>.sslip.io` | sslip.io : nom gratuit qui pointe vers l'IP (ex. `51-75-1-2.sslip.io`), suffisant pour un certificat HTTPS ; à remplacer par un vrai domaine avant d'accueillir des clients |
| Stockage | Bucket Backblaze B2 **privé**, sans Object Lock, cycle de vie « Keep only the last version » | Clé d'application **limitée au bucket** (Read and Write), jamais la clé principale |
| Emails | `KORA_EMAIL_BACKEND=disabled` au départ | Ni mot de passe oublié ni invitation par email tant qu'un fournisseur SMTP n'est pas configuré (l'interface le signale) |

## 2. Préparer le serveur (une fois)

Depuis votre ordinateur : `ssh ubuntu@IP_DU_SERVEUR`, puis sur le serveur :

```bash
git clone https://github.com/skaba89/kora-finance.git ~/kora-finance
sudo ~/kora-finance/deploy/vps/bootstrap-server.sh
exit   # se reconnecter pour appartenir au groupe docker
```

Le dépôt étant privé, `git clone` demande un identifiant GitHub et un **jeton d'accès**
(GitHub → Settings → Developer settings → Fine-grained tokens : accès en lecture seule au
seul dépôt `kora-finance`, « Contents: Read-only »). Pour ne pas le ressaisir :
`git config --global credential.helper store` (jeton stocké en clair dans
`~/.git-credentials`, lisible seulement par vous).

`bootstrap-server.sh` : mises à jour, Docker (dépôt officiel), pare-feu (SSH, 80, 443),
mises à jour de sécurité automatiques, fail2ban, fichier d'échange de 2 Go, connexion
SSH par clé uniquement si une clé est installée.

## 3. Installer Kora

```bash
cd ~/kora-finance/deploy/vps
./init-env.sh          # crée .env avec des secrets aléatoires, liste ce qui manque
nano .env              # KORA_DOMAIN, KORA_ACME_EMAIL, KORA_S3_*
./init-env.sh          # « .env est complet »
./deploy.sh            # construit, vérifie le stockage, migre, démarre
./install-backup-timer.sh
```

**Avant toute chose, copiez dans votre gestionnaire de mots de passe** les valeurs de
`.env` marquées (*) — en particulier `KORA_ENCRYPTION_KEYS` : sans elle, les pièces
justificatives et les sauvegardes sont définitivement illisibles, même par vous.

`deploy.sh` s'arrête si la vérification du stockage échoue ou signale un problème (clé
qui voit d'autres buckets, point d'accès non https). Ensuite, ouvrez `https://KORA_DOMAIN`
et créez votre compte.

## 3 bis. Serveur partagé : derrière le proxy commun

Sur un serveur qui héberge plusieurs applications (installation actuelle : 51.75.248.4),
les ports 80/443 appartiennent à un **proxy commun** indépendant des applications : le
projet `~/vps-proxy` (Caddy, hors de ce dépôt). Kora ne lance pas son propre Caddy et ne
dépend d'aucune autre application : son web rejoint le réseau Docker externe `edge` sous
l'alias `kora-web`, et le proxy le publie sous un nom à lui
(`kora.51-75-248-4.sslip.io`). Aucun port supplémentaire n'est ouvert.

1. Production dans un clone dédié, toujours sur `main` (jamais le répertoire de dev) :
   `git clone https://github.com/skaba89/kora-finance.git ~/kora-production`.
2. Dans `deploy/vps/.env` : commenter `COMPOSE_PROFILES=caddy`, décommenter
   `COMPOSE_FILE=compose.yml:compose.proxy-externe.yml`, `KORA_ACME_EMAIL=-`.
3. `./deploy.sh` (crée le réseau `edge` s'il n'existe pas encore) ; le web y est joignable
   sous le nom `kora-web`, sans port publié.
4. Côté proxy commun : le site est décrit dans `~/vps-proxy/sites/kora.caddy` (bloc
   indiqué en tête de `compose.proxy-externe.yml`) ; après modification,
   `~/vps-proxy/reload.sh` (validation puis rechargement sans coupure).

Le projet Compose de production s'appelle `kora` ; celui de développement
`kora-finance` : ne jamais lancer de tests ni `docker compose down -v` sur `kora`.

## 4. Mettre à jour

Après la fusion d'une pull request sur `main` (CI verte) :

```bash
~/kora-finance/deploy/vps/deploy.sh   # ~/kora-production/... sur un serveur partagé
```

Les migrations s'appliquent automatiquement (service `migrate`) avant le redémarrage de
l'API ; les données (volumes Docker) ne sont jamais supprimées. Faire une sauvegarde
manuelle avant une mise à jour importante : `./backup.sh`.

## 5. Sauvegardes et restauration

- Chaque nuit (02:30 UTC) : `pg_dump`, chiffrement (AES-256-GCM, clés `KORA_ENCRYPTION_KEYS`),
  envoi dans le bucket sous `backups/`, relecture et vérification, purge au-delà de
  30 jours (les 7 plus récentes sont toujours gardées). Copie locale 7 jours dans
  `deploy/vps/backups/`.
- Suivi : `journalctl -u kora-backup.service`, liste : `./restore.sh`.
- Restaurer (remplace toutes les données, confirmation demandée) :
  `./restore.sh backups/kora-AAAAMMJJTHHMMSSZ.dump.enc`.
- **Tester une restauration** au moins une fois par trimestre (procédure vérifiée en
  développement : données, déclencheurs et RLS identiques après restauration).

Limites connues : les sauvegardes sont dans le même bucket que les pièces, avec la même
clé (une clé B2 ne couvre qu'un bucket) ; un bucket séparé avec Object Lock protégerait
contre une suppression malveillante. Les pièces justificatives elles-mêmes reposent sur
la durabilité de B2 (pas de seconde copie).

## 6. Activer les emails (plus tard)

Dans `.env` : `KORA_EMAIL_BACKEND=smtp`, `KORA_EMAIL_FROM`, `KORA_SMTP_HOST`,
`KORA_SMTP_PORT`, `KORA_SMTP_SECURITY` (`starttls` ou `tls`), `KORA_SMTP_USERNAME`,
`KORA_SMTP_PASSWORD`, puis `./deploy.sh --sans-git`. Déclarer SPF, DKIM et DMARC du
domaine d'envoi chez le fournisseur.

## 7. Passer à un vrai nom de domaine

Créer un enregistrement DNS `A` vers l'IP du serveur, modifier `KORA_DOMAIN` dans `.env`,
puis `./deploy.sh --sans-git` : Caddy obtient le nouveau certificat. Les sessions en
cours sont perdues (cookies liés à l'ancien nom).

## Dépannage

```bash
cd ~/kora-finance/deploy/vps
docker compose ps                          # état des services
docker compose logs --tail=100 api caddy   # journaux
docker compose run --rm --no-deps api python -m kora.scripts.check_storage
```
