# M6b4 — Consultation et état commercial à date

Service plateforme interne de consultation de l'historique des licences par
entreprise. Seul un administrateur plateforme actif peut sélectionner le dossier,
qui reste protégé par la RLS PostgreSQL.

- La date civile `as_of` est fournie explicitement.
- Les statuts `scheduled`, `trial`, `active`, `suspended`, `expired`
  sont calculés avec les règles de `LicensePeriod.status_on`.
- Les résultats sont triés par début de période puis identifiant.
- Aucun paiement, aucune route API publique, aucune mutation, aucun changement
  de RBAC, de configuration des modules ou de migration.
- Appeler avec une session dédiée par dossier, ne pas la réutiliser pour
  des requêtes comptables.

Les tests PostgreSQL vérifient les statuts, l'isolation et le refus d'accès.
Avant fusion : CI complète verte, vérification stricte et non-régression.
