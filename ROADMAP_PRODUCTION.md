# Roadmap de préparation production

Date : 26 octobre 2026 — dépôt privé `skaba89/kora-finance`

Référence figée : `7a51c45258301e8cfc50a0305ce023e08d286202` (`main` au début de l'audit). Les constats visent ce commit, pas l'état réel d'un VPS. Aucun accès aux données de production, aucune migration ni aucun déploiement effectués.

## Règles de livraison

Une PR par risque ou ensemble technique cohérent ; branche dédiée ; tests de régression avant correctif ; revue puis CI verte ; validation staging avant production. Pas de merge automatique, pas de déploiement dans cette mission. Les durées ci-dessous sont des estimations de travail, dépendantes des accès, de la disponibilité de l'expert-comptable et des résultats des tests.

| Priorité | Chantier | Dépendances | Critère de sortie | Effort indicatif |
|---|---|---|---|---|
| P0 | KF-01 : migration de protection des lignes | PostgreSQL 16 isolé | Attaques OLD/NEW et concurrence refusées, totaux immuables | 2–4 j |
| P0 | KF-02 : séparation des secrets migration/runtime | Config Alembic et Compose | API/worker fonctionnent sans owner ; migrations réussissent séparément | 1–2 j |
| P0 | KF-10 : restauration complète prouvée | Copie S3 indépendante, clé hors VPS | Compte rendu de restauration, intégrité base/pièces/audit, RTO/RPO mesurés | 2–4 j |
| P1 | KF-04 : export texte littéral | Aucune DB pour reproduction unitaire | Régression rouge avant, verte après ; exports existants verts | Correctif préparé ; revue/CI restantes |
| P1 | KF-03/05/06/07/08 : transactions et sécurité | Banc PostgreSQL concurrent | Tests déterministes clôture/rapports/auth/membres/MFA, zéro corruption | 5–10 j |
| P1 | KF-09/11/12/13 : release, sauvegardes, supervision, ressources | Staging proche cible | Pannes simulées alertées, release réversible et charge mesurée | 5–10 j |
| P1 | KF-15/16 : validation et complément comptable | Expert guinéen ; données de recette indépendantes | PV de validation, mapping versionné, flux et notes si offre système normal complet | 1–3 semaines + délai expert |
| P2 | KF-14/17/18/19/20/21/22/23 : durcissement et expérience | Socle P0/P1 | CSP durcie, devises cohérentes, scans CI, UX et offline vérifiés | 2–4 semaines selon offline |
| P3 | Offre SaaS complète | Périmètre choisi et pilote réussi | Modules nouveaux avec modèles, API, UX, tests et critères métier | À chiffrer après cadrage |

## PR séparées proposées

1. `audit/kora-production-20261026` : les six rapports, périmètre et preuves ; documentation uniquement.
2. `fix/audit-xlsx-literal-text` : KF-04, sérialisation texte et test indépendant. Correctif préparé et vérifié localement ; ne vaut pas validation globale.
3. `fix/ledger-parent-immutability` : KF-01, nouvelle migration sans réécrire 0005 déployée ; tests SQL app/owner et concurrence.
4. `security/runtime-database-credentials` : KF-02, Settings runtime/Alembic séparés ; test Compose et démarrage.
5. `test/closing-concurrency` : KF-03, tests de preuve d'abord ; correctif séparé seulement si nécessaire.
6. `fix/report-snapshot` : KF-05, transaction de lecture cohérente et tests d'interleaving.
7. `fix/auth-lockout-atomic` : KF-06 ; `fix/company-director-invariant` : KF-07 ; `security/mfa-enrollment-reauth` : KF-08.
8. `ops/independent-backups-restore-drill` : KF-09/10, sauvegarde protégée et restauration automatisée en environnement vierge.
9. `ops/release-observability-limits` : KF-11/12/13, scinder si la diff devient difficile à relire.
10. `accounting/syscohada-validated-statements` : KF-15/16, découper flux, notes et règles fiscales selon validation expert.

Seules les branches/PR dont un lien réel est donné dans la réponse de livraison sont effectivement ouvertes. Les autres noms sont des propositions de découpage, pas des changements réalisés.

## P3 — modules produits absents

Facturation commerciale (tiers, devis, factures, avoirs, relances), connecteurs/relevés et rapprochements bancaires/Mobile Money, imports avec staging et rapport de rejet, prévisionnels, déclaration fiscale préparatoire, pack de financement et partage révocable, portefeuille cabinet, abonnements et paiements, IA supervisée. Le séquencement commercial peut remonter certains modules en P1/P2 après choix de l'offre pilote.

Pour les paiements futurs : état de paiement explicite, montant/devise vérifiés côté serveur, référence opérateur unique, webhooks authentifiés et idempotents, rapprochement, remboursement et rejouabilité, tests événements dupliqués/inversés/perdus. Pour des attestations futures : portée juridique et émetteur identifiés, version du dossier, signature/vérification/révocation ; un simple PDF ne suffit pas.

## Déploiement progressif en Guinée

Phase A : démo synthétique et recette comptable. Phase B : petit pilote fermé avec PME/cabinet, support rapproché, données réelles seulement après P0 et accord de recette. Phase C : cohorte élargie après au moins une restauration et un cycle de clôture validés, charge et support mesurés. Phase D : commercialisation plus large conditionnée aux incidents du pilote, à l'offre précise, au support, aux engagements contractuels et à la capacité démontrée. Aucun feu vert national n'est donné par cet audit.
