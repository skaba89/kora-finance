# Kora Finance Premium — bilan de clôture provisoire et reste à faire

Date : 21 novembre 2026. Référence stable : `main` `8c0136f` (PR #127).
Base avant programme : `ce89b41` (PR #110), audit initial `AUDIT_UX_UI.md`.
La PR #128 (commit `97c0e55`) est en validation ; elle n'est pas incluse dans
le score stable. Ce document n'est ni une certification WCAG ni une autorisation
de mise en production. Le lot thème qui accompagne ce document reste à valider.

## 1. Avant / après et preuves de continuité

| Domaine | Avant | Après sur main | Preuve |
|---|---|---|---|
| Identité | thème générique | Inter variable, fond #F8FAFC, texte #0F172A, primaire #0F766E, tokens sémantiques | #111, `globals.css`, `docs/STYLE_UI.md` |
| Navigation | menu de dossier plat | groupes, recherche de modules, raccourci clavier, sidebar repliable, sélecteur de dossier | #112–115, `company-navigation.tsx`, `company-switcher.tsx` |
| Pilotage | cartes et indicateurs basiques | KPI et hiérarchie financière, graphiques et priorités | #116, `kpi-card.tsx`, `dashboard/` |
| Comptabilité | tableaux hétérogènes | DataTable, densité, filtres, fiches mobiles, pagination selon le module | #117–118, `data-table.tsx`, `table-density-select.tsx` |
| Vente / achat | parcours denses | onglets métier, recouvrement, tiers, tableaux et actions | #119–120 |
| Trésorerie | interface opérationnelle | rapprochement et prévisionnel hiérarchisés | #121–122 |
| États financiers | présentation initiale | bilan, résultat et TFT harmonisés, montants exacts | #123 |
| Administration | écrans disparates | paramètres, audit, sécurité compte et MFA | #124–125 |
| Hors réseau | saisie et synchronisation existantes | statut réseau, appareil, file locale et compteurs | #126 |
| Accessibilité | repères partiels | lien d'évitement, repère main, focus et reflow six largeurs sur connexion/tableau de bord | #127 |

Inventaire : 37 fichiers `page.tsx`, huit primitives UI, 19 fichiers de tests
unitaires et 22 fichiers E2E (hors ajout #128 et lot thème). DataTable est utilisé
dans onze fichiers de pages. La CI #293 contrôlant #127 est terminée avec succès :
https://github.com/skaba89/kora-finance/actions/runs/44904129559 .
La CI #295 de #128 est suivie séparément :
https://github.com/skaba89/kora-finance/actions/runs/44905553856 .

## 2. Score UX/UI stable, sur 100 (revue interne, non certification)

Le score est une estimation conservatrice de maturité, pas un pourcentage de
fonctionnalités ni un résultat de test utilisateur. Les points correspondent
aux éléments observables dans main et la CI ; les écarts non vérifiés restent
déduits. Le score global du produit et la conformité comptable ne sont pas évalués ici.

| Axe | Max | Acquis | Justification de la déduction |
|---|---:|---:|---|
| Identité et design system | 18 | 16 | thème utilisateur absent de main ; inventaire de composants incomplet |
| Navigation et orientation | 15 | 13 | recherche de modules, pas recherche d'entités ni centre de notifications |
| Parcours financiers existants | 18 | 16 | parcours cabinet et tâches de terrain non validés |
| Tables et lisibilité des montants | 15 | 12 | colonnes configurables, tri/export et détail non uniformes |
| Mobile et hors connexion | 12 | 9 | six tailles testées sur deux parcours ; pas recette exhaustive en faible réseau |
| Accessibilité | 10 | 5 | repères, clavier, focus ; pas encore de baseline parcourue ni contrôle lecteur d'écran |
| Performance | 7 | 3 | Inter auto-hébergée, chargements ; objectifs LCP/INP/CLS non mesurés |
| Qualité et gouvernance | 5 | 4 | CI verte sur #127, preuve visuelle avant/après exhaustive manquante |
| **Total** | **100** | **78** | **21 points à acquérir pour 99/100** |

Le lot 11B ajoute l'instrumentation, mais une CI verte ne garantit pas zéro
violation axe : la baseline est informative. Le lot thème ajoute la préférence
locale système/clair/sombre, sans mutation serveur ; la recette contraste et
une éventuelle flash de thème au premier rendu restent à mesurer. Aucun point
supplémentaire n'est compté avant validation des deux lots.

## 3. Références concurrentielles (consultées le 21 novembre 2026)

Ce benchmark se limite aux capacités publiées par les éditeurs ; aucun login,
essai chronométré ni audit d'accessibilité concurrent n'a été réalisé. Stripe
est une référence UX de paiements, pas un substitut général au SYSCOHADA.

| Référence | Capacité documentée | Écart ou orientation Kora |
|---|---|---|
| [Pennylane](https://www.pennylane.com/fr/expert-comptable/production-comptable) | automatisation comptable, collaboration cabinet et entreprise | portefeuille multi-dossiers, suivi des tâches et validation humaine |
| [QuickBooks](https://quickbooks.intuit.com/global/cloud-accounting-software/) | factures, reçus mobiles, rapports, rapprochement | capture de pièces, import et automatisation contrôlée |
| [Xero](https://www.xero.com/us/accounting-software/xero-accounting-mobile-app/) | facturation mobile, capture de justificatifs, rapprochement | parcours tactile terrain, pièces hors connexion |
| [Odoo](https://www.odoo.com/documentation/18.0/applications/finance/accounting/bank/reconciliation.html) | rapprochement depuis le tableau de bord comptable | actions contextuelles et parcours de rapprochement cohérent |
| [Stripe](https://docs.stripe.com/dashboard/search) | recherche transverse par entités et opérateurs | recherche globale autorisée par tenant, résultats classés et navigation clavier |

Différenciation à consolider : comptabilité SYSCOHADA, GNF avec montants exacts,
import Mobile Money, français/anglais et saisie hors réseau. Ces avantages
locaux ne démontrent pas que Kora dépasse déjà les cinq références.

## 4. Backlog priorisé et critères d'acceptation

| Priorité | Chantier | Critère de sortie |
|---|---|---|
| P0 | Finir #128 et lire ses rapports | CI complète verte ; violations, revue manuelle et mesures LCP/CLS/interaction consignées par écran et profil |
| P0 | Thèmes et accessibilité | choix persisté, contraste AA vérifié FR/EN clair/sombre, navigation clavier/lecteur d'écran, zéro violation critique/sérieuse confirmée |
| P0 | Recette responsive globale | 37 pages et états représentatifs sur 360/390/768/1024/1440/1920 ; aucune fuite ou débordement global, captures avant/après |
| P0 | Web Vitals | LCP < 2500 ms, INP < 200 ms, CLS < 0,1 au p75 sur profils terrain documentés ; distinguer laboratoire et terrain |
| P1 | DataTable et composants | tri, filtres, colonnes, actions, états et exports selon besoins ; pas d'arrondi, d'accès ou de requête hors tenant |
| P1 | Recherche et tâches | résultats par entité avec filtrage des droits, aucun résultat inter-tenant ; navigation clavier et latence validées |
| P1 | Parcours cabinet | portefeuille et affectations réels, permissions et isolation vérifiées ; ne pas maquiller une fonctionnalité absente |
| P1 | Recette utilisateur | scénarios identiques sur Kora et références : facture, saisie, rapprochement, clôture, recouvrement ; temps, erreurs, réussite et satisfaction |
| P2 | Import/migration, financement, IA et abonnements | suivre les phases 5–8 validées dans `docs/PLAN.md`, après arbitrage métier |

Les phases 5–8 ne sont pas des améliorations graphiques ; elles nécessitent
des incréments métier et des tests d'isolation dédiés. Le score final 99/100 ne
sera envisagé qu'avec preuves vérifiables. Le programme ne modifie pas les
calculs comptables, permissions, RLS ou schéma de base pour l'esthétique.

## 5. Résultats mesurés après #128 et #129 (21 novembre 2026)

Les CI #295 et #296 sont vertes et les deux PR sont fusionnées (`f79f4aa`).
Le rapport Playwright du run 44905553856, artefact 14707623753, contient les
mesures suivantes (profil simulé : 150 ms, 1,6 Mbit/s descendant, 750 kbit/s
montant, CPU x4, cache froid, service worker contourné).

| Profil | LCP | CLS | Interaction max observée |
|---|---:|---:|---:|
| Desktop 1280 × 720 | 948 ms | 0,00047 | 64 ms (30 événements) |
| Mobile 393 × 727 | 860 ms | 0,00325 | 88 ms (26 événements) |

Ces deux mesures respectent les seuils indicatifs de laboratoire ; elles ne
constituent pas un INP terrain ni un p75. Axe 4.14.0 : connexion FR et EN sans
violation sur les deux profils ; tableau de bord : `label-content-name-mismatch`
(7 desktop, 4 mobile), `nested-interactive` (1 sur chaque profil), revue manuelle
du contraste (11 desktop, 26 mobile). Le correctif du graphique mensuel utilise
un groupe accessible et inclut le libellé visible dans le nom de chaque mois.
Les deux règles deviennent bloquantes dans la CI, avec audit supplémentaire du
thème sombre. La validation de ce correctif et la revue manuelle restent à faire.

## 6. Recette responsive financière — lot 13A (21 novembre 2026)

La PR #130 est fusionnée (`a6cc2ec`), CI #300 verte (run 44908757635).
Le test historique du graphique a été aligné sur son nouveau rôle accessible.
La revue manuelle des contrastes reste ouverte.

La recette `recette-finance-premium.spec.ts` étend la couverture à douze
écrans financiers réels avec un dossier synthétique neuf : écritures, création,
saisie guidée, balance, grand livre, lettrage, ventes, achats, tiers, trésorerie,
prévisions et états financiers. Les six largeurs sont réparties entre les deux
projets Playwright : 360/390/768 et 1024/1440/1920. Chaque écran produit une
capture à 390 et 1440 px et un relevé JSON du débordement global (72 mesures
au total). Le titre attendu est contrôlé à chaque largeur ; le débordement
reste informatif pour cette première baseline. Les états détaillés, peuplés,
les autres routes, la recette anglaise et les corrections éventuelles restent
à traiter. Aucun résultat ni point de maturité supplémentaire n'est acquis
avant lecture du rapport CI.

## 7. Lot 13B — résultats et garde de non-régression responsive

PR #131 fusionnée (`8cc937c`), CI #302 verte (run 44911384186,
artefact Playwright 14710620442). Les deux rapports `reflow-finance`
contiennent 36 mesures chacun : largeur effective égale à la largeur demandée,
débordement global de **0 px dans les 72 cas**, aucun écart. Les rapports axe
du tableau de bord sombre ne signalent aucune violation automatique sur les
deux profils, mais 11 et 26 éléments de contraste nécessitent une revue manuelle.

Le lot 13B rend les 72 cas financiers bloquants (tolérance 1 px), vérifie
le nombre de mesures et les largeurs réelles. Il étend la baseline à neuf
écrans : six paramètres du dossier, seuils d'alerte, audit et hors connexion.
La nouvelle matrice prévoit 126 mesures et 42 captures au total ; les nouveaux
écarts sont informatifs jusqu'à lecture des rapports. Cette mesure sur dossier
neuf ne prouve pas la qualité des tableaux remplis ni celle du parcours anglais.

Revue visuelle ciblée des captures #302 : ventes et nouvelle écriture à 390 px,
états financiers à 1440 px. Aucun débordement visible sur ces trois captures.
La hauteur cumulée de l'en-tête mobile, de l'alerte de vérification email et
de la navigation repousse toutefois le contenu métier : compacter ces zones
sans masquer les actions ni les alertes importantes est le prochain chantier.

## 8. Lot 14 — en-tête mobile compact

PR #132 fusionnée (`502e387`), CI #304 verte (run 44914033626,
artefact 14710479033) : 63 mesures par profil, aucun écart de reflow supérieur
à 1 px. Les 126 cas deviennent bloquants.

Sur smartphone, en-tête en deux rangées avec les commandes système/langue,
compte et déconnexion conservées ; les deux dernières utilisent des icônes
avec nom accessible et cibles de 44 px. Les espacements du contexte dossier
et de la navigation sont réduits uniquement sur mobile. L'alerte email et le
comportement de déconnexion hors connexion sont conservés. La recette mesure
une hauteur d'en-tête cible de 120 px maximum à 360 et 390 px et vérifie les
commandes disponibles. Captures et résultats effectifs à confirmer en CI.
