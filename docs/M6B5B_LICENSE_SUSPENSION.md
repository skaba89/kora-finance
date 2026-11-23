# M6b5b — Suspension et réactivation auditées

La migration additive `0032` accorde au rôle `kora_app` un droit
UPDATE **sur la seule colonne `suspended`** des périodes commerciales.
RLS forcée conservée ; pas de modification des dates, offres, tenants ou
suppression des périodes.

Le service exige un administrateur plateforme actif, lie une session
dédiée au dossier, verrouille la période avec `FOR UPDATE`, et impose
une valeur `expected_suspended` pour rejeter les décisions obsolètes.
Une modification et son événement d'audit chaîné sont atomiques.
Aucun commit interne : l'appelant conserve le rollback.

Pas de route HTTP, de paiement, de changement de module ou de rôle métier.

**Point de vigilance sécurité :** la restriction super-admin est assurée
par la couche service. Le droit SQL sur la colonne existe pour le rôle
applicatif partagé : avant une route HTTP, compléter la revue des surfaces
de mutation et les tests HTTP RBAC/IDOR. Envisager une séparation de rôles
SQL dédiée aux opérations plateforme.

Les tests couvrent permissions de colonnes, refus non-admin et cross-tenant,
verrouillage logique, rejets de concurrence, audit, idempotence et rollback.
