# Audit de suivi — 28 novembre 2026 (IMP-3)

Prolongement de `AUDIT_SUIVI_20261128.md` (état figé sur PR #217/#218,
référence `f5df450`). Référence courante : `main` = `5fad681` — PR #219
(backend IMP-3) puis PR #220 (volet UI). Périmètre : l'annulation définitive
d'un batch d'import non validé, dernier volet opérationnel du pipeline
d'import (dépôt → précontrôle → confirmation → annulation avant validation).
Audit réalisé depuis un bac à sable d'exécution : **aucun accès au VPS de
production ni à REC**, aucune donnée de production consultée, aucun
déploiement effectué.

## 1. IMP-3 livré

Route `POST /companies/{id}/accounting-imports/{batch_id}/cancel` et service
`import_cancel.py`, miroir de la confirmation — la sémantique exacte que le
docstring de `ImportBatchEntry` annonçait (« l'annulation d'un batch ne
visera que les brouillons encore présents »).

| Garantie | Implémentation et preuve de test |
|---|---|
| Dépôt simple (jamais confirmé) | référence, rapport persisté et objet chiffré disparaissent en une transaction ; capacité du dossier (10 fichiers / 128 Mio) libérée immédiatement (`test_cancel_un_depot_simple_libere_immediatement`) |
| Batch confirmé | seuls les brouillons **encore présents et encore `DRAFT`** sont supprimés, lignes en CASCADE ; un brouillon déjà supprimé par son auteur a emporté son lien et ne compte plus (`test_cancel_supprime_les_brouillons_encore_presents` : 2 écritures et 4 lignes retirées, zéro ligne restante) |
| Écriture validée → refus intégral (409) | toute écriture du batch passée `POSTED` interdit l'annulation : contre-passation obligatoire, jamais de destruction d'écriture validée ; rien n'est entamé (batch, objet et écritures intacts vérifiés après le 409) (`test_cancel_refuse_une_ecriture_deja_validee`) |
| Verrou de ligne | le batch est verrouillé `FOR UPDATE` : confirmation et annulation sont mutuellement exclusives quel que soit l'ordre d'arrivée (`test_cancel_attend_le_verrou_du_batch`, attente prouvée via `pg_locks`) |
| Reprise immédiate | le même fichier (SHA identique) est redéposé aussitôt sur un batch neuf, confirmable de nouveau (`test_cancel_puis_reprise_du_meme_fichier`) |
| Traçabilité d'audit | `import.cancelled` complète la chaîne `import.confirmed` avec les comptes (brouillons, lignes, confirmés) ; les deux événements coexistent après annulation d'un batch confirmé |
| Pièces jointes | détachées dans la transaction, objets purgés après commit — même schéma que `delete_draft` |
| Isolation et rôles | 404 inter-dossiers (les deux sens), 403 lecteur `PME_LECTEUR`, les refus n'entravent pas le dirigeant (`test_cancel_isole_par_dossier_et_par_role`) |
| Inconnu / expiré | 404, y compris après annulation (idempotence par disparition) ; un batch expiré refusé reste entier, la purge worker reste maîtresse (`test_cancel_inconnu_ou_expire_repond_404`) |
| Pas d'exigence de devise | un batch devenu étranger au dossier (devise modifiée après dépôt) reste annulable — c'est précisément lui qu'il faut pouvoir retirer |

### Volet UI (PR #220)

- Action serveur `cancelImportAction` ; composant `ImportCancelSection`,
  miroir de la section de confirmation : avertissement définitif avant
  l'acte, bandeau `aria-live` avec compteurs (brouillons supprimés, lignes)
  une fois annulé, erreur 409 affichée en `role=alert` avec réessai.
- Libellés FR/EN ; la section de confirmation disparaît après annulation ;
  le dépôt reste annulable avant comme après confirmation, précontrôle
  vert ou non.
- 5 tests vitest nouveaux ; parcours **E2E** complet ajouté à
  `imports.spec.ts` : confirmer → annuler → journal vide → redéposer le
  même fichier → reconfirmer (la reprise, exécutée sur la pile réelle par
  le job E2E de la CI).
- Contrat : `openapi.json` et types TS régénérés (commit `f71087f`),
  aucun changement de schéma de base de données, aucune migration.

## 2. Validation (bac à sable + CI 9 jobs, deux PR)

