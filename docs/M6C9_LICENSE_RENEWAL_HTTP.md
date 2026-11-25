# M6c9 — Renouvellement des licences par HTTP (API seule)

`POST /api/v1/platform/module-clients/{client_id}/licenses/{license_id}/renewals`
→ 201 `{id, starts_on, ends_on, kind}`.

Corps strict : `ends_on` (date civile ISO, horodatage numérique refusé),
`kind` (`trial`/`paid`), `reason` (3 à 500 caractères, journalisé dans
`commercial.license_renewed`, validé aussi par le service avant tout accès).

| Cas | Réponse |
|---|---|
| Anonyme | 401 |
| Non-admin, propriétaire de dossier, admin révoqué | 403 |
| Licence d'un autre dossier, dossier ou licence inconnus | 404 |
| Corps invalide (date, type, motif, champ inconnu dont `starts_on`) | 422, sans écriture |
| Fin non postérieure, période suspendue, début dans le passé | 422 |
| Chevauchement, y compris double envoi | 409 |

Le début est toujours la fin exclusive de la période précédente (non saisi).
L'ancienne période reste inchangée ; aucun paiement ni droit comptable.
Tests : `test_renouvellement_http_*` (dates lointaines : le refus rétroactif
compare à la vraie date du jour) et tests de service mis à jour.
Interface d'administration : lot suivant.
