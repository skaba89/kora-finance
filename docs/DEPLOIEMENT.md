# Déploiement de Kora Finance sur un VPS

Un serveur dédié à Kora, une pile Docker Compose (`deploy/vps/compose.yml`) :

```
internet ──443──▶ Caddy (HTTPS automatique) ──▶ web (Next.js) ──▶ api (FastAPI) ──▶ PostgreSQL
                                                                   │                  Redis ◀── worker
                                                                   │        (pièces) ──▶ Backblaze B2 — bucket A
            api/worker : sans accès aux sauvegardes (KF-09)        └─(backup)──▶ Backblaze B2 — bucket B dédié
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
nano .env              # KORA_DOMAIN, KORA_ACME_EMAIL, KORA_S3_*, KORA_BACKUP_S3_*
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

Chaque déploiement est une **release identifiée** (KF-11) :

1. **Pré-vols** — `.env` complet, branche `main`, **copie git propre** (aucune
   modification suivie non commitée), avance `--ff-only` sur `origin/main`. La
   vérification du SHA local contre le SHA distant réel de `origin/main`,
   également avec `--sans-git`. Une divergence ou l'impossibilité de joindre
   GitHub bloque la publication. **Attention :** cette égalité de SHA ne prouve
   pas à elle seule la réussite de la CI. La protection de `main` par une règle
   GitHub imposant le statut `CI / Résultat` et la revue des PR est indispensable,
   et doit être configurée par un administrateur du dépôt.
2. **Release** — les images sont construites et étiquetées par le SHA court du commit
   (`kora-api:<sha>`, `kora-web:<sha>`, variable `KORA_IMAGE_TAG`) : l'alias `:prod`
   n'est plus écrasé avant la bascule, la pile en place continue de tourner sur ses
   images. Le stockage S3 est vérifié avec la nouvelle version (check_storage).
3. **Sauvegarde pré-migration vérifiée, imposée** — `backup.sh` est exécuté avec
   l'image en cours : dump relu et déchiffré avant d'aller plus loin ; s'il échoue, le
   déploiement s'arrête. (Première installation, postgres absent : passée avec
   avertissement explicite, il n'existe encore aucune donnée.)
4. **Bascule** — migrations (service `migrate`) puis `up -d --wait` (healthchecks).
   En cas d'échec (migration refusée, healthcheck), **retour automatique** à la
   version précédente connue.
5. **Consignation** — `releases.log` (date, SHA, IDs des images) et `.release` /
   `.previous-release` (état local au serveur, ignorés par git). Les cinq dernières
   releases restent présentes localement pour le retour arrière.

**Retour arrière manuel** : `./rollback.sh` redémarre la pile sur la version
précédente (images immuables déjà présentes, volumes intacts). Refus s'il n'existe
aucune version antérieure connue ou si ses images ont été retirées.

**Convention expand/contract** : le schéma n'est jamais migré en arrière. Toute
migration doit donc être écrite en deux temps (ajouter la nouvelle structure et la
remplir sans casser l'ancienne version — *expand* ; supprimer l'ancienne après la
mise en production de la version qui n'utilise plus que la nouvelle — *contract*).
Un rollback vers la version immédiatement précédente est ainsi toujours sûr : les
colonnes ajoutées restent présentes et sans effet sur l'ancien code.

## 5. Sauvegardes et restauration

- Chaque nuit (02:30 UTC) : `pg_dump`, chiffrement (AES-256-GCM, clés `KORA_ENCRYPTION_KEYS`),
  envoi dans le bucket **dédié** aux sauvegardes, relecture et vérification. Copie locale
  7 jours dans `deploy/vps/backups/`.
- **Isolation (KF-09)** : les identifiants de sauvegarde (`KORA_BACKUP_S3_*`) ne sont
  transmis qu'au service `backup` — jamais à l'API, au worker ni au web. La clé de
  sauvegarde ne porte **aucun droit de suppression** (B2 : capabilities sans deleteFiles ;
  S3 : politique refusant DeleteObject) : une application compromise peut détruire les
  pièces, pas les sauvegardes.
- **Rétention** : administrée côté fournisseur (cycle de vie du bucket, ~30 jours). La
  purge manuelle `python -m kora.scripts.backup prune --keep-days 30` exige la clé
  d'administration **distincte** `KORA_BACKUP_ADMIN_S3_*`, conservée hors du serveur
  (elle garde toujours les 7 plus récentes ; sans elle, la purge est refusée).
- Suivi : `journalctl -u kora-backup.service`, liste : `./restore.sh`.
- Restaurer (remplace toutes les données, confirmation demandée) :
  `./restore.sh backups/kora-AAAAMMJJTHHMMSSZ.dump.enc`.
- **Tester une restauration** au moins une fois par trimestre (procédure vérifiée en
  développement : données, déclencheurs et RLS identiques après restauration).

Prérequis fournisseur : créer un second bucket privé dédié aux sauvegardes et une clé
limitée à ce bucket, en lecture/écriture **sans suppression** ; régler son cycle de vie
(rétention) côté fournisseur ; séquestrer la clé d'administration hors du serveur. Les
pièces justificatives elles-mêmes reposent sur la durabilité de B2 (pas de seconde copie).

## 5 bis. Supervision (KF-12)

Quatre unités systemd supervisent l'exploitation ; elles s'installent d'un geste avec
`./install-backup-timer.sh` (remplace l'ancienne installation à deux fichiers).

| Unité | Rythme | Rôle | En cas d'échec |
|---|---|---|---|
| `kora-backup.service` (+ `.timer`) | quotidienne 02:30 UTC | sauvegarde chiffrée | `OnFailure=` → alerte |
| `kora-freshness.service` (+ `.timer`) | quotidienne 03:45 UTC | la dernière sauvegarde doit dater de moins de 26 h (`backup status`) | `OnFailure=` → alerte |
| `kora-probe.service` (+ `.timer`) | toutes les 5 min | sonde externe `https://<domaine>/health/ready` (HTTPS → Caddy → API → PostgreSQL/Redis, certificat TLS inclus) | 2 échecs consécutifs → alerte |
| `kora-alert@.service` | à la demande (instanciée par `OnFailure=`) | trace locale + email d'exploitation | — |

