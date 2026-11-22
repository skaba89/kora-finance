# Kora Finance — capacités activables par client

## Objectif et périmètre

Suite au benchmark Tiime/Pennylane : simplifier les parcours par profil et
commercialiser les modules séparément. Adapter chaque module aux pays (GNF,
SYSCOHADA, Mobile Money, connectivité réduite), avec une identité visuelle Kora
inspirée de Tiime. Ne pas copier une police propriétaire ni des actifs de marque.

Le lot M1 ajoute le catalogue pur `kora.tenancy.modules` et le calcul des états.
Il ne modifie pas encore le comportement de production. Aucun écran ou abonnement
fictif ; aucun module indisponible ne peut être accordé par le moteur. Les six
capacités déjà livrées conservent leur valeur par défaut active. Une capacité
nouvellement livrée doit recevoir une décision explicite d'activation par défaut.

Le lot M2 stocke les choix explicites par dossier, avec une révision optimiste
(0 pour un choix absent), une isolation RLS et un événement d'audit atomique.
La désactivation d'un prérequis conserve les choix de ses dépendants. Seul un
administrateur plateforme actif peut modifier la configuration interne. Aucun
endpoint public ni garde métier ne consomme encore ces choix.

## Règles impératives

- Séparer disponibilité produit, droit d'abonnement, choix administratif et RBAC.
- La décision serveur doit être appliquée aux API, actions, workers, exports et
  synchronisations offline. Masquer un menu ne constitue pas un contrôle d'accès.
- Un administrateur plateforme configure les capacités, sans lire les données
  comptables du client ni se substituer à son rôle métier.
- Authentification, isolation RLS, audit et accès au support restent hors catalogue.
- Une désactivation ne purge jamais les écritures, pièces, factures ou historiques.
  Définir la consultation historique, les dettes et traitements en cours avant
  d'autoriser le changement ; ne jamais bloquer l'intégrité des opérations liées.
- Distinguer la comptabilité visible des fondations comptables nécessaires aux
  achats, ventes et trésorerie. Auditer ces dépendances avant tout filtrage RBAC.
- L'offline ne doit jamais accepter une synchronisation avec un droit révoqué.
  Les brouillons locaux restent récupérables par leur propriétaire autorisé.

## Plan de livraison

1. M1 : catalogue, états, dépendances, tests purs ; aucune garde active.
2. M2 : persistance versionnée par tenant, migration additive Alembic, RLS,
   contraintes, concurrence, audit et tests croisés ; aucun changement d'accès.
3. M3 : API d'administration plateforme séparée de l'accès comptable, lecture
   des capacités effectives par tenant, contrats OpenAPI/TypeScript générés.
4. M4 : inventaire des routes, services et workers ; enforcement progressif,
   consultation historique et dépendances métier ; tests d'isolement et régression.
5. M5 : écran FR/EN Super Admin, simulation puis confirmation de changement,
   menus et dashboard dynamiques, état synchronisé sur mobile.
6. M6 : profils et offres commerciales, quotas, essais, expiration, paiements
   d'abonnement via prestataires autorisés ; aucune intégration simulée.
7. M7 : nouvelles capacités (OCR/GED, dépenses, actifs, analytique, fiscalité,
   cabinet, financement, IA, MakitiPlus), chacune avec ses tests et sa recette.

Toute activation repose sur des capacités réellement disponibles et validées.
Les paramètres de pays, le style et les fonctions sont configurables séparément.
