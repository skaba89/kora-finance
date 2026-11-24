# M6c4 — Tests négatifs HTTP des mutations commerciales

## Objectif

Compléter le garde-fou structurel M6c3 par de véritables appels HTTP de non-régression, sans ajouter de mutation.

La suite de tests rejoue les méthodes `POST`, `PUT`, `PATCH` et `DELETE` sur le chemin de consultation `/api/v1/platform/module-clients/{client_id}/licenses`. Tant qu'aucune action commerciale n'est publiée, le résultat attendu est `405 Method Not Allowed`.

## Portée et limites

- La PR ne crée aucune route, aucun droit, aucune migration ni modification de montant.
- Le garde-fou structurel de M6c3 reste en place.
- Ces tests ne remplacent pas une revue de sécurité : les services internes de suspension/renouvellement nécessitent toujours tests de droits, isolation IDOR, concurrence, audit et transaction avant exposition.
- Une future route d'écriture devra remplacer ces attentes 405 par des scénarios HTTP RBAC complets explicitement approuvés.

## Validation

Lancer `make api-lint`, `make api-typecheck`, `make api-test`, puis la CI complète, en conservant la PR en brouillon tant que les validations requises ne sont pas satisfaites.
