# M6c7 — Pas de renouvellement rétroactif

Décision métier du 2026-11-24 (question ouverte en M6c5) : un renouvellement
dont la nouvelle période commencerait avant la date du jour est refusé
(`BusinessRuleError`, 422 une fois exposé en HTTP). Une période source
expirée exige une nouvelle attribution (`assign_license`).

- Date de référence : `utcnow().date()` (Guinée : UTC+0), injectable par le
  paramètre `today` pour des tests déterministes.
- Le jour même de la fin de période (borne exclusive) reste admis.
- Refus après contrôle admin et verrou, avant toute écriture ou audit.

Test : `test_renouvellement_refuse_debut_dans_le_passe`. Les tests existants
fixent `today` pour ne pas dépendre du calendrier réel.

Décision associée : le rôle SQL applicatif partagé avec privilège limité à la
colonne `suspended` est conservé (point 4 de M6c3 tranché, pas de rôle dédié).
Aucune route HTTP, migration, paiement ni droit comptable dans ce lot.
