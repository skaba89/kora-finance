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
9. **Prévision de trésorerie (3E)** : menu du dossier → « Prévision de trésorerie » —
   projection 30/60/90 jours sur les sept mois d'historique du seed : soldes observés,
   flux engagés (écritures validées datées dans le futur) et flux estimés ; changer
   l'horizon et le scénario via les liens, lire « Comment ce chiffre est calculé »
   (coefficients du scénario, périmètre 5xx hors 58x, brouillons futurs exclus),
   puis exporter en PDF et Excel (chaque export est inscrit au journal d'audit).
   **Tension de trésorerie prévue par le scénario** : le chèque postdaté remis à
   Mamaya Import-Export (réassort trimestriel, 195 000 000 GNF, encaissé le
   3 décembre) fait plonger la prévision sous zéro — statut **CRITIQUE**,
   première date critique = 3 décembre, point bas ≈ −6 900 000 GNF. La séance
   démontre la lecture de la tension et les leviers (encaisser FAC-F-2026-052,
   reporter ou échelonner le chèque). Flux engagés fournis : chèque postdaté
   reçu de Sahel Agro +12 500 000 GNF à +10 j ; brouillon de règlement Soleil
   Élec à +25 j (visible dans « Brouillons futurs exclus ») ; facture fournisseur
   à régler FAC-F-2026-052 (14 750 000 GNF, non lettrée).
10. **Seuils d'alerte (3E)** : sur l'écran Prévision (rôle dirigeant), bouton
    « Seuils d'alerte » → régler le seuil critique (ex. 10 000 000 GNF) et le
    seuil de surveillance (ex. 25 000 000 GNF), l'horizon et le scénario par
    défaut → « Enregistrer » : les statuts des journées et le badge global se
    recalculent immédiatement (le lecteur voit les seuils sans pouvoir les
    modifier).
11. **Instantanés figés (3E)** : bouton « Figer cette prévision » (rôle
    dirigeant, inscrit au journal d'audit) → l'instantané apparaît dans
    « Instantanés figés » → « Comparer au réalisé » ouvre le détail : en-tête
    figé (statut, solde initial, point bas, première date critique) puis la
    comparaison jour à jour prévisionnel / réalisé / écart, les totaux et les
    écarts les plus marquants dès que des écritures validées suivent le
    figeage.

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
- `--out DIR` choisit le dossier des relevés générés (défaut : `./demo`). Si le
  répertoire demandé n'est pas inscriptible — cas du conteneur durci (`/app` en
  lecture seule, utilisateur non-root), ex. `--out demo` → `PermissionError` —
  le script bascule automatiquement sur `/tmp/kora-demo` et affiche la commande
  `docker compose cp` à exécuter sur l'hôte ; si même le repli échoue, l'erreur
  remonte (aucune perte silencieuse).
- Les montants sont en GNF (unité entière) ; la TVA 18 % est appliquée sur les
  montants TTC multiples de 590 000 GNF pour des scissions HT/TVA exactes.
- Les relevés sont construits **depuis les mouvements réellement créés** : le
  rapprochement retrouve toujours les opérations comptabilisées, et les cinq
  anomalies injectées sont garanties sans candidat.

## 5. Démarrage Windows (Git Bash)

Commandes **exécutées et validées** le 12/11/2026 sur Windows 11 + Git Bash
(Git for Windows) + Docker Desktop (backend WSL 2). Cibles : Windows 10/11.

### 5.1 Différences Windows ↔ Ubuntu

| Besoin | Ubuntu / macOS | Windows Git Bash |
|---|---|---|
| Orchestration | `make up`, `make migrate`, … | `make` fonctionne si **GNU Make est installé** (§5.2) ; sinon exécuter les cibles à la main (§5.3) |
| Chemins Docker (volumes, montages) | `/home/…` | Toujours préfixer `MSYS_NO_PATHCONV=1` : sinon Git Bash réécrit `/app/…` en `C:/Program Files/Git/app/…` |
| `docker compose exec` interactif | `docker compose exec api sh` | Ajouter **`-T`** : `docker compose exec -T api sh` (sinon « the input device is not a TTY ») |
| Sortie de fichiers du conteneur | `--out` direct | Le conteneur API est **durci** (utilisateur non-root `kora`, `/app` en lecture seule) : écrire dans `/tmp` du conteneur puis `docker compose cp` (§5.3) |
| Fin de ligne | LF natif | Cloner avec `core.autocrlf=false` ; `.gitattributes` normalise le dépôt (PR repo-hygiene) |
| Docker Desktop | démon natif | Vérifier « WSL 2 backend » actif (Settings → General) |

### 5.2 Installation de GNU Make (une fois)

```bash
winget install --id GnuWin32.Make -e
# ou : winget install ezwinports.make
make --version   # attendu : GNU Make 4.4.1
```

Si `make` reste introuvable dans le Git Bash courant : fermer et rouvrir le
terminal (mise à jour du PATH).

### 5.3 Démarrage complet sans Make (équivalence des cibles)

```bash
# 1. Environnement local (génère .env avec des secrets réels, à la racine)
./scripts/init-env.sh

# 2. Construire et démarrer la pile
docker compose up -d --build

# 3. Attendre la santé des conteneurs
docker compose ps                          # tous les services « healthy »
docker compose logs -f api                 # Ctrl+C pour sortir

# 4. Migrations
MSYS_NO_PATHCONV=1 docker compose exec -T api alembic upgrade head

# 5. Jeu de démonstration Djouma Distribution SARL (conteneur → /tmp, puis copie)
MSYS_NO_PATHCONV=1 docker compose exec -T api \
  python -m kora.scripts.seed_demo --out /tmp/demo
mkdir -p ./demo-export
docker compose cp api:/tmp/demo/. ./demo-export/
```

> `--out demo` (chemin relatif) fonctionne désormais : le correctif
> `resolve_out_dir` rend le script tolérant — en cas de refus d'écriture il
> bascule automatiquement sur `/tmp/kora-demo` et affiche la commande
> `docker compose cp` à exécuter (§4). Le `--out /tmp/demo` explicite reste
> une option valide.

### 5.4 Diagnostic des pannes déjà rencontrées (résolues)

| Symptôme | Cause racine | Remède validé |
|---|---|---|
| `make: command not found` | Make absent de Git Bash | §5.2 (winget) puis rouvrir le terminal |
| `storage-1 exited (1)` + logs « kora_owner » échec d'authentification Postgres | `.env` périmé (fausses clés d'une ancienne exécution) **et** volume Postgres ancien avec mot de passe différent | `docker compose down -v` (⚠️ efface les données locales) puis re-exécuter `./scripts/init-env.sh` puis `docker compose up -d --build` |
| `PermissionError: '/app/demo'` au seed | `/app` en lecture seule (conteneur durci, utilisateur `kora` non-root) | corrigé : repli automatique sur `/tmp/kora-demo` + consigne `docker compose cp` (`resolve_out_dir`, §4) |
| `the input device is not a TTY` | Git Bash sans TTY compatible | ajouter `-T` à `docker compose exec` |
| `/app/...` transformé en `C:/Program Files/Git/app/...` | MSYS réécrit les chemins POSIX | préfixer `MSYS_NO_PATHCONV=1` |

