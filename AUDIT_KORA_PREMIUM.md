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
