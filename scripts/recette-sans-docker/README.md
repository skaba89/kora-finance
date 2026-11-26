# Recette locale sans Docker

Pile de validation locale légère pour kora-finance, sans Docker ni services
externes, destinée aux recettes fonctionnelles sur un poste de développement
ou dans un bac à sable d'exécution restreint.

| Service | Implémentation | Port |
|---|---|---|
| PostgreSQL | [`pgserver`](https://pypi.org/project/pgserver/) (binaire embarqué, répertoire de données dédié) | 54330 |
| Redis | `fakeredis` (serveur TCP) | 63790 |
| S3 | `moto_server` | 9000 |
| Emails | backend API `disabled` | — |

Les ports décalés évitent toute collision avec des instances de développement
locales (5432/6379/9000) : la recette ne doit jamais toucher à une base réelle.

## Démarrage

```bash
scripts/recette-sans-docker/recette-stack.sh   # PG + Redis + S3 + rôles + buckets
scripts/recette-sans-docker/recette-env.sh     # .env API (secrets générés) + .env.local web
uv sync --directory apps/api                   # dépendances API
scripts/recette-sans-docker/recette-up.sh      # API :8100 + web :3000 + health check
```

Répertoire de travail par défaut : `../.recette` (hors dépôt), paramétrable via
`RECETTE_DIR`. Idempotent : réexécutable, seuls les éléments manquants sont créés.

## Garanties reprises de la pile de test CI

- Rôles PostgreSQL séparés : `kora_owner` (migrations, propriétaire des objets)
  et `kora_app` (runtime sans `BYPASSRLS`, sans droits de propriétaire) —
  même modèle que `tests/test_db_roles.py` et le `restore-drill`.
- Extension `btree_gist` installée (contraintes d'exclusion : verrous d'exercice,
  lettrage) ; le script la recherche dans le paquet `pgserver` et la replace si
  la disposition du paquet est incorrecte.
- Buckets S3 séparés `kora-test` (pièces) et `kora-backups` (sauvegardes),
  conformément à l'isolation exigée par `tests/test_backup.py`.
- Secrets générés localement (`openssl rand`, Fernet) ; `recette-api.env` en
  `0600`, jamais versionné.

## Limites connues

- Ce n'est pas un environnement de production : `fakeredis` ne reproduit pas la
  persistance Redis, `moto` ne reproduit pas les quotas/versions S3 réels.
- Les emails sont désactivés ; les parcours d'invitation doivent être validés
  avec le backend SMTP réel en REC.
- Après un redémarrage de la machine, si `pgdata` a été copié, réexécuter
  `recette-stack.sh` : les répertoires runtime de PostgreSQL sont recréés.
