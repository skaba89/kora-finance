# Arbitrage comptable — KF-15 et KF-16

Date : 2026-11-11 · Rédigé dans le cadre du suivi d'audit (`AUDIT_SUIVI_20261109.md`
§15/§16, items KF-15 et KF-16). Ce document fixe les décisions de présentation et de
calcul retenues pour Kora Finance, avec leur justification et leurs limites. Conformément
à la règle du dépôt (`CLAUDE.md` §3), toute donnée fiscale chiffrée reste paramétrable,
datée et marquée « à vérifier auprès de la DGI » ; ce mémoire ne code aucun taux en dur
et ne remplace pas la revue finale d'un expert-comptable inscrit à l'ONECCA Guinée.

## 1. KF-15 — Tableau des flux de trésorerie (TFT)

### 1.1 Décision

Le TFT est implémenté en **méthode directe** : les flux sont mesurés comme les
mouvements réels des comptes de trésorerie (classe 5), classés d'après la contrepartie
de chaque écriture. La présentation retient la structure du TFT du SYSCOHADA révisé
(AUDCIF, art. 21-23 ; Guide d'application du SYSCOHADA révisé, chap. « Tableau des flux
de trésorerie ») : trois grandes fonctions — **opérationnelle**, **d'investissement**,
**de financement** — encadrées par la trésorerie nette d'ouverture et de clôture.

**Pourquoi la méthode directe** : les données sources de Kora sont des écritures en
partie double validées ; le flux réel (mouvement de trésorerie + contrepartie) y est
directement disponible, sans reconstitution par variation de postes. La méthode directe
est aussi celle qui parle aux dirigeants de PME et aux banquiers (Kora vise des dossiers
de financement, phase 6). La méthode indirecte (CRA à partir du résultat) pourra être
ajoutée plus tard comme lecture alternative ; elle n'est pas jugée nécessaire pour
l'arbitrage.

**Pourquoi cette construction** : elle évite d'inventer des soldes intermédiaires.
Chaque montant du tableau est la somme de mouvements réels ; le tableau se contrôle
lui-même (trésorerie de clôture = solde réel des comptes de classe 5 à la date de
coupure). Toute divergence est signalée (`coherent = false`), jamais masquée.

### 1.2 Définition de la trésorerie

Trésorerie = **tous les comptes de classe 5** (50 titres de placement, 51 valeurs à
encaisser, 52 banques, 53 établissements financiers, 54/55 instruments de monnaie
électronique, 56 crédits de trésorerie, 57 caisses, 58 régularisations), cohérent avec
la définition du bilan (lignes BQ/BS côté actif, DQ/DR côté passif, voir
`etats_affectations_2017.csv`). Les virements internes (contrepartie elle-même en
classe 5) ne génèrent aucun flux. Le mouvement net d'un compte créditeur (56/52 au
crédit) réduit la trésorerie nette, symétriquement au bilan.

### 1.3 Règles de calcul

1. Seules les écritures **validées** entrent dans le calcul (convention commune à tous
   les états de Kora) ;
