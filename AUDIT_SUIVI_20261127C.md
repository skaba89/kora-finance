# Audit de suivi — 27 novembre 2026 (C)

Prolongement de `AUDIT_SUIVI_20261127B.md` (état figé sur PR #215, référence
`bfded0d`). Référence courante : branche `feature/import-confirm-drafts`
(basée sur `bfded0d`), PR ouverte pour IMP-2. Périmètre : le lot IMP-2 —
confirmation humaine d'un import et génération transactionnelle de brouillons.
Audit réalisé depuis un bac à sable d'exécution : **aucun accès au VPS de
production ni à REC**, aucune donnée de production consultée, aucun
déploiement effectué.

## 1. IMP-2 vérifié dans le code de la branche

« Confirmation humaine → génération transactionnelle de brouillons (aucune
écriture validée auto, idempotence par batch) » — le trou produit n° 1 de
l'audit B. État du pipeline avant : l'import s'arrêtait après le précontrôle,
aucun endpoint `confirm` n'existait.

| Garantie | Preuve dans le code |
|---|---|
| Acte humain explicite | `POST /companies/{id}/accounting-imports/{batch_id}/confirm` (droit `ENTRIES_WRITE`) ; l'écran n'affiche le bouton qu'après un précontrôle vert |
| Jamais validé automatiquement | `create_draft` uniquement : les écritures naissent `DRAFT`, `number IS NULL`, `posted_at IS NULL` ; aucune numérotation consommée (test dédié : `journal_sequences` reste vide) |
| Tout ou rien | brouillons + liens de traçabilité + marqueurs du batch + trace d'audit dans **une seule** transaction (`confirm_staged_import`, `session.begin()` unique) ; un fichier anomale est refusé sans aucune écriture |
| Idempotence par batch | verrou de ligne `FOR UPDATE` + colonnes `confirmed_at/confirmed_by_user_id/confirmed_entries` (CHECK tout-rien) ; un second appel → 409, zéro duplication |
| Références revérifiées au moment décisif | catalogue relu dans la transaction d'écriture (`_catalog` + `ImportCatalog.check` ligne à ligne) : journal désactivé ou période verrouillée après le dépôt → 422, rien n'est écrit ; revalidation positive ensuite |
| Fichier intègre | redéchiffrement + empreinte SHA-256 à chaque lecture (`load_staged_content`), parsing hors transaction (aucune connexion immobilisée) |
| Traçabilité | table `accounting_import_entries` (migration 0034, RLS `tenant_isolation` FORCE, clé composite vers `journal_entries`, CASCADE) ; une écriture n'appartient qu'à un seul batch ; trace d'audit `import.confirmed` à payload borné |
| Isolation | batch filtré par `tenant_id` (RLS + service) ; dossier étranger → 404 ; rôle sans `ENTRIES_WRITE` → 403 ; table de liens sous RLS |

Le modèle comptable existant n'est **pas** modifié : aucune colonne ni
contrainte ajoutée à `journal_entries`/`journal_lines` ; seul `create_draft`
gagne un paramètre `commit` (défaut `True`, comportement inchangé pour les
appels existants — même pattern que `post_pending`).

## 2. Validation locale (bac à sable, pile recette sans Docker + Mailpit)

- API : suite complète exécutée en trois segments, **zéro échec** — 318 puis
  638 puis 333 tests passés (incluant les 8 nouveaux de `test_import_confirm.py`
  : création de brouillons sans validation, idempotence 409, refus d'un
  fichier anomale sans écriture, revalidation du référentiel au moment décisif
  (désactivation puis réactivation du journal), période verrouillée, batch
  expiré 404, isolation 404/403, sérialisation de deux confirmations
  concurrentes prouvée par `pg_locks`).
- Qualité : `ruff check` et `ruff format` verts, `mypy` vert (266 fichiers),
  contrat `openapi.json` exporté et régénéré deux fois à l'identique
  (déterministe), `schema.ts` régénéré (+294 lignes attendues en diff).
