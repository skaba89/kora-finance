# Données fictives pour tester Kora en local

Ce guide décrit le jeu de données de démonstration « **Djouma Distribution SARL** » :
une PME commerciale fictive de Conakry (Guinée, GNF), sept mois d'activité réalistes
(avril → novembre 2026), trois comptes financiers et trois relevés bancaires fictifs
à importer. Toutes les données sont inventées — les noms d'entreprises, RCCM et NIF
ne correspondent à aucune entité réelle.

## 1. Créer la démonstration

Une fois la pile démarrée (`make up`), le dossier est créé par le script de seed,
qui passe par les mêmes services que l'application (aucune écriture directe en base) :

```bash
docker compose exec api python -m kora.scripts.seed_demo
```

Le script crée :

- trois comptes utilisateurs (mot de passe commun `KoraDemo2026!`) :
  - `directeur@demo.kora.gn` — Fatoumata Diallo — **PME_DIRIGEANT** (créateur du dossier)
  - `comptable@demo.kora.gn` — Mamadou Sylla — **PME_COMPTABLE**
  - `lecteur@demo.kora.gn` — Aïssatou Baldé — **PME_LECTEUR**
- le dossier « Djouma Distribution SARL » (SARL, GNF, exercice 2026), avec plan
  SYSCOHADA préchargé, taxes (TVA 18 %) et journaux par défaut ;
- des sous-comptes de tiers (4111-4114 clients, 4011-4013 fournisseurs) et de
  trésorerie (5211 banque, 5212 Orange Money) ;
- trois comptes financiers : **Banque Fouta Express**, **Caisse du siège**,
  **Orange Money — Boutique** ;
- 74 écritures validées + 1 brouillon, dont 36 mouvements de trésorerie ;
- un lettrage automatique des factures entièrement réglées ;
- trois **relevés bancaires fictifs** dans le dossier courant (`./demo` dans le
  conteneur) : `releve-banque-fouta-2026-10.csv`, `releve-banque-fouta-2026-11.ofx`
  et `releve-orange-money-2026-10-11.csv`.

Ouvrir l'application sur http://localhost:3100 et se connecter avec l'un des comptes.

## 2. Scénario de test conseillé ( parcours complet )

1. **Tableau de bord** : l'instantané des rapports et le résultat s'affichent avec
   sept mois d'historique.
2. **Saisie guidée** : enregistrer une vente, un achat, une facture client — les
   comptes clients/fournisseurs de la démonstration sont proposés.
3. **Écriture en brouillon** : la « caution eau-électricité » (1 500 000 GNF, OD)
   attend une validation depuis l'écran Écritures.
4. **Lettrage** : les comptes clients/fournisseurs montrent des factures lettrées
   (règlement complet) et non lettrées (règlements partiels — exemple : FAC-2026-003).
5. **Import de relevé (3B)** : Trésorerie → compte Banque Fouta Express →
   « Importer un relevé » → charger `releve-banque-fouta-2026-10.csv`, puis
   `releve-banque-fouta-2026-11.ofx` (format OFX) et le relevé Orange Money (CSV).
   Le double import du même fichier est refusé (déduplication).
6. **Rapprochement assisté (3C)** : ouvrir le rapprochement du compte — chaque
   opération connue reçoit un candidat proposé, classé par score ; la confirmation
   est **toujours manuelle**. Cinq opérations « surprises » n'ont aucun candidat :
   - *AGIOS ET COMMISSIONS TRIMESTRE* (−182 500 GNF) et *COMMISSION DOSSIER
     RECOUVREMENT* (−145 000 GNF) et *COMMISSION DEPOT AGENT KOULOUBA* (−12 000 GNF) :
     frais non comptabilisés → les enregistrer (Saisie guidée → Dépense payée,
     nature « Frais bancaires »), puis recharger le rapprochement ;
   - *REMISE CHEQUE 000341* (+9 800 000 GNF) : encaissement inconnu → enregistrer un
     dépôt (contrepartie client Sahel Agro), puis rapprocher ;
   - *FRAIS ALERTE SMS* (−25 000 GNF) : ligne à **ignorer** (bouton Ignorer).
7. **Rapports et états financiers** : bilan, résultat, TFT ; exports XLSX/PDF/TFT.
8. **Hors connexion** : saisir une écriture déconnecté puis la resynchroniser.

## 3. Repartir de zéro (réinitialisation)

Le `--reset` supprime le dossier et ses utilisateurs puis les recrée à l'identique.
Le grand livre étant en ajout seul (déclencheurs d'immuabilité), la suppression en
cascade exige les droits du propriétaire du schéma — le conteneur `api` ne les porte
pas volontairement (séparation des rôles runtime/DDL). Passer l'URL de migration :

```bash
docker compose exec -e KORA_DATABASE_MIGRATION_URL="postgresql+psycopg://kora_owner:${KORA_DB_OWNER_PASSWORD}@postgres:5432/kora" api python -m kora.scripts.seed_demo --reset
```

(Valeurs de `KORA_DB_OWNER_PASSWORD` dans le `.env` créé par `make env`.)

## 4. Détails techniques

- Le script vit dans `apps/api/src/kora/scripts/seed_demo.py` ; il fonctionne aussi
  hors Docker (`uv run python -m kora.scripts.seed_demo` avec `KORA_DATABASE_URL`).
- `--out DIR` choisit le dossier des relevés générés (défaut : `./demo`).
- Les montants sont en GNF (unité entière) ; la TVA 18 % est appliquée sur les
  montants TTC multiples de 590 000 GNF pour des scissions HT/TVA exactes.
- Les relevés sont construits **depuis les mouvements réellement créés** : le
  rapprochement retrouve toujours les opérations comptabilisées, et les cinq
  anomalies injectées sont garanties sans candidat.