2. Le flux d'une écriture = mouvement net des lignes de classe 5, réparti entre les
   lignes du TFT d'après la **contrepartie** (chaque ligne non trésorerie contribue
   pour son propre montant, inversé) ; une écriture à contreparties multiples
   (ex. remboursement d'emprunt + intérêts payés en une seule écriture) est donc
   ventilée ligne par ligne ;
3. La contrepartie est classée par un référentiel d'affectations par préfixe
   (`tft_affectations_2017.csv`, préfixe le plus long, un poste par sens débit/crédit) ;
4. **Trésorerie d'ouverture** = mouvements des écritures d'origine `CLOSING`
   (à-nouveaux et leurs contre-passations) datées du premier jour de l'exercice —
   même convention que le bilan, qui ne voit que l'exercice en cours ;
5. **Trésorerie de clôture** = ouverture + variation ; un contrôle indépendant
   recalcule le solde réel de la classe 5 à la date de coupure et compare ;
6. Tout compte de contrepartie sans affectation est signalé (`unmapped_accounts`),
   jamais ignoré.

### 1.4 Lignes et choix de classement

Les codes de ligne (OA…OH, IA…IE, FA…FE, XA/XB/XC/XV) sont des codes propres à Kora ;
les libellés suivent la nomenclature du SYSCOHADA révisé. Choux notables :

| Objet | Classement retenu | Justification |
|---|---|---|
| Ventes encaissées (70x, clients 41x, avances 419/477) | Opérationnel, « Ventes de biens et services encaissées » | Les encaissements sur créances clients sont des flux d'activité ; les avances reçues sont des ventes à venir |
| Subventions d'exploitation (71x) | Opérationnel, ligne dédiée | Rémunération de l'activité ordinaire |
| Achats payés (60x-63x, 401/402/408/409, stocks 3x, prépayés 476) | Opérationnel, « Fournisseurs de stocks et services décaissés » | Achat comptant et règlement fournisseur sont la même réalité économique |
| Personnel et organismes sociaux (42x, 43x, 66x) | Opérationnel, ligne dédiée | — |
| Impôts et taxes (44x, 64x, 88x, 89x) | Opérationnel, « Impôts, taxes et assimilés décaissés » | Convention dominante ; la TVA payée à l'État y figure via 44x |
| **Charges financières payées (67x, 631)** | **Opérationnel**, ligne dédiée | Les intérêts et frais bancaires restent dans les flux d'activité (convention retenue ; des sources de pratique OHADA les maintiennent dans les flux opérationnels — à confirmer en revue finale) |
| Cessions d'immobilisations (754, 414/485, 721/722...) | Investissement, « Cessions » | — |
| Acquisitions d'immobilisations (21x-27x, 25x avances, 404/481/482, 26x) | Investissement, « Acquisitions » par nature (incorporelles, corporelles, financières) | 404 « acquisitions courantes d'immobilisations » suit les immobilisations, pas les fournisseurs d'exploitation |
| Capital et primes (101, 104-106, 461/467) | Financement, « Capital et primes émis encaissés » | — |
| Dividendes et prélèvements (465, 109, 12x en débit) | Financement, « Dividendes versés » | Convention confirmée par les références de présentation OHADA |
| Emprunts et dettes financières (16x, 17x, 462/463/466) | Financement, encaissements et remboursements séparés (sens débit/crédit) | Le remboursement du principal n'est pas une charge ; la ventilation brute reste lisible |
| Subventions d'investissement (14x) | Financement, ligne dédiée | Ressource de financement |
| Dons et produits HAO (84x, 845) | Opérationnel, « Autres encaissements » | Flux réels non liés à l'ordinaire, mais non finançants |
| Comptes de contrepartie aberrants (reprises 78x/79x, dotations 68x/69x, provisions 19x, dépréciations 49x) | « Autres décaissements / encaissements » | Une écriture de trésorerie qui touche ces comptes est suspecte : elle reste visible dans « autres » au lieu d'être ignorée — et peut être corrigée |

### 1.5 Limites assumées et points à confirmer

- Le classement des **charges financières payées** (opérationnel) et la ventilation
  **encaissements/remboursements** des emprunts sont à confirmer par la revue finale ;
- Les **écarts de conversion** (478/479) et les gains/pertes de change sont classés
  « autres » ; une traduction détaillée de l'effet de change sur la trésorerie est du
  travail futur, sans objet tant que le multi-devises n'est pas livré ;
- Les **titres de placement** (50x) font partie de la trésorerie : leur achat/cession
  via un compte intermédiaire (472) apparaît en investissement financier ; un usage
  avancé pourra les exclure de la trésorerie nette ;
- L'**export PDF/Excel du TFT** n'est pas livré dans ce lot (la page web et l'API le
  sont) ; il suivra le même chemin que les exports des autres états ;
- Le jeu d'affectations est versionné (`SYSCOHADA_REVISE_2017_TFT_V1`) : toute
  correction est un changement visible au diff, testé par le banc de référence.

## 2. KF-15 — Notes annexes

Décision : livrées **progressivement** à partir de la phase 3, car leurs rubriques
dépendent d'un périmètre qui n'existe pas encore (immobilisations détaillées, emprunts,
engagements, parties liées). Le socle retenu (ordre de livraison) :

1. **Note « principes comptables et méthodes »** — générée depuis les choix du dépôt
   (partie double, immuabilité, référentiels versionnés) ;
2. **Tableau des immobilisations, amortissements et dépréciations** — dérivé du grand
   livre (classes 2/28/29), dès la phase 3 ;
3. **Détail des tiers et échéancier** — dès que le rapprochement (phase 3) existe ;
4. **Engagements hors bilan et parties liées** — saisie dédiée, phase 4+.

Chaque note sera pilotée par référentiel versionné, comme le bilan et le compte de
résultat, et soumise au même banc de tests.

## 3. KF-16 — Règles fiscales et d'exercice

Décisions opérationnelles (le taux n'est jamais codé en dur ; voir `CLAUDE.md` §3) :

| Objet | Décision | Statut |
|---|---|---|
| **Exercice comptable** | 12 mois au plus, chevauchement interdit, clôture/réouverture avec à-nouveaux — déjà implémenté (phase 2d) et conforme à la pratique OHADA ; l'alignement sur l'année civile est proposé par défaut mais non imposé | Implémenté |
| **TVA** | Taux paramétrables par dossier, datés, marqués « à vérifier auprès de la DGI » (phase 1e) ; la saisie guidée calcule le TTC avec taux du dossier à la date | Implémenté |
| **Impôt sur les résultats / IMF** | Comptes 891/895 préchargés ; aucune simulation fiscale automatique : Kora ne calcule pas d'impôt, il enregistre les écritures constatées | Décision maintenue |
| **Mentions obligatoires des factures** | Livrées avec le module ventes/achats (phase 4) : NIU/NCC, raison sociale, adresse, montant HT/TVA/TTC en GNF, référence de l'exercice — libellés paramétrables, à vérifier auprès de la DGI | Planifié phase 4 |
| **Conservation des documents** | Les pièces justificatives sont conservées dans le stockage chiffré, jamais supprimées une fois l'écriture validée (phase 2g) ; la durée légale (10 ans sous réserve de vérification du texte applicable) sera affichée dans les notes annexes | Implémenté + à confirmer |

**Résultat de l'arbitrage** : KF-16 ne bloque plus la mise en production tant que
(1) aucun taux n'est codé en dur, (2) les mentions fiscales manquantes sont portées par
la phase 4 et non par un module factice, (3) la revue finale d'un expert inscrit à
l'ONECCA reste au chemin critique de la première clôture certifiée.
