# M6c6 — Suspension et réactivation des licences par HTTP (API seule)

Première mutation commerciale exposée, après les verrous M6c3/M6c4 et le
correctif M6c5. Seule la suspension/réactivation est ouverte ; le
renouvellement reste interne (question métier ouverte sur les périodes
démarrant dans le passé).

## Route

`PUT /api/v1/platform/module-clients/{client_id}/licenses/{license_id}/suspension`

Corps strict (`extra="forbid"`) : `suspended` et `expected_suspended`
(booléens stricts), `reason` (3 à 500 caractères après suppression des espaces
de bord). Réponse : `{id, suspended, changed}`.

## Points du verrou M6c3 couverts

| Exigence M6c3 | Preuve |
|---|---|
| 401 anonyme, 403 non-admin et admin révoqué | `test_suspension_http_refus_rbac_idor_et_validation` |
| IDOR / inter-dossiers → 404 (licence d'un autre dossier, dossier ou licence inconnus) | idem |
| Validation du corps (types, motif, champs inconnus) sans aucune écriture | idem (état vérifié inchangé) |
| État attendu, conflit 409, no-op idempotent sans audit | `test_suspension_http_transitions_conflit_et_audit` |
| Audit intègre avec motif et acteur, chaîne vérifiée | idem + `test_suspension_reactivation_audit_et_rollback` |
| Motif obligatoire validé aussi dans le service, avant tout accès | `test_suspension_exige_motif_valide_avant_acces` |
| Aucune modification de dates, offre, type, paiement ou droit comptable | idem (dates/type vérifiés) ; privilège SQL limité à la colonne `suspended` |

Le droit administrateur est relu en base à chaque requête (`is_active` et
`is_platform_admin`) : un retrait du droit prend effet sans attendre
l'expiration du jeton.

## Restant à traiter (non couvert par ce lot)

- Point 4 : rôle SQL distinct pour les mutations plateforme (actuellement
  privilège colonne `suspended` du rôle applicatif + contrôle de service).
- Points 5 et 7 : interface d'administration FR/EN avec confirmation explicite
  et recette métier (lot suivant). L'API est appelée par le BFF Next.js avec
  jeton porteur, sans cookie navigateur transmis à l'API.
- Renouvellement HTTP, abonnements et paiements : lots séparés.
