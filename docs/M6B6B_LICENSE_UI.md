# M6b6b — Consultation des licences depuis l'administration

## Périmètre

- Page `/administration/licences` en lecture seule, accessible uniquement aux administrateurs de plateforme.
- Liste paginée des dossiers clients déjà autorisés par l'API existante.
- Lecture des périodes avec `GET /api/v1/platform/module-clients/{client_id}/licenses`.
- Date de consultation explicite en UTC ; statuts affichés tels que renvoyés/calculés par le serveur.
- Offre, version, type, dates, suspension et états vides affichés sans information financière fictive.
- Entrée de navigation ajoutée à `/administration`.
- Vérification E2E du refus pour un dirigeant non administrateur.

## Hors périmètre

Aucune écriture de licence, aucun changement RBAC/RLS, aucun calcul comptable, aucune migration,
aucune modification de contrat OpenAPI, aucun paiement. Les workflows de renouvellement et de
suspension nécessitent un lot dédié avec tests HTTP et métier.

## Critères de validation avant fusion

1. `make check` et `make contract` passent.
2. `make e2e` vérifie le refus d'un dirigeant ordinaire sur la nouvelle route.
3. Recette manuelle super-administrateur : dossiers paginés, licences présentes/absentes,
   états et dates cohérents avec l'API, fonctionnement FR/EN.
4. Vérification de l'isolation tenant et absence de données fictives.
5. CI GitHub Actions intégralement verte ; fusion interdite tant que ces critères ne sont pas satisfaits.

Note : les statuts dépendent du paramètre `as_of` fixé à la date UTC du rendu.
