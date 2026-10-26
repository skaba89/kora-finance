# Audit comptabilité — Kora Finance

Date : 26 octobre 2026 — dépôt privé `skaba89/kora-finance`

Référence figée : `7a51c45258301e8cfc50a0305ce023e08d286202` (`main` au début de l'audit). Les constats visent ce commit, pas l'état réel d'un VPS. Aucun accès aux données de production, aucune migration ni aucun déploiement effectués.

## Conclusion

Le moteur de partie double est réellement développé. Les tests fournis démontrent de nombreux calculs et invariants ; ils ne valent pas validation réglementaire indépendante. Ne pas présenter les exports comme des comptes certifiés ou comme un dossier complet SYSCOHADA prêt à dépôt.

Le cadre de référence est l'AUDCIF adopté le 26 janvier 2017 et le SYSCOHADA révisé. Références primaires consultées : https://www.ohada.org/en/uniform-act-relating-to-accounting-law-and-financial-information-audcif/ et Journal officiel diffusé par le ministère sénégalais de la Justice : https://justice.sec.gouv.sn/wp-content/uploads/textes-reglements/OHADA/Acte-uniforme-relatif-droit-comptable-information-financiere-JAN-2017-JO.pdf . La fiscalité guinéenne 2026 n'a pas été validée auprès de la DGI : aucun taux n'est déclaré réglementairement confirmé dans cet audit.

## Exigences : code vérifié et validation professionnelle

| Domaine | Preuve technique | Limite et validation requise |
|---|---|---|
| Partie double | Sommes int, contrôles Python, CHECK et triggers, Hypothesis | KF-01 : chemin UPDATE de rattachement ; concurrence SQL non complètement couverte |
| Unité monétaire GNF | BIGINT/int, chaînes API, BigInt web, GNF sans décimales | Référentiel de devises cohérent à imposer (KF-19) ; pas de multi-devises avec gains/pertes de change |
| Journaux / numérotation | Séquence par journal/exercice sous FOR UPDATE, unicité, test de 20 posts concurrents | Numéro d'ordre d'enregistrement distinct de date de pièce : chronologie des saisies rétrodatées à faire valider par expert |
| Immuabilité et correction | POSTED protégé, contre-passation liée et unique | KF-01 ; suppression et transformation indirecte des référentiels à couvrir en SQL direct |
| Périodes / exercices | Exclusion GiST empêche chevauchement ; verrouillage et statut CLOSED | Règles civiles et exceptions de premier exercice non modélisées complètement (KF-16) |
| Clôture | Classes 1–5 reportées, résultat classes 6–8 en 131/139, à-nouveaux datés en N+1, réouverture par contre-passation | Faire signer comptes de résultat, affectation, clôtures successives, reprise de soldes par tiers et conditions de réouverture ; limite de 499 comptes de bilan environ dans une seule écriture |
| Plan SYSCOHADA | 520 comptes préchargés et version de référence, sous-comptes rattachés | Source détaillée/exhaustivité/libellés et règles d'imputation à approuver par expert indépendant |
| TVA | Taux datés sans chevauchement, points de base, arrondi entier et complément exact TTC-HT | split_vat calcule HT arrondi puis TVA par différence ; convention d'arrondi et déductibilité à valider. Un avertissement « non vérifié » n'établit pas la légalité du taux |
| Lettrage | Lignes validées de tiers, contrôle d'équilibre et unicité, délettrage tracé | Rapprochements bancaires/opérateurs et balance âgée non implémentés |
| Balance / grand livre | Calcul SQL, fonctions fenêtre, pagination, ouverture et à-nouveaux | KF-05 : cohérence de snapshot à prouver sous activité concurrente |
| États annuels | Bilan et résultat, comparaison N/N-1 et comptes non affectés signalés | Jeu complet absent : flux et notes ; affectations et présentation non signées (KF-15) |
| Pièces et traçabilité | Chiffrement, empreinte, attachement aux écritures, retrait interdit après validation ; audit transactionnel | Conservation opérationnelle, restitution et ancrage indépendant non prouvés ; sauvegarde de 30 jours ne définit pas la conservation des livres et justificatifs |
| Factures commerciales | Aucune génération légale identifiée | « FACTURE_CLIENT » dans saisie guidée ne fournit pas numérotation commerciale, mentions, avoirs ou envoi |

Les tests de clôture calculent un bénéfice attendu sur les mêmes règles que le moteur. Pour valider le référentiel, un expert doit fournir des résultats indépendants ; recopier les formules du code dans les tests serait une preuve circulaire.

## Anomalies

### KF-01 — Le trigger des lignes ne contrôle pas le parent de destination

- **Priorité / gravité :** P0 / Critique.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/alembic/versions/20261024_0005_comptabilite_generale.py:304`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/alembic/versions/20261024_0005_comptabilite_generale.py#L304).
- **Preuve technique :** Sur UPDATE, kora_ledger_protect_line ne consulte que OLD.entry_id. Une ligne d'un brouillon peut être réaffectée vers une écriture POSTED du même tenant, avec un line_no libre. La FK composite vérifie le tenant, pas le statut. Le trigger de l'en-tête ne s'exécute pas lors de cet UPDATE de ligne. Aucune migration ultérieure ne remplace ce trigger.
- **Impact :** Contournement de l'immuabilité et de l'équilibre par un chemin SQL disposant des droits DML. Aucun endpoint HTTP de déplacement de ligne n'a été identifié : ce constat ne prouve ni une injection SQL ni une exploitation à distance.
- **Solution :** Nouvelle migration 0009 : vérifier OLD et NEW parents, interdire le changement de parent ou verrouiller les deux parents dans un ordre stable, imposer le statut DRAFT. Couvrir aussi les mutations SQL concurrentes et vérifier l'équilibre à la validation.
- **Test de validation :** Créer une écriture validée et un brouillon ; tenter UPDATE journal_lines SET entry_id=:posted,line_no=3 WHERE id=:draft_line avec kora_app puis kora_owner. Attendre un refus, aucun changement des totaux. Reproduire sur PostgreSQL 16 isolé ; reproduction dynamique non effectuée ici.

### KF-03 — Clôture et modifications concurrentes : preuve complémentaire indispensable

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Risque identifié ; exploitation non reproduite.
- **Fichier :** [`apps/api/src/kora/accounting/closing.py:219`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/accounting/closing.py#L219).
- **Preuve technique :** close verrouille l'exercice FOR UPDATE ; entries._fiscal_year_for fait une lecture simple. Le trigger 0007 lit l'état de l'exercice sans verrou explicite. La suite teste les validations simultanées, mais pas l'interleaving création/validation/clôture. Les verrous implicites des FK doivent être pris en compte : leur présence empêche de conclure à une corruption certaine par simple lecture.
- **Impact :** Risque résiduel de course ou d'attente/deadlock autour de la clôture ; intégrité des à-nouveaux non prouvée dans ces scénarios.
- **Solution :** Écrire d'abord des tests déterministes à deux connexions et barrières. Définir un protocole commun de verrouillage par exercice si les tests révèlent une course ; prévoir les reprises après deadlock.
- **Test de validation :** Tester insert bloqué par FK, post existant, verrouillage de période, clôture de N et N+1 en parallèle, puis comparer soldes et à-nouveaux. Chaque mutation doit soit précéder la clôture, soit être rejetée proprement.

### KF-05 — Les lectures multi-requêtes ne fixent pas de snapshot comptable

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Risque de concurrence étayé par le code.
- **Fichier :** [`apps/api/src/kora/accounting/reports.py:193`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/accounting/reports.py#L193).
- **Preuve technique :** account_ledger calcule d'abord ouverture/totaux puis lit les lignes ; full_ledger appelle trial_balance puis une seconde requête. get_engine ne fixe aucune isolation spécifique : PostgreSQL utilise normalement READ COMMITTED. Les états N et N-1 sont aussi calculés séparément.
- **Impact :** Sous écritures concurrentes, un même export ou écran peut mélanger deux instants et afficher totaux, solde progressif et lignes incohérents. Ce scénario n'a pas été reproduit dans cet environnement.
- **Solution :** Produire le rapport sous snapshot cohérent (transaction REPEATABLE READ dédiée, ou requête unifiée). Gérer séparément l'audit d'export et les reprises transactionnelles.
- **Test de validation :** Insérer/valider une écriture entre les deux requêtes à l'aide d'une barrière ; vérifier que totaux, détails et soldes reflètent tous le même instant.

### KF-15 — Jeu d'états SYSCOHADA incomplet

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/exports/builders.py:229`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/exports/builders.py#L229).
- **Preuve technique :** financial_statements produit Bilan Actif, Bilan Passif et Compte de résultat. Le template CSV ne comporte que ACTIF/PASSIF/RESULTAT ; aucune implémentation du tableau des flux ou des notes annexes n'a été trouvée dans les routes/services/modèles.
- **Impact :** Le produit ne doit pas être vendu comme générateur du jeu complet d'états annuels du système normal. La conformité du mapping présent n'est pas certifiée par les tests de calcul.
- **Solution :** Compléter flux et notes, cadrer système normal/SMT et faire approuver le référentiel versionné par un expert-comptable guinéen ; étiqueter les exports actuels selon leur portée.
- **Test de validation :** Jeux de comptes de référence indépendants, bilan/résultat/flux/notes rapprochés et signés par l'expert ; tests de non-régression sur chaque affectation.

### KF-16 — Règles fiscales et exercices nécessitent un arbitrage métier

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Validation réglementaire externe nécessaire.
- **Fichier :** [`apps/api/src/kora/organization/service.py:340`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/organization/service.py#L340).
- **Preuve technique :** Le code accepte les exercices jusqu'à 24 mois sans distinguer premier exercice et suivant. fiscal_defaults_gn.py propose des valeurs à confirmer ; guided._vat autorise un taux non vérifié en ajoutant un avertissement. La saisie d'un nouveau taux marque verified_at automatiquement.
- **Impact :** Une configuration techniquement valide peut être inadaptée au régime réel de la PME. Aucun justificatif DGI ni approbation d'expert n'a été fourni à l'audit.
- **Solution :** Distinguer validation utilisateur et validation fiscale documentée ; règles d'exercice par contexte ; versionner source, période et approbateur des taxes. Définir avec l'expert quand un avertissement doit devenir bloquant.
- **Test de validation :** Scénarios régime TVA/non-assujetti, changement de taux et premiers exercices ; approbation écrite de la politique par expert guinéen puis tests datés.

### KF-19 — L'API accepte des devises non prises en charge par les exports

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/api/v1/companies.py:64`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/api/v1/companies.py#L64).
- **Preuve technique :** CompanyCreate accepte toute chaîne de trois majuscules. exports.document.currency_decimals accepte seulement GNF/XOF/XAF/EUR/USD. La devise n'est ensuite plus modifiable par update_company.
- **Impact :** Un dossier créé par API avec une autre devise peut fonctionner partiellement mais échouer à l'export et nécessiter une réparation administrée.
- **Solution :** Référentiel partagé des devises supportées, validation à la création et tests de contrat frontend/backend ; définir une migration pour les dossiers déjà concernés.
- **Test de validation :** Créer JPY et ZZZ via API : refus clair si hors périmètre ; toutes les devises autorisées doivent être saisissables, affichables et exportables avec les mêmes décimales.


## Recette comptable indépendante à faire signer

Constituer au minimum trois dossiers anonymisés/synthétiques : commerce avec stocks, services avec TVA, petite activité non assujettie selon régime confirmé. Pour chaque dossier : ouverture, ventes/achats, avoirs et règlements partiels (saisie manuelle si module absent), caisse/banque/Mobile Money, frais, immobilisations/amortissements, provisions, régularisations, clôture, réouverture contrôlée et N+1. Inclure profit, perte, solde nul, comptes débiteurs inhabituels et soldes créditeurs d'actifs.

L'expert valide séparément : plan des comptes ; chaque affectation de bilan/résultat ; signe et règle des amortissements/dépréciations ; calcul et report du résultat ; TVA et exemptions guinéennes applicables ; présentation des comparatifs ; flux et notes ; règles d'exercice et de conservation ; portée des mentions commerciales. Livrer un procès-verbal daté et des états attendus versionnés dans les tests. L'application doit conserver les pièces et rendre les contrôles reproductibles sans prétendre remplacer la responsabilité professionnelle.