- Local : `ruff check` + `ruff format --check` verts (303 fichiers), `mypy`
  strict vert (268 fichiers). Pytest ciblé : **58 verts** sur le périmètre
  imports complet (dont les 7 tests d'annulation) et **88 verts** sur le
  voisinage de code partagé (accounting, audit, attachments, closing,
  guardrails). La suite intégrale n'entre pas dans la fenêtre d'exécution
  du bac à sable (découpage tenté, deux débordements) ; le job API de la
  CI l'exécute en entier avec couverture ≥ 90 %.
- PR #219 : premier tour **8/9 verts**, échec attendu du job « Contrat
  d'API à jour » (la nouvelle route change le schéma) ; régénération du
  contrat puis second tour **9/9 verts**, fusion (`a944b29`).
- PR #220 : premier tour **9/9 verts** d'emblée (Web, E2E avec le nouveau
  parcours, API, contrat, SCA, secrets, restauration), fusion (`5fad681`).
- Côté bac à sable, deux pièges d'environnement réglés sans impact produit :
  `moto_server` lent à se lier (attente robuste dans le script de recette)
  et cache d'identité SQLAlchemy dans un test (lecture périmée d'un statut
  modifié hors session — `expire_all()` avant relecture).

## 3. Reste mis à jour

| Priorité | Item | État après IMP-3 |
|---|---|---|
| P0 | PROD-1 déploiement VPS (#204/#207/#208/#211–#220) + santé/migrations/sauvegardes/rollback | **Inchangé — action opérateur, autorisation explicite requise** |
| P0 | SEC-2 vérifier l'activation réelle du MFA admin sur l'environnement déployé | Dépend de PROD-1 |
| P1 | ~~IMP-2 confirmation → brouillons transactionnels~~ | **Fait (#216)** |
| P1 | ~~IMP-4 tests inter-entreprises sur tout le pipeline~~ | **Fait (#217)** |
| P1 | ~~IMP-3 annulation d'un batch non validé, gestion des conflits/reprises~~ | **Fait (#219 backend + #220 UI/E2E)** |
| P1 | CAB-1 frontend espace cabinet (backend `firms` prêt) ; CAB-2 tests séparation/révocation | **Suivant** |
| P1 | SAAS-1 abonnements/factures SaaS | **Bloqué métier** (tarifs, entité facturante, PSP) |
| P1 | MOMO-1 imports Orange Money / MTN MoMo dédiés | Ouvert ; connecteurs réels interdits sans contrat opérateur |
| P2 | IA-1 OCR/IA contrôlé ; FIN-1 dossier de financement ; UX-1 accessibilité/réseaux lents ; HYG-1 outbox + réconciliation S3 | Ouvert ; HYG-1 peut réutiliser le périmètre transactionnel d'IMP-2/IMP-3 |
| P3 | OHADA-1 multi-pays (**exige un professionnel qualifié du pays**) ; MOD-1 stock/immobilisations/budgets/analytique/multidevise | Ouvert/bloqué métier |

## 4. Tableau de pilotage

| Dimension | État |
|---|---|
| Maturité | **87/100** (+1 : le cycle d'exploitation de l'import est désormais complet — déposer, précontrôler, confirmer, annuler avant validation — avec les mêmes garanties transactionnelles, RLS, verrou, audit et reprise que le reste du pipeline, du service jusqu'à l'écran ; plus aucune trappe opérationnelle sur l'import) |
| Prochaine action | PROD-1 (opérateur, autorisation requise) — en parallèle dev : **CAB-1** (frontend espace cabinet, backend `firms` prêt), puis CAB-2 |

## 5. Limites

- Le score ne vaut que pour l'état fusionné `5fad681` et les preuves citées ;
  la CI (9 jobs) reste l'arbitre avant chaque fusion.
- La suite pytest intégrale n'a pas été rejouée en une seule passe locale
  (fenêtre d'exécution du bac à sable dépassée deux fois) ; compensée par
  les runs ciblés locaux étendus au voisinage partagé et par le job API de
  la CI (même suite, couverture ≥ 90 %) sur chaque PR.
- Pas d'accès VPS/REC ; aucune donnée de production consultée.
- PRs ouvertes à re-vérifier à chaque session avec un jeton à périmètre
  limité, détruit après usage.
