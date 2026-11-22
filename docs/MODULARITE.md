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

Le lot M3a prépare l'administration : annuaire minimal paginé des entreprises,
contrôle du droit plateforme en base, contexte dédié et instantané cohérent des
choix, révisions et dépendances du catalogue. L'état configuré est distinct des
droits métier effectivement appliqués. Les routes HTTP et contrats générés sont
livrés séparément en M3b.

M3b expose l'annuaire, la configuration et la mutation sur `/platform/module-clients`,
ainsi que la lecture des capacités configurées sur `/companies/{company_id}/module-capabilities`.
Les routes plateforme ne donnent aucun accès comptable. La mutation exige une
révision attendue et une valeur booléenne stricte. Les états restent informatifs
tant que M4 ne contrôle pas les autorisations métier.

M4a applique la garde serveur au prévisionnel : calcul, export PDF/Excel,
lecture et modification des paramètres, création d'instantanés. Un prérequis
trésorerie désactivé bloque également ces opérations. Les instantanés existants
et leur comparaison au réalisé restent consultables par les rôles autorisés.
Le contrôle est effectué à chaque nouvelle requête, après le RBAC ; une opération
déjà autorisée peut se terminer. Aucun worker ne produit ces prévisions.
Les autres modules restent informatifs jusqu'à leurs lots M4 dédiés.

M4b distingue la synchronisation hors connexion de la saisie interactive :
la Server Action fixe le marqueur interne `X-Kora-Offline-Sync` sur chacun
de ses appels (libre et guidé). Le serveur vérifie le module après le RBAC,
avant même un rejeu idempotent. La préparation d'un nouvel instantané local
vérifie également les capacités. Une réponse 403 conserve le brouillon dans
la file locale en état rejeté, relançable après réactivation. Les écritures
ordinaires restent autorisées selon le RBAC ; le marqueur distingue le parcours,
ce n'est pas un mécanisme d'authentification ni une preuve de connectivité.
Un client API qui utilise la saisie interactive conserve ses droits comptables.

M4c2 suspend les nouvelles relances automatiques lorsque Ventes est désactivé,
y compris lors d'une exécution du worker déjà enfilée. La politique est conservée
et reprend à la réactivation ; son activation explicite est refusée tant que le
module est inactif, mais sa désactivation reste possible. L'historique et le
recouvrement manuel des créances existantes restent accessibles selon le RBAC.
Les emails de relances déjà enregistrées poursuivent leur traitement normal.

## Règles impératives

M4d1 distingue les nouvelles opérations de trésorerie (création de comptes,
mouvements autonomes, virements et imports de relevés), soumises à la garde
Trésorerie, de la consultation et du rapprochement des relevés historiques.
Les règlements commerciaux existants et les écritures comptables restent
accessibles selon leurs droits métier ; aucun historique n'est supprimé.

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

## M4c1 — Documents commerciaux

Contrôle de la création de nouveaux devis et factures (ventes et achats)
au niveau des services, y compris la conversion d'un devis en facture.
Les documents déjà créés restent consultables et traitables ; les avoirs
correctifs restent autorisés selon les règles métier et le RBAC. Les règlements,
la comptabilisation, les remboursements et les annulations ne sont pas bloqués
afin de préserver les obligations existantes. Les fonctions annexes feront
l'objet d'un inventaire distinct avant toute restriction.

## M5a — Administration plateforme (PR #159)

Écran FR/EN intégré dans main : annuaire paginé, sélection du dossier, états
configurés, dépendances, confirmation de désactivation et révision optimiste.
Accès réservé au SUPER_ADMIN actif ; aucune nouvelle migration. La CI #371
est verte. La configuration seule ne garantit pas le blocage de toutes les
opérations : les gardes M4 restent progressives et les historiques préservés.

## Prochain lot — Portail SaaS

- M5b : recette des droits plateforme, isolation et retour au dossier métier ;
  simulation des conséquences et indication de la couverture effective M4.
- M6a : cadrer les offres et licences indépendamment des choix administratifs,
  sans tarif fictif ni mutation des droits existants.
- M6b : persistance versionnée, audit des changements, expiration et essais,
  migrations additives et contrats générés.
- M6c : interface de gestion et supervision, puis paiement réel après sélection
  et validation du prestataire adapté au marché guinéen.

Aucune donnée comptable ni identité client supplémentaire n'est exposée à la
plateforme sans besoin explicite et validation du périmètre.

## M5b — accueil plateforme

Accueil FR/EN réservé aux administrateurs plateforme, total réel des dossiers
via l'annuaire existant, accès à la configuration des modules. Aucun indicateur
commercial fictif ni accès aux données comptables. Recette de refus desktop/mobile
étendue à l'accueil ; recette positive et CI requises avant mise en production.

## M6a1 — définition versionnée des offres

Moteur pur `kora.tenancy.offers.OfferVersion` : code, version positive et ensemble
immuable de capacités livrées, prérequis inclus. Aucun tarif ni offre attribuée
par défaut ; aucun changement de module, de RBAC ou de données existantes.
La composition d'une offre n'est pas une autorisation métier. Le prochain lot
modélisera licences, essais et expiration avant persistance et audit M6b.

## M6a2 — périodes de licence

Modèle pur immuable lié au dossier et à une version d'offre. Dates civiles
explicites, début inclus et fin exclue ; états planifié, essai, actif, suspendu
et expiré. L'expiration prime sur la suspension hors période. Le renouvellement
est représenté par une nouvelle période ; aucun paiement ni contrôle de droits.
M6b devra garantir références, non-chevauchement, historique et audit en base.

## M6b1 — stockage des offres

Migration additive 0028 : table globale des versions commerciales, clé composée
code/version, modules non vides et sans NULL. Lecture seule pour kora_app jusqu'au
service de publication audité ; aucune offre initiale ni licence attribuée.
La validation catalogue reste indispensable à la publication. M6b2 ajoutera
le service de publication et les contraintes de périodes de licence sous RLS.
