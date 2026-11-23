# M6b5c — Renouvellement commercial persisté

Le service interne `renew_license` utilise la période réellement stockée,
vérifie l'administrateur plateforme et le dossier, puis verrouille
la période source (`FOR UPDATE`). Il réutilise la validation pure
`preview_renewal` et l'insertion auditée `assign_license`.

La base garantit qu'aucune période ne chevauche une autre, y compris en cas
de concurrence. Une suspension préalable interdit la préparation de ce
renouvellement. Le service conserve l'ancienne période et ne fait aucun
`commit` ; rollback métier et audit restent atomiques.

Aucun paiement, droit d'accès comptable, module, tarif ou rôle n'est modifié.
Pas de route HTTP ni de changement OpenAPI dans ce lot. L'API et les
permissions de transport seront traitées dans M6b6 après revue RBAC/IDOR.
