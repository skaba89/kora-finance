# Phase 3D — Mobile Money : architecture des connecteurs et adaptateurs d'import

État au 13/11/2026. Ce document fixe l'architecture de la sous-phase 3D
(connecteurs Mobile Money Orange Money / MTN MoMo Guinée) et **définit
explicitement ce qui est implémenté de ce qui ne l'est pas**.

Règles de conduite (mission §3D) : aucune API opérateur n'est activée ni
simulée ; aucune disponibilité n'est annoncée sans autorisation de
l'opérateur ; aucune écriture comptable n'est postée automatiquement.

## 1. Ce qui est implémenté aujourd'hui

| Capacité | État | Portée |
|---|---|---|
| Relevés OFX 1.x/2.x (banques) | **Livré (3B)** | Parseur sur mesure, montants signés, GNF entier |
| Relevés CSV génériques (banques et opérateurs) | **Livré (3B)** | Colonnes détectées par rôles, encodages UTF-8/cp1252 |
| **Colonne « Frais » des exports Mobile Money → ligne `[FRAIS]` distincte** | **Livré (3D)** | CSV, toute colonne frais/commission reconnue |
| Déduplication fichier (SHA-256 par compte) | **Livré (3B)** | Réimport refusé, jamais de double comptage |
| Déduplication métier par ligne (empreinte date/montant/libellé/référence) | **Livré (3B)** | Doublons signalés entre relevés recouvrants |
| Rapprochement assisté des lignes importées (3C) | **Livré** | Confirmation toujours manuelle |
| Connecteurs API opérateurs (Collections/Disbursements) | **Non implémenté — désactivé** | Voir §2 et §3 |
| Webhooks opérateurs | **Non implémenté — désactivé** | Requiert un contrat et une exposition signée |
| Import Excel (.xlsx) | **Non implémenté** | Prochaine étape du même chantier |

## 2. Conditions officielles des API opérateurs (sources consultées le 13/11/2026)

| Opérateur | Offre développeur | Produits | Conditions d'accès |
|---|---|---|---|
| MTN MoMo | Portail développeur MoMo — momodeveloper.mtn.com (hébergé Ericsson), momo.mtn.com/api | Collections (encaissements), Collection Widget (MoMoPay QR/USSD), Disbursements (paiements de masse), Remittances | Souscription par produit ; API User + API Key + clé d'abonnement ; **sandbox public** ; **production = provisionnement par marché et contrat avec l'opérateur** (KYB) |
| Orange (Orange Money) | Orange Developer — developer.orange.com, API « Orange Money Web Payment » (om-webpay) | Paiement web marchand (redirection) | Compte développeur + **contrat marchand Orange Money** ; OAuth2, token de paiement à durée courte ; disponibilité et activation **par pays**, sous réserve du contrat local |

Conclusion d'audit : les deux opérateurs disposent d'offres développeurs
officielles, mais **aucune autorisation marchande n'a été accordée à ce
projet à ce jour** — ni contrat MTN, ni contrat Orange, ni identifiants de
production, ni exemple d'export réel fourni par un opérateur.

## 3. Décision : connecteurs API non implémentés, adaptateurs d'import livrés

Conformément à la mission (§3D) : *« Si les API ne sont pas accessibles,
développer des adaptateurs d'import CSV/Excel explicitement étiquetés comme
tels »*. Le périmètre livré est donc :

1. **Import CSV étiqueté** — un export de relevé Orange Money / MTN MoMo
   déposé par le comptable est lu par le même pipeline que les relevés
   bancaires (3B) : lignes en attente de rapprochement, fichier original
   conservé chiffré, déduplication identique. La colonne frais de l'export
   est reconnue et produite en **ligne distincte `[FRAIS]`** — la commission
   est visible, rapprochable et comptabilisable séparément.
2. **Étiquetage explicite** — le libellé `[FRAIS]` est visible dans l'écran
   d'import, le rapprochement et les exports ; l'origine du relevé reste
   tracée par le nom du fichier et l'objet original conservé.
3. **Aucun écran ni statut « connecté »** — aucune interface ne laisse
   croire à une liaison directe avec un opérateur : il n'y a rien de tel
   dans l'application.

## 4. Architecture cible des connecteurs (quand un contrat opérateur existera)

Le socle est préparé sans activer quoi que ce soit :

- **Configuration par dossier** — `financial_accounts.operator`
  (`ORANGE_MONEY_GN`, `MTN_MOMO_GN`, …) porte déjà la normalisation des
  opérateurs ; les identifiants de connecteur, quand ils existeront, seront
  stockés chiffrés (clés Fernet de `KORA_ENCRYPTION_KEYS`), jamais en clair
  ni dans les exports.
- **Trois modes de synchronisation**, du plus simple au plus direct :
  1. `IMPORT` — fichier déposé par l'utilisateur (implémenté, cf. §3) ;
  2. `PULL` — interrogation périodique de l'API opérateur (cible) ;
  3. `WEBHOOK` — notification opérateur entrante, exigeant signature
     partagée et point d'entrée dédié (cible, jamais sans contrat).
- **Déduplication** — quel que soit le mode, la clé de déduplication reste
  l'identifiant de transaction opérateur (référence de ligne) complété par
  l'empreinte métier ; l'API externe n'a jamais le droit de créer un
  mouvement comptable.
- **Frais** — toute commission opérateur devient une ligne distincte
  `[FRAIS]`, rapprochée et comptabilisée comme les frais bancaires actuels
  (Saisie guidée → nature « Frais bancaires » / « commissions »).
- **Suivi d'erreurs** — une ligne illisible est refusée avec un message
  exploitable (jamais interprétée à l'aveugle) ; le fichier original chiffré
  permet toujours de repartir de la source. Un journal d'erreurs de
  synchronisation dédié sera ajouté avec le premier connecteur `PULL`.
- **Aucun posting automatique** — les lignes importées restent
  `PENDING` jusqu'à un rapprochement confirmé par un humain ; une API
  opérateur ne produirait jamais d'écriture directe.

## 5. Prochaines étapes du chantier 3D

1. Adaptateur **Excel** (.xlsx) sur le même contrat de lecture
   (openpyxl déjà présent pour les exports) ;
2. Recollement du parseur CSV sur un **export réel** dès qu'un opérateur
   en fournit un (les colonnes cibles resteront ajustables sans rupture) ;
3. Journal de suivi des erreurs de synchronisation (avec le premier
   connecteur `PULL`) ;
4. Connecteurs API — **uniquement** après signature d'un contrat marchand et
   validation du périmètre par le porteur du projet.
