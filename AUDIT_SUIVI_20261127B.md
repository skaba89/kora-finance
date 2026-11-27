# Audit de suivi — 27 novembre 2026 (B)

Prolongement de `AUDIT_SUIVI_20261127.md` (état figé sur PR #210, référence
`71b2952`). Référence courante : `9907466` (`main`, merge PR #214 du 2026-11-27).
Périmètre : delta du jour — lots #211 à #214 vérifiés dans le code, mise à jour
du reste P0–P3 et des verrous. Audit réalisé depuis un bac à sable d'exécution :
**aucun accès au VPS de production ni à REC**, aucune donnée de production
consultée, aucun déploiement effectué.

## 1. État vérifié des lots du jour (PR #211 → #214)

| PR | Objet | Vérification dans le code `9907466` |
|---|---|---|
| #211 | Pile de recette locale sans Docker (`scripts/recette-sans-docker/`) | PG16 pgserver :54330 + fakeredis :63790 + moto :9000, rôles `kora_owner`/`kora_app` séparés, README ; consolidée par #214 (btree_gist sous `kora_owner`, buckets S3 séparés pièces/sauvegardes, `/health/live`) |
| #212 | Audit de suivi du matin (`AUDIT_SUIVI_20261127.md`) | Présent ; figé sur l'état #210 |
| #213 | E2E Playwright administration licences (SEC-1) | `apps/web/e2e/administration-licences.spec.ts` : 7 tests (suspension, réactivation, renouvellement adjacent, conflits concurrents 409) |
| #214 | **IMP-1 : rapport de précontrôle persisté et relu par pages** | Migration 0033 (colonnes `precheck_*` sur `accounting_import_batches` avec CHECK tout-rien ; table `accounting_import_issues` bornée à 1 000 anomalies, RLS `tenant_isolation`) ; service `precheck_and_persist` (verrou de ligne, idempotent) + `read_precheck_report` (autorisation + RLS à chaque lecture) ; route `GET /accounting-imports/{batch_id}/precheck` paginée (`limit ≤ 200`) ; web `ImportIssuesView` + `loadMoreIssuesAction` (aucun rechargement du fichier) ; 7 tests API, 4 tests vitest, 1 E2E >200 anomalies |

CI sur la PR #214 (run `46010029694`, branche `feature/import-precheck-report`,
2026-11-27) : 9/9 jobs verts, puis fusion sur `main`.
Validation locale : 46/46 tests imports, ruff, mypy, vitest 109/109, eslint,
typecheck, contrat openapi↔schema.ts régénéré, pile recette sans Docker.
Le fichier source déposé n'est **jamais** rechargé ni redéchiffré pour consulter
un rapport : la relecture ne passe que par la base, autorisation + RLS incluses.

## 2. Reste mis à jour

| Priorité | Item | État après #214 |
|---|---|---|
| P0 | PROD-1 déploiement VPS de #204/#207/#208/#211–#214 + santé/migrations/sauvegardes/rollback | **Inchangé — action opérateur, autorisation explicite requise** |
| P0 | SEC-2 vérifier l'activation réelle du MFA admin sur l'environnement déployé | Dépend de PROD-1 |
| P1 | IMP-2 confirmation humaine → génération transactionnelle de brouillons | **Devenu le trou produit n° 1** : l'import s'arrête encore avant toute écriture (0 endpoint `confirm`) |
| P1 | ~~IMP-1 persistance du rapport de précontrôle~~ | **Fait (#214)** |
| P1 | IMP-3 annulation d'un batch ; IMP-4 tests inter-entreprises sur tout le pipeline | Ouvert |
| P1 | CAB-1 frontend espace cabinet (backend `firms` prêt) ; CAB-2 tests séparation/révocation | Ouvert |
| P1 | SAAS-1 abonnements/factures SaaS | **Bloqué métier** (tarifs, entité facturante, PSP) |
| P1 | MOMO-1 imports Orange Money / MTN MoMo dédiés | Ouvert ; connecteurs réels interdits sans contrat opérateur |
| P2 | IA-1 OCR/IA contrôlé (aucune trace dans le code) ; FIN-1 dossier de financement ; UX-1 accessibilité/réseaux lents ; HYG-1 outbox + réconciliation S3 | Ouvert |
| P3 | OHADA-1 multi-pays (**exige un professionnel qualifié du pays**) ; MOD-1 stock/immobilisations/budgets/analytique/multidevise | Ouvert/bloqué métier |

## 3. Tableau de pilotage

| Dimension | État au `9907466` |
|---|---|
| Maturité | **82/100** — +2 : SEC-1, E2E licences admin (#213) ; +2 : IMP-1, rapport de précontrôle persisté, paginé et écran de revue (#214) ; outillage de recette reproductible consolidé (#211/#214). Verrous inchangés : PROD-1 (opérateur), IMP-2 (trou n° 1), CAB-1, SAAS-1/OHADA-1 (métier) |
| Prochaine action | PROD-1 (opérateur) — en parallèle dev : **IMP-2** puis IMP-3/IMP-4, CAB-1 |

## 4. Limites

- Mêmes limites que l'audit du matin : pas d'accès VPS/REC ; le score ne vaut
  que pour `9907466` et les preuves citées.
- Le test E2E paginé de #214 s'exécute en CI ; il n'a pas été rejoué localement
  dans ce bac à sable (Playwright non exécuté hors CI dans la session).
- PRs ouvertes à re-vérifier à chaque session avec un jeton à périmètre limité.
