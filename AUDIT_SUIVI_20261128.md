# Audit de suivi — 28 novembre 2026 (IMP-4)

Prolongement de `AUDIT_SUIVI_20261127C.md` (état figé sur PR #216, référence
`14cd696`). Référence courante : branche `test/imp4-import-cross-tenant-end-to-end`
(basée sur `14cd696`), PR #217 pour IMP-4. Périmètre : le volet tests du lot
import — isolation inter-entreprises prouvée à chaque étape du pipeline
(dépôt, précontrôle, lecture du rapport, confirmation). Audit réalisé depuis
un bac à sable d'exécution : **aucun accès au VPS de production ni à REC**,
aucune donnée de production consultée, aucun déploiement effectué.

## 1. IMP-4 vérifié dans le code de la branche

« Tests inter-entreprises sur tout le pipeline d'import » — le volet test du
backlog P1, verrouillé jusqu'ici par l'absence du pipeline confirmé (IMP-2).
Un seul test, volontairement complet, ajouté à `test_import_confirm.py`
(+58 lignes, aucun code produit modifié) :
`test_meme_fichier_deux_dossiers_isole_tous_les_parcours`.

| Garantie testée | Preuve dans le test |
|---|---|
| Dépôts isolés malgré un contenu identique | le **même** fichier (SHA identique) est déposé dans deux dossiers : ids de batches distincts et deux objets distincts dans le stockage (`len(storage) == 2`) |
| Précontrôle inter-dossiers refusé | `POST .../{batch}/precheck` du dossier voisin → 404, dans les deux sens (mine→other et other→mine) |
| Rapport inter-dossiers refusé | `GET .../{batch}/precheck` du dossier voisin → 404, dans les deux sens |
| Confirmation inter-dossiers refusée | `POST .../{batch}/confirm` du dossier voisin → 404, dans les deux sens |
| Les refus n'entravent pas le propriétaire | chaque dossier poursuit son parcours complet : précontrôle 200 (`valid: true`), rapport relu 200 (`entries == 2`), confirmation 200 (`entries == 2`), second appel → 409 sans duplication |
| Isolation au niveau des données | sous RLS de chaque tenant : exactement 2 écritures + 2 liens `accounting_import_entries`, tous `tenant_id` du bon dossier, écritures `DRAFT` (`number IS NULL`) |
| Aucune écriture validée | statut `DRAFT` partout — l'isolation ne crée aucun raccourci vers la validation automatique |

Le code produit n'est **pas** modifié : le test verrouille des garanties
déjà implémentées (RLS + filtrage tenant dans le service) et les fait
vivre face aux futures évolutions du pipeline (IMP-3 notamment).

## 2. Validation (bac à sable + CI 9 jobs)

- Premier tour de CI sur la PR : **8/9 verts**, échec unique sur
  `make api-lint` — `ruff format --check` refusait trois lignes vides avant
  le nouveau test. Corrigé par un commit dédié (`89f85e0`, suppression d'une
  ligne vide, aucun changement fonctionnel), vérifié en bac à sable avec les
  outils du dépôt : `ruff check` et `ruff format --check` verts (301
  fichiers), `mypy` strict vert (266 fichiers).
- Deuxième tour de CI : **9/9 verts** (run `46119608278`) — Périmètre
  modifié, Secrets (gitleaks), Restauration synthétique, Contrat d'API à
  jour, SCA, **API (ruff, mypy, pytest)**, E2E (pile complète +
  Playwright), Web (eslint, tsc, vitest, build), Résultat. Fusion
  ensuite (référence `6642a26`).
- Le nouveau test s'exécute dans le job API de la CI (suite complète avec
  couverture) : c'est lui qui porte la preuve d'exécution, conformément à
  la discipline « la CI est l'arbitre avant fusion ».
- Recette sans Docker : pile PG/Redis/S3 reconstruite après recyclage du
  bac à sable (répertoires runtime du `pgdata` recréés, dont
  `pg_logical/snapshots` — piège nouveau et documenté ici), venv API
  reinstallé sous Python 3.13 (`uv sync`). La suite pytest locale n'a pas
  été relancée avant le push (indisponibilité intermittente du bac à
  sable) ; les lints et le typage l'ont été, et la CI a exécuté la suite
  complète.

## 3. Reste mis à jour

| Priorité | Item | État après IMP-4 |
|---|---|---|
| P0 | PROD-1 déploiement VPS (#204/#207/#208/#211–#217) + santé/migrations/sauvegardes/rollback | **Inchangé — action opérateur, autorisation explicite requise** |
| P0 | SEC-2 vérifier l'activation réelle du MFA admin sur l'environnement déployé | Dépend de PROD-1 |
| P1 | ~~IMP-2 confirmation → brouillons transactionnels~~ | **Fait (#216)** |
| P1 | ~~IMP-4 tests inter-entreprises sur tout le pipeline~~ | **Fait (#217)** |
| P1 | IMP-3 annulation d'un batch non validé | Ouvert ; déverrouillé par `accounting_import_entries`, l'isolation est désormais prouvée par tests |
| P1 | CAB-1 frontend espace cabinet (backend `firms` prêt) ; CAB-2 tests séparation/révocation | Ouvert |
| P1 | SAAS-1 abonnements/factures SaaS | **Bloqué métier** (tarifs, entité facturante, PSP) |
| P1 | MOMO-1 imports Orange Money / MTN MoMo dédiés | Ouvert ; connecteurs réels interdits sans contrat opérateur |
| P2 | IA-1 OCR/IA contrôlé ; FIN-1 dossier de financement ; UX-1 accessibilité/réseaux lents ; HYG-1 outbox + réconciliation S3 | Ouvert ; HYG-1 peut réutiliser le périmètre transactionnel d'IMP-2 |
| P3 | OHADA-1 multi-pays (**exige un professionnel qualifié du pays**) ; MOD-1 stock/immobilisations/budgets/analytique/multidevise | Ouvert/bloqué métier |

## 4. Tableau de pilotage

| Dimension | État |
|---|---|
| Maturité | **86/100** (+1 : le pipeline d'import est maintenant prouvé étanche entre dossiers de bout en bout — dépôt, précontrôle, rapport, confirmation, données — face aux évolutions à venir ; lot produit complet jusqu'au journal, reste IMP-3 comme ultime complément d'exploitation) |
| Prochaine action | PROD-1 (opérateur, autorisation requise) — en parallèle dev : **IMP-3** (annulation d'un batch non validé), puis CAB-1 |

## 5. Limites

- Le score ne vaut que pour l'état fusionné `6642a26` et les preuves citées ;
  la CI (9 jobs) reste l'arbitre avant chaque fusion.
- La suite pytest locale n'a pas été rejouée dans ce bac à sable (pile
  reconstruite mais suite non relancée avant push) ; compensée par le tour
  de CI complet sur la PR, exécutant la même suite que `make api-test`.
- Pas d'accès VPS/REC ; aucune donnée de production consultée.
- PRs ouvertes à re-vérifier à chaque session avec un jeton à périmètre limité.
