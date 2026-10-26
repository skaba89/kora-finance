# Audit production et VPS — Kora Finance

Date : 26 octobre 2026 — dépôt privé `skaba89/kora-finance`

Référence figée : `7a51c45258301e8cfc50a0305ce023e08d286202` (`main` au début de l'audit). Les constats visent ce commit, pas l'état réel d'un VPS. Aucun accès aux données de production, aucune migration ni aucun déploiement effectués.

## Verdict

La pile VPS existe ; sa capacité, sa configuration effective et sa reprise après perte de serveur ne sont pas validées. Aucun nombre de PME ou d'utilisateurs simultanés ne peut être annoncé avec les seules tailles de VPS. Les autres projets pouvant partager ce VPS doivent être inclus dans la mesure.

## Contrôles du code de déploiement

| Sujet | Constat positif | Limite |
|---|---|---|
| Exposition | En mode Caddy, seuls 80/443 publiés ; PostgreSQL/Redis/API internes | Mode proxy externe à vérifier réellement ; réseau Docker commun non segmenté par service |
| HTTPS | Caddy, compression gzip/zstd, HSTS, corps limité 12 MB | DNS, certificats et proxy réel non inspectés |
| Conteneurs | Images runtime API/web non root, healthchecks API/web/DB/Redis, restart unless-stopped | Pas de healthcheck worker, limites de ressources et digests de release |
| Base | Rôles admin/owner/app distincts, migrations dédiées, volume persistant | Secret owner dans runtime ; pas de réplication/PITR configuré dans la pile |
| Redis | AOF et volume | Un seul nœud ; sauvegarde/reconstruction des files et perte résiduelle non mesurées |
| Backups | pg_dump -Fc, upload chiffré, relecture/hash, rétention 30 jours avec minimum 7 copies, timer quotidien | Pas de test automatique pg_restore sur instance vierge ; pièces/clé hors serveur à valider ; droits de suppression partagés |
| Déploiement | main uniquement, ff-only, contrôle S3 avant compose up | Reconstruction sur serveur, rollback et backup avant migration non imposés |
| Logs | JSON et rotation max-size 10m/max-file 5 | Pas de collecte/alerte indépendante configurée |

## Capacité : dimensionnement à mesurer

Le pool SQLAlchemy autorise 5 connexions permanentes + 10 supplémentaires par processus. Avec un processus API et un worker, cela donne un plafond théorique de pools à prendre en compte, pas une mesure de débit. Chaque processus supplémentaire multiplie ce budget. Le worker est configuré à un processus/quatre threads. Vérifier limites PostgreSQL, threadpool FastAPI et parallélisme des exports ensemble.

Le scénario de recette proposé est : 10/25/50 sessions simultanées, mélange 60 % lecture, 25 % saisie, 10 % pièces et 5 % exports ; 10k puis 100k puis 1M lignes de journal synthétiques réparties entre tenants ; exports longs en parallèle d'une saisie courante. Ces nombres sont des paliers de test, pas une capacité garantie. Mesurer p50/p95/p99, RSS, CPU, IOPS, latence SQL, connexions, backlog et taux d'erreur. Fixer les SLO avec le métier avant de conclure. Tester sur la même offre VPS et le même stockage que la cible.

## Reprise après incident

Objectifs à contractualiser, non garantis aujourd'hui : par exemple RPO inférieur à une heure et RTO inférieur à quatre heures pour un pilote payant, à ajuster au budget et aux attentes. Le dump quotidien seul peut laisser environ une journée de données non sauvegardées, voire davantage après une panne silencieuse. Ajouter sauvegarde continue/WAL si le RPO retenu l'exige.

Runbook à démontrer sur infrastructure isolée : panne processus → redémarrage/alerte ; panne Redis → traitement des requêtes et reprise des files ; perte PostgreSQL → restauration et contrôle des chaînes ; perte VPS → nouveau serveur + clés hors site + base + objets + release ; panne fournisseur S3 → mode dégradé explicite et reprise ; compromission → rotation des clés/identifiants, révocation des sessions et preuve de préservation des sauvegardes. Aucun de ces exercices n'a été exécuté sur la production.

## Anomalies

### KF-02 — Le secret du propriétaire de schéma est transmis aux services applicatifs

- **Priorité / gravité :** P0 / Élevée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`deploy/vps/compose.yml:17`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/deploy/vps/compose.yml#L17).
- **Preuve technique :** x-api-env contient KORA_DATABASE_MIGRATION_URL avec le compte kora_owner ; migrate, api et worker réutilisent cet environnement aux lignes 80, 89 et 104. Settings exige aussi ce paramètre pour tout processus.
- **Impact :** Une compromission de l'API ou du worker donne accès aux identifiants permettant de modifier le schéma et ses protections. Le rôle utilisé normalement reste kora_app : aucune fuite inter-tenant HTTP démontrée.
- **Solution :** Séparer environnement runtime et migration ; retirer l'URL owner de l'API/worker ; configuration Alembic distincte, requise seulement lors des migrations. Conserver les secrets de sauvegarde hors runtime si possible.
- **Test de validation :** Analyser compose config sans publier les valeurs ; vérifier que seuls migrate et l'outil autorisé reçoivent le secret owner ; démarrer API/worker sans celui-ci et vérifier leurs tests et migrations.

### KF-09 — Sauvegardes et pièces partagent les droits de suppression

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/scripts/backup.py:58`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/scripts/backup.py#L58).
- **Preuve technique :** Les sauvegardes utilisent objects._client et le même bucket/compte que les pièces ; prune supprime les anciens objets. deploy/vps/compose.yml transmet ces identifiants à API et worker. Aucun stockage WORM ou réplication indépendante configuré dans le dépôt.
- **Impact :** Le chiffrement protège la confidentialité mais pas la suppression malveillante par une application compromise. Le paramétrage réel du fournisseur reste inconnu.
- **Solution :** Compte et bucket de sauvegarde séparés, protection de rétention/versions administrée hors application, copie indépendante des pièces et clés séquestrées hors VPS.
- **Test de validation :** Sous identifiants API, tenter la suppression d'une sauvegarde protégée : refus. Restaurer base, pièces et clés depuis les seules copies hors serveur dans un environnement isolé.

### KF-10 — La reprise complète après perte du VPS n'est pas démontrée

- **Priorité / gravité :** P0 / Élevée.
- **Statut de preuve :** Preuve opérationnelle manquante.
- **Fichier :** [`deploy/vps/restore.sh:25`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/deploy/vps/restore.sh#L25).
- **Preuve technique :** restore.sh restaure PostgreSQL ; test_backup.py vérifie les objets chiffrés, pas un cycle pg_dump/pg_restore sur une nouvelle instance ni la récupération des pièces et des clés. La CI ne lance pas de restauration complète. Aucun accès au VPS réel n'a été utilisé.
- **Impact :** On ne peut pas garantir un RTO/RPO ni l'accès aux justificatifs après sinistre. C'est un blocage de validation production, pas la preuve que les sauvegardes actuelles sont inutilisables.
- **Solution :** Ajouter un exercice automatisé de restauration sur serveur vierge, base + S3 + clés + version du code ; mesurer la durée ; tester une clé secondaire et un backup ancien.
- **Test de validation :** Détruire uniquement une pile éphémère, reconstruire, restaurer, vérifier migrations, RLS, chaînes d'audit, comptages et hash de plusieurs pièces ; consigner RPO/RTO et date.

### KF-11 — Déploiement non versionné et sans sauvegarde préalable imposée

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`deploy/vps/deploy.sh:22`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/deploy/vps/deploy.sh#L22).
- **Preuve technique :** Le script avance main, reconstruit puis lance compose up et les migrations. Pas de sauvegarde pré-migration imposée, pas de rollback d'image par digest, pas de contrôle de checkout propre ni de procédure automatique de retour. Plusieurs images sont référencées par tags mobiles.
- **Impact :** Une erreur de migration ou de build peut prolonger une indisponibilité ; reproduire exactement une version dépend des registres au moment de la reconstruction.
- **Solution :** Release identifiée par SHA et digest, validation CI préalable, backup vérifié avant migration, schéma expand/contract, arrêt contrôlé si nécessaire et procédure de rollback documentée.
- **Test de validation :** Sur staging, simuler migration refusée, build indisponible et healthcheck échoué ; démontrer le retour à une version connue sans perte de données.

### KF-12 — Supervision limitée aux healthchecks et logs locaux

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Absence dans le dépôt ; configuration VPS non vérifiée.
- **Fichier :** [`apps/api/src/kora/api/health.py:47`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/api/health.py#L47).
- **Preuve technique :** ready teste seulement SELECT 1 et Redis ping. Pas de configuration de métriques, alertes externes, dead letters, succès de backup, expiration TLS, saturation disque ou contrôles périodiques d'intégrité dans le dépôt.
- **Impact :** Le processus peut rester vivant pendant une défaillance métier ou une sauvegarde en échec ; rotation locale des logs ne remplace pas l'alerte.
- **Solution :** Sondes externes et métriques API/PostgreSQL/Redis/worker/stockage ; alertes orientées actions, traces corrélées, contrôle périodique sauvegarde et audit. Conserver ready léger et ajouter des contrôles métier séparés.
- **Test de validation :** Injecter panne worker, disque presque plein, erreur S3 et backup en échec sur staging ; vérifier la réception d'une alerte et la procédure associée.

### KF-13 — Exports et stockage sans budget global de ressources

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/exports/service.py:65`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/exports/service.py#L65).
- **Preuve technique :** Les exports construisent le Document complet avant le seuil MAX_PDF_ROWS ; Excel n'a pas de plafond équivalent. full_ledger matérialise toutes les lignes. Le nombre de pièces est limité par écriture, sans quota total par société. compose.yml ne fixe pas de limites CPU/RAM.
- **Impact :** Un tenant très actif peut épuiser mémoire, connexions ou stockage et dégrader tous les clients du VPS. Aucune capacité chiffrée n'a été mesurée.
- **Solution :** Limiter avant lecture, exporter en streaming ou worker avec quotas, plafonner nombre d'exports concurrents et stockage par tenant, fixer les budgets conteneurs et préserver PostgreSQL.
- **Test de validation :** Charge multi-tenant avec grands livres de 10k/100k/1M lignes synthétiques et exports concurrents ; mesurer RSS, p95/p99, files, erreurs, équité entre tenants et arrêt contrôlé.

### KF-20 — Les audits de dépendances ne sont pas dans la CI

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`.github/workflows/ci.yml:1`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/.github/workflows/ci.yml#L1).
- **Preuve technique :** La CI couvre gitleaks, lint, typage, tests, build et contrat. Aucun job pip-audit/npm audit/SBOM/scan d'image ni politique de mise à jour automatisée n'est défini. Audits locaux exécutés : zéro vulnérabilité connue dans les bases consultées.
- **Impact :** Une vulnérabilité publiée après ce contrôle ne bloque pas les futures releases. Les tags Docker non figés compliquent aussi la traçabilité.
- **Solution :** SCA Python/JS, SBOM et scan d'images sur release ; politique d'exceptions avec expiration et seuils définis ; pinning des images de production par digest.
- **Test de validation :** Dans une branche de test, injecter une dépendance de démonstration vulnérable : la CI doit échouer avec un diagnostic et une procédure d'exception traçable.

### KF-22 — Mise en file après commit sans outbox durable

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/worker/tasks.py:48`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/worker/tasks.py#L48).
- **Preuve technique :** _prepare_and_deliver prépare et commit le jeton via le service puis appelle deliver_email.send. enqueue_best_effort peut perdre une notification ; purge peut finir avec un objet orphelin si S3 et Redis sont indisponibles. Ces cas sont journalisés mais sans réconciliation durable identifiée.
- **Impact :** Emails ou purges perdus à la frontière DB/Redis ; réessais possibles mais l'utilisateur ou l'exploitation doit parfois intervenir.
- **Solution :** Outbox transactionnelle et worker idempotent, suivi des dead letters, réconciliation périodique des objets orphelins avec délai de sécurité.
- **Test de validation :** Arrêter Redis entre commit et enqueue puis redémarrer ; retrouver la tâche et livrer/purger une seule fois sans invalider un lien utile.

### KF-23 — Sauvegarde chargée intégralement avant contrôle de taille

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/scripts/backup.py:50`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/scripts/backup.py#L50).
- **Preuve technique :** upload fait path.read_bytes avant de vérifier MAX_BYTES=2 GiB ; chiffrement, empaquetage et relecture gardent plusieurs buffers. backup.sh conserve aussi des dumps locaux non chiffrés dans un répertoire 700 ; aucune politique de chiffrement disque vérifiable dans le dépôt.
- **Impact :** La sauvegarde elle-même peut provoquer un OOM sur petit VPS ; confidentialité locale dépend du serveur et de ses accès administrateur.
- **Solution :** Contrôle stat avant lecture, limite adaptée à la RAM et transfert/chiffrement par blocs ; espace de travail chiffré, umask strict, nettoyage sûr y compris sur échec.
- **Test de validation :** Backup synthétique dépassant le seuil refusé sans lire le contenu ; mesurer RSS en upload/download et tester l'échec de transfert sans résidu accessible.


## Conditions de passage en production

P0 fermés avec preuves ; environnement staging distinct ; configuration runtime sans secrets owner ; toutes les vérifications CI vertes sur la release ; test de restauration complet et clés hors VPS ; supervision réellement alertante ; charge validée sur cible ; SMTP délivrable ou parcours alternatifs clairement bornés ; validation expert-comptable et périmètre commercial explicite ; procédure de support et retour arrière répétée. Le dépôt ne prouve pas que ces conditions sont déjà remplies.