- **Alertes** : `alert.sh` écrit toujours une trace horodatée
  (`deploy/vps/backups/alertes/journal.log`), puis envoie un email au destinataire
  `KORA_ALERT_EMAIL` (à renseigner dans `.env`) via le conteneur `backup`
  (`python -m kora.scripts.notify`). Anti-tempête : au plus un email par unité
  défaillante et par 4 h. Sans `KORA_ALERT_EMAIL` ou avec `KORA_EMAIL_BACKEND=disabled`,
  l'alerte n'est pas prétendue envoyée : elle reste tracée et visible dans
  `journalctl -u kora-alert`.
- **Sondes publiques** : le Caddyfile expose uniquement `handle /health/*` vers l'API
  (statut `ok|erreur` des dépendances, aucune donnée métier). C'est le seul chemin d'API
  joignable depuis internet, et il sert à la sonde : une coupure applicative, une base
  indisponible ou un certificat TLS expiré déclenchent une alerte en 10 minutes maximum.
- Vérification manuelle : `systemctl list-timers 'kora-*' --no-pager` ; forcer un essai :
  `sudo systemctl start kora-freshness.service kora-probe.service` ; journal :
  `journalctl -u kora-freshness -u kora-probe -u kora-alert`.

## 6. Activer les emails (plus tard)

Dans `.env` : `KORA_EMAIL_BACKEND=smtp`, `KORA_EMAIL_FROM`, `KORA_SMTP_HOST`,
`KORA_SMTP_PORT`, `KORA_SMTP_SECURITY` (`starttls` ou `tls`), `KORA_SMTP_USERNAME`,
`KORA_SMTP_PASSWORD`, puis `./deploy.sh --sans-git`. Déclarer SPF, DKIM et DMARC du
domaine d'envoi chez le fournisseur.

## 6 bis. Exiger la double authentification des administrateurs plateforme

Les administrateurs plateforme peuvent suspendre et renouveler des licences
commerciales. Pour leur imposer la double authentification (2FA) :

1. Vérifier que chaque administrateur plateforme l'a activée (Sécurité du compte),
   sans quoi il perdra l'accès à l'administration :
   `SELECT email FROM users WHERE is_platform_admin AND is_active AND totp_enabled_at IS NULL;`
   doit ne renvoyer aucune ligne.
2. Ajouter `KORA_PLATFORM_ADMIN_REQUIRE_MFA=true` dans `deploy/vps/.env`, puis redéployer.

**Garde P0 :** pour toute mise à jour d'une installation possédant déjà
`deploy/vps/.release`, `deploy.sh` bloque si cette variable n'est pas
explicitement égale à `true`. Pour la première installation uniquement,
l'administrateur peut créer son compte et enrôler le TOTP avant la première mise
à jour. Ne jamais supprimer `.release` pour contourner le contrôle : consulter
les logs de déploiement et vérifier les comptes administrateurs en base.

Le droit est relu en base à chaque requête : la désactivation de la 2FA retire
aussitôt l'accès plateforme. Les droits dans les dossiers ne sont pas concernés.

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
./rollback.sh                              # revenir à la version précédente (KF-11)
cut -f2 releases.log                       # versions déployées (la plus récente en bas)
```

## Séparation des identifiants PostgreSQL (KF-02)

L'API et le worker reçoivent uniquement `KORA_DATABASE_URL` (rôle `kora_app`).
Ils ne reçoivent ni URL de migration, ni mot de passe propriétaire/administrateur.
Le service ponctuel `migrate` reçoit uniquement `KORA_DATABASE_MIGRATION_URL`
(rôle `kora_owner`) ; Alembic utilise une configuration indépendante.
Les outils de test gardent les deux connexions pour contrôler migrations et RLS.
La CI vérifie les environnements Compose résolus, y compris le mode proxy commun,
avec des valeurs synthétiques et sans afficher les secrets.

Après validation et déploiement autorisé, recréer les conteneurs API et worker
pour retirer l'ancienne variable de leurs environnements. Une simple modification
du fichier Compose ne retire pas les secrets des conteneurs déjà démarrés.
Si l'ancienne exposition a pu être exploitée, prévoir une rotation séparée des
identifiants privilégiés ; ce correctif ne modifie aucun mot de passe existant.
