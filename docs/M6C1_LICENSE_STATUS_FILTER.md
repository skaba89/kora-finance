# M6c1 — Filtrage des périodes de licence

La consultation commerciale existante propose un filtre d'état (programmée, essai, active, suspendue, expirée) sur les périodes du seul dossier sélectionné, en préservant la date UTC de consultation.

## Garanties
- Les périodes et statuts proviennent exclusivement de l'API de lecture existante.
- Le filtre est appliqué aux périodes déjà autorisées et chargées pour un dossier, jamais à l'ensemble des clients.
- Les liens de dossiers et de pagination conservent le filtre.
- Les compteurs indiquent explicitement le périmètre du dossier sélectionné.
- Aucun changement d'API, RLS, permissions, écritures comptables ou migration.

## Recette
- Vérifier un dossier avec plusieurs états à deux dates distinctes.
- Comparer les compteurs et résultats aux périodes renvoyées par l'API à la même date.
- Tester filtre sans résultat, dossier sans licence, changement de page et de dossier.
- Vérifier le contrôle d'accès de la page pour un dirigeant non administrateur.
- Exécuter `make check`, `make contract`, `make e2e`, et la CI complète.
- Valider FR/EN, mobile et une session expirée.

Les opérations de suspension, renouvellement ou paiement ne sont pas introduites dans ce lot.
