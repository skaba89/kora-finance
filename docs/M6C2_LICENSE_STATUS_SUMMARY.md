# M6c2 — Synthèse des états des licences par dossier

La page de lecture seule `/administration/licences` affiche cinq compteurs (programmée, essai, active, suspendue, expirée) à partir des **périodes déjà renvoyées par l'API** pour le dossier autorisé sélectionné et la date civile UTC choisie.

## Garanties
- Les compteurs concernent des **périodes**, et non des entreprises ou des licences commerciales vendues.
- Les valeurs restent calculées côté serveur, avec l'API existante et le même `as_of`.
- Le filtrage de la liste n'altère pas les compteurs de répartition, calculés sur l'ensemble des périodes chargées pour le dossier sélectionné.
- Aucune nouvelle API, mutation, permission, migration ou modification des règles financières.

## Recette
- Dossier sans licences : tous les compteurs sont à zéro.
- Dossier avec plusieurs périodes et états : somme des compteurs = nombre total de périodes retournées par l'API, en supposant les cinq états contractuels.
- Filtre d'état : compteur global inchangé ; liste filtrée uniquement.
- Changement de date : les compteurs reflètent la date sélectionnée.
- Accès interdit aux non-super-admins et isolation multi-tenant inchangés.
- Vérification accessibilité, langue FR/EN, mobile et CI complète.

## Bloquant avant API de suspension
Le document `docs/M6B5B_LICENSE_SUSPENSION.md` demande explicitement une revue des surfaces de mutation et des tests HTTP RBAC/IDOR. Ne pas publier d'endpoint de suspension ou de renouvellement sans ce contrôle.
