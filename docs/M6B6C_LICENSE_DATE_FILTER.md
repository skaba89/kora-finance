# M6b6c — Consultation des licences à date choisie

La page `/administration/licences` permet au super-administrateur de choisir une date civile UTC via un formulaire GET. La date est passée au paramètre `as_of` de l'API de lecture existante. Les sélections de dossier et la pagination conservent cette date.

## Garde-fous

- Validation d'un format `YYYY-MM-DD` et d'une date civile réelle.
- Repli explicite sur la date UTC du jour si une valeur de requête est invalide.
- Les statuts continuent d'être calculés exclusivement par l'API.
- Aucune écriture de licence, mutation comptable, migration, permission ni contrat modifié.

## Recette avant fusion

1. CI complète et typage Next.js réussis.
2. Un super-administrateur choisit une date historique et une date future ; comparer les statuts à l'API.
3. Vérifier le maintien de la date en changeant de dossier et de page.
4. Vérifier la notification pour `?as_of=2026-02-30` et `?as_of=invalid`.
5. Refus d'accès à un utilisateur ordinaire sur `/administration/licences` inchangé.
6. Vérifier les affichages FR/EN et mobile.