- Web : vitest 113/113 (4 nouveaux tests `ImportConfirmSection` : proposition
  après précontrôle vert seulement, bouton désactivé pendant l'appel, annonce
  des brouillons créés avec masquage du bouton, échec affiché avec
  réessai), `eslint` dépôt entier vert, `next typegen && tsc --noEmit` vert,
  `next build` vert.
- E2E : `imports.spec.ts` étendu (confirmation → brouillons visibles dans le
  journal, filtres `statut=DRAFT`/`statut=POSTED` prouvent qu'aucune écriture
  n'est validée automatiquement). Exécution de ce test locale non rejouée
  (Playwright non lancé dans ce bac à sable) : il tourne dans la CI.
- Environnement : pile recette rétablie après recyclage du bac à sable
  (pgdata régénéré, `btree_gist` 16.2 recopié du paquet local), Mailpit
  autonome pour les tests SMTP réels, `KORA_EMAIL_BACKEND=memory` requis pour
  pytest (le `.env` de recette reste en `disabled`, côté serveur uniquement).

## 3. Reste mis à jour

| Priorité | Item | État après IMP-2 |
|---|---|---|
| P0 | PROD-1 déploiement VPS (#204/#207/#208/#211–#215 + IMP-2) + santé/migrations/sauvegardes/rollback | **Inchangé — action opérateur, autorisation explicite requise** |
| P0 | SEC-2 vérifier l'activation réelle du MFA admin sur l'environnement déployé | Dépend de PROD-1 |
| P1 | ~~IMP-2 confirmation → brouillons transactionnels~~ | **Fait (branche IMP-2)** |
| P1 | IMP-3 annulation d'un batch non validé ; IMP-4 tests inter-entreprises sur tout le pipeline | Ouvert ; IMP-3 est désormais déverrouillé par `accounting_import_entries` |
| P1 | CAB-1 frontend espace cabinet (backend `firms` prêt) ; CAB-2 tests séparation/révocation | Ouvert |
| P1 | SAAS-1 abonnements/factures SaaS | **Bloqué métier** (tarifs, entité facturante, PSP) |
| P1 | MOMO-1 imports Orange Money / MTN MoMo dédiés | Ouvert ; connecteurs réels interdits sans contrat opérateur |
| P2 | IA-1 OCR/IA contrôlé ; FIN-1 dossier de financement ; UX-1 accessibilité/réseaux lents ; HYG-1 outbox + réconciliation S3 | Ouvert ; HYG-1 peut réutiliser le périmètre transactionnel d'IMP-2 |
| P3 | OHADA-1 multi-pays (**exige un professionnel qualifié du pays**) ; MOD-1 stock/immobilisations/budgets/analytique/multidevise | Ouvert/bloqué métier |

## 4. Tableau de pilotage

| Dimension | État |
|---|---|
| Maturité | **85/100** (+3 : IMP-2 ferme le trou produit n° 1 — l'import va enfin jusqu'au journal, sous contrôle humain, sans aucune validation automatique ; guarantees testées : idempotence, tout-ou-rien, revalidation au moment décisif, isolation) |
| Prochaine action | PROD-1 (opérateur) — en parallèle dev : **IMP-3** (annulation d'un batch non validé, déverrouillée par la table de traçabilité) puis IMP-4, CAB-1 |

## 5. Limites

- Le score ne vaut que pour la branche IMP-2 et les preuves citées ; la CI
  (9 jobs) reste l'arbitre avant fusion.
- Le test E2E de confirmation n'a pas été rejoué localement (Playwright non
  exécuté dans ce bac à sable) ; il s'exécute dans la CI à chaque push.
- Pas d'accès VPS/REC ; aucune donnée de production consultée.
- PRs ouvertes à re-vérifier à chaque session avec un jeton à périmètre limité.
