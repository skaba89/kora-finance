# M6c5 — Renouvellement : relecture verrouillée et traçabilité

Prérequis sécurité avant toute route HTTP de renouvellement (voir M6c3/M6c4).

## Défaut corrigé

`renew_license` verrouillait la période source (`FOR UPDATE`) sans forcer la
relecture de l'objet ORM. Les sessions utilisant `expire_on_commit=False`, un
objet déjà présent dans la carte d'identité conservait un état `suspended`
obsolète : une période suspendue entre-temps par une autre transaction pouvait
être renouvelée. La requête utilise désormais `populate_existing=True`, comme
`change_license_suspension`.

Test : `test_renouvellement_relit_suspension_concurrente_sous_verrou`
(échec constaté avant correctif, succès après).

## Traçabilité

En plus de `commercial.license_assigned` (inchangé), le service enregistre
dans la même transaction `commercial.license_renewed`, rattaché à la nouvelle
période, avec `previous_license_id`, `starts_on`, `ends_on` et `kind`.

## Hors périmètre

Aucune route HTTP, migration, modification OpenAPI, paiement ou droit métier.
Question métier ouverte : autoriser ou refuser un renouvellement dont la
nouvelle période commence dans le passé (période source expirée).