### 5.5 Ubuntu — rappel des mêmes étapes

Les mêmes commandes fonctionnent sans les garde-fous Windows : pas besoin de
`MSYS_NO_PATHCONV=1`, `docker compose exec` garde son TTY, et le seed peut
écrire directement `--out ./demo`. En cas d'écriture refusée (installations
durcies), la même procédure `/tmp` + `docker compose cp` s'applique.

### 5.6 Vérification post-démarrage (les 3 rôles)

Une fois la pile saine et le seed chargé, le scénario du §2 est jouable :
connexion `directeur` / `comptable` / `lecteur` (mot de passe commun du jeu de
démo), vérifier en particulier :

1. les trois comptes voient le tableau de bord et les états financiers (lecture) ;
2. seuls `directeur` et `comptable` peuvent saisir une écriture et rapprocher ;
3. `lecteur` obtient un refus propre (pas d'erreur 500) sur toute action d'écriture.

### 5.7 Environnement de démonstration prospects (isolation)

- Ne **jamais** exécuter le seed sur une base contenant des données réelles ;
- La démonstration prospects se fait sur une pile locale (Docker, données
  fictives) ou sur un environnement de démo dédié explicitement identifié
  `DEMO=true` ;
- Les identifiants de démo ne quittent jamais ce périmètre (jamais en
  production) ;
- Réinitialisation : §3 ci-dessus (`--reset`).
