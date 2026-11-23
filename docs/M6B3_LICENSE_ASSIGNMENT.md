# M6b3 — Attribution des périodes commerciales

La migration additive 0031 accorde uniquement INSERT à kora_app sur
commercial_license_periods (RLS déjà forcée en 0029). Le service interne
assign_license exige un administrateur plateforme actif, vérifie le dossier,
la version d'offre publiée et ses modules, puis lie le contexte RLS. L'ajout
et l'événement d'audit tenant sont dans la transaction de l'appelant ;
les chevauchements sont rejetés par une exclusion GiST en base.

Aucune route HTTP, aucune grille tarifaire, aucun paiement, aucune mutation
de configuration des modules ou des droits RBAC. Une nouvelle période adjacente
permet le renouvellement, sans modification de l'ancienne. Les statuts
commerciaux sont calculés à date explicite.

À valider avant fusion : migrations aller-retour, tests PostgreSQL, ruff,
mypy, CI complète, isolation et vérification des permissions runtime.
