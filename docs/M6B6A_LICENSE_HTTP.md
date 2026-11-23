# M6b6a — Lecture HTTP des licences commerciales

Route de lecture seule `GET /api/v1/platform/module-clients/{client_id}/licenses`.
L'administrateur plateforme actif est vérifié avant le contexte tenant.
Le paramètre `as_of` (date ISO obligatoire) détermine les statuts :
scheduled, trial, active, suspended ou expired.

Aucun détail financier, tarif, changement de droits ou mutation de licence.
L'isolation RLS et le service existant `list_license_periods` sont réutilisés.
Les tests vérifient 401, 403, 422, isolation entre entreprises et les statuts.
Contrat OpenAPI et types TypeScript sont régénérés dans le même lot.
Les routes d'écriture suivront après validation de cette lecture.
