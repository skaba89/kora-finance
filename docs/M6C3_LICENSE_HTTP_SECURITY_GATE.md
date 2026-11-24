# M6c3 — Verrou de sécurité avant exposition HTTP des mutations commerciales

## Constat vérifié sur main (2026-11-24)

- `apps/api/src/kora/api/v1/modules.py` n'expose qu'un GET de consultation des périodes commerciales sous `/platform/module-clients/{client_id}/licenses`.
- `license_suspension.change_license_suspension` effectue un verrou `FOR UPDATE`, exige `expected_suspended`, vérifie l'administration plateforme et journalise atomiquement le changement.
- `license_renewal_assignment.renew_license` conserve la période précédente et s'appuie sur `assign_license` pour la création auditée, avec contrainte PostgreSQL anti-chevauchement.
- Le rôle SQL applicatif partagé dispose d'un privilège UPDATE limité à `suspended` ; l'autorisation de plateforme dépend du contrôle de service. Une revue de surface est nécessaire.

## Verrou introduit

Le test `test_aucune_mutation_http_licence_exposee_sans_revue_securite` exige que la seule route `/platform/module-clients/.../licenses` soit le GET existant. Toute nouvelle route commerciale de mutation impose ainsi une modification explicite de ce test, à accompagner d'une revue et de preuves d'autorisation.

## Travaux obligatoires avant ouverture HTTP

1. Documenter et tester le refus des utilisateurs anonymes (401), non-admin (403), admin désactivé (403), cross-tenant et IDOR (404).
2. Tester les validations de payload, transitions d'état, conflit concurrent, vérification de l'état attendu, idempotence, transactions annulées et événement d'audit intègre.
3. Séparer les sessions de contexte plateforme / tenant, avec transaction dédiée par opération et revalidation de privilèges.
4. Réviser le droit UPDATE du rôle SQL partagé : envisager rôle séparé ou procédure privilégiée à périmètre contrôlé selon architecture.
5. Exiger une intention explicite, motif d'audit et confirmation côté UI pour toute suspension/réactivation.
6. Préserver les permissions comptables, les montants, les périodes existantes et le caractère distinct de tout paiement.
7. Ajouter tests HTTP intégrés et protections anti-CSRF BFF, puis recettes métier FR/EN.
8. Ne jamais fusionner sur la seule réussite d'un test de structure des routes ; la preuve de sécurité doit être complète.

Ce lot est un garde-fou et une note de revue, **pas** une preuve que la suspension est prête à être exposée.
