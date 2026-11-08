# Backlog priorisé et preuves de validation

Date : 26 octobre 2026 — dépôt privé `skaba89/kora-finance`

Référence figée : `7a51c45258301e8cfc50a0305ce023e08d286202` (`main` au début de l'audit). Les constats visent ce commit, pas l'état réel d'un VPS. Aucun accès aux données de production, aucune migration ni aucun déploiement effectués.

> **Suivi du 2026-11-09** : `AUDIT_SUIVI_20261109.md` vérifie les correctifs fusionnés
> depuis (KF-01, 02, 04, 06, 10, 17, 18 : corrigés), confirme les KF restants, ajoute
> 14 constats nouveaux (N-B1…N-I4) et met à jour le séquencement (§8 de ce document
> référentiel) après une exécution locale complète de la suite API (540/540).

## Conventions

P0 : bloque la validation production. P1 : à résoudre avant ouverture commerciale générale ou à borner formellement pour un pilote. P2 : amélioration/durcissement planifié. P3 : extension produit. La gravité décrit l'impact, la priorité le séquencement. Un risque non reproduit reste libellé ainsi ; une absence d'implémentation n'est pas présentée comme une vulnérabilité.

L'absence de PostgreSQL local interdit de déclarer les tests SQL proposés réussis. Les tests ajoutés appartiennent uniquement à la branche dédiée du correctif XLSX. Aucun changement de schéma ni donnée de production n'a été effectué.

## Tableau de suivi

| ID | Priorité | Gravité | Sujet | Responsable suggéré |
|---|---|---|---|---|
| KF-01 | P0 | Critique | Le trigger des lignes ne contrôle pas le parent de destination | Backend / PostgreSQL |
| KF-02 | P0 | Élevée | Le secret du propriétaire de schéma est transmis aux services applicatifs | DevSecOps |
| KF-03 | P1 | Élevée | Clôture et modifications concurrentes : preuve complémentaire indispensable | Backend / PostgreSQL |
| KF-04 | P1 | Élevée | Injection de formule dans les exports Excel | Backend / frontend / QA |
| KF-05 | P1 | Élevée | Les lectures multi-requêtes ne fixent pas de snapshot comptable | Backend / PostgreSQL |
| KF-06 | P1 | Élevée | Compteur de tentatives de connexion non atomique | Backend / PostgreSQL |
| KF-07 | P1 | Élevée | Dernier dirigeant : contrôle de cardinalité non sérialisé | Backend / PostgreSQL |
| KF-08 | P1 | Élevée | Activation MFA sans réauthentification récente | Backend / frontend / QA |
| KF-09 | P1 | Élevée | Sauvegardes et pièces partagent les droits de suppression | DevSecOps |
| KF-10 | P0 | Élevée | La reprise complète après perte du VPS n'est pas démontrée | DevSecOps |
| KF-11 | P1 | Élevée | Déploiement non versionné et sans sauvegarde préalable imposée | DevSecOps |
| KF-12 | P1 | Élevée | Supervision limitée aux healthchecks et logs locaux | DevSecOps |
| KF-13 | P1 | Élevée | Exports et stockage sans budget global de ressources | DevSecOps |
| KF-14 | P2 | Modérée | La CSP autorise les scripts inline | Backend / frontend / QA |
| KF-15 | P1 | Élevée | Jeu d'états SYSCOHADA incomplet | Expert comptable + backend |
| KF-16 | P1 | Élevée | Règles fiscales et exercices nécessitent un arbitrage métier | Expert comptable + backend |
| KF-17 | P2 | Modérée | La PWA ne sauvegarde pas les saisies hors connexion | Backend / frontend / QA |
| KF-18 | P2 | Faible | Le tableau de bord annonce encore la comptabilité à venir | Backend / frontend / QA |
| KF-19 | P2 | Modérée | L'API accepte des devises non prises en charge par les exports | Backend / frontend / QA |
| KF-20 | P2 | Modérée | Les audits de dépendances ne sont pas dans la CI | DevSecOps |
| KF-21 | P2 | Modérée | Accessibilité et expérience 3G : preuves insuffisantes | Backend / frontend / QA |
| KF-22 | P2 | Modérée | Mise en file après commit sans outbox durable | Backend / frontend / QA |
| KF-23 | P2 | Modérée | Sauvegarde chargée intégralement avant contrôle de taille | DevSecOps |

## Fiches détaillées

### KF-01 — Le trigger des lignes ne contrôle pas le parent de destination

- **Priorité / gravité :** P0 / Critique.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/alembic/versions/20261024_0005_comptabilite_generale.py:304`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/alembic/versions/20261024_0005_comptabilite_generale.py#L304).
- **Preuve technique :** Sur UPDATE, kora_ledger_protect_line ne consulte que OLD.entry_id. Une ligne d'un brouillon peut être réaffectée vers une écriture POSTED du même tenant, avec un line_no libre. La FK composite vérifie le tenant, pas le statut. Le trigger de l'en-tête ne s'exécute pas lors de cet UPDATE de ligne. Aucune migration ultérieure ne remplace ce trigger.
- **Impact :** Contournement de l'immuabilité et de l'équilibre par un chemin SQL disposant des droits DML. Aucun endpoint HTTP de déplacement de ligne n'a été identifié : ce constat ne prouve ni une injection SQL ni une exploitation à distance.
- **Solution :** Nouvelle migration 0009 : vérifier OLD et NEW parents, interdire le changement de parent ou verrouiller les deux parents dans un ordre stable, imposer le statut DRAFT. Couvrir aussi les mutations SQL concurrentes et vérifier l'équilibre à la validation.
- **Test de validation :** Créer une écriture validée et un brouillon ; tenter UPDATE journal_lines SET entry_id=:posted,line_no=3 WHERE id=:draft_line avec kora_app puis kora_owner. Attendre un refus, aucun changement des totaux. Reproduire sur PostgreSQL 16 isolé ; reproduction dynamique non effectuée ici.

### KF-02 — Le secret du propriétaire de schéma est transmis aux services applicatifs

- **Priorité / gravité :** P0 / Élevée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`deploy/vps/compose.yml:17`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/deploy/vps/compose.yml#L17).
- **Preuve technique :** x-api-env contient KORA_DATABASE_MIGRATION_URL avec le compte kora_owner ; migrate, api et worker réutilisent cet environnement aux lignes 80, 89 et 104. Settings exige aussi ce paramètre pour tout processus.
- **Impact :** Une compromission de l'API ou du worker donne accès aux identifiants permettant de modifier le schéma et ses protections. Le rôle utilisé normalement reste kora_app : aucune fuite inter-tenant HTTP démontrée.
- **Solution :** Séparer environnement runtime et migration ; retirer l'URL owner de l'API/worker ; configuration Alembic distincte, requise seulement lors des migrations. Conserver les secrets de sauvegarde hors runtime si possible.
- **Test de validation :** Analyser compose config sans publier les valeurs ; vérifier que seuls migrate et l'outil autorisé reçoivent le secret owner ; démarrer API/worker sans celui-ci et vérifier leurs tests et migrations.

### KF-03 — Clôture et modifications concurrentes : preuve complémentaire indispensable

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Risque identifié ; exploitation non reproduite.
- **Fichier :** [`apps/api/src/kora/accounting/closing.py:219`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/accounting/closing.py#L219).
- **Preuve technique :** close verrouille l'exercice FOR UPDATE ; entries._fiscal_year_for fait une lecture simple. Le trigger 0007 lit l'état de l'exercice sans verrou explicite. La suite teste les validations simultanées, mais pas l'interleaving création/validation/clôture. Les verrous implicites des FK doivent être pris en compte : leur présence empêche de conclure à une corruption certaine par simple lecture.
- **Impact :** Risque résiduel de course ou d'attente/deadlock autour de la clôture ; intégrité des à-nouveaux non prouvée dans ces scénarios.
- **Solution :** Écrire d'abord des tests déterministes à deux connexions et barrières. Définir un protocole commun de verrouillage par exercice si les tests révèlent une course ; prévoir les reprises après deadlock.
- **Test de validation :** Tester insert bloqué par FK, post existant, verrouillage de période, clôture de N et N+1 en parallèle, puis comparer soldes et à-nouveaux. Chaque mutation doit soit précéder la clôture, soit être rejetée proprement.

### KF-04 — Injection de formule dans les exports Excel

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Reproduit localement ; correctif testé, non fusionné.
- **Fichier :** [`apps/api/src/kora/exports/xlsx.py:37`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/exports/xlsx.py#L37).
- **Preuve technique :** sheet.append reçoit directement les textes métier. Le test test_xlsx_security.py fournit '=1+1' dans les métadonnées et le détail : huit cellules deviennent de type f au lieu de s. Test exécuté : échec avant correctif, succès après sérialisation littérale.
- **Impact :** Un texte comptable contrôlé par un utilisateur peut être interprété comme formule lors de l'ouverture du classeur. Le comportement des liens externes dépend d'Excel et de ses protections ; aucune exfiltration réelle n'a été tentée.
- **Solution :** Forcer le type chaîne des cellules textuelles pour tous les points d'écriture, y compris en-têtes et notes ; conserver les montants numériques. Correctif préparé sur branche séparée fix/audit-xlsx-literal-text.
- **Test de validation :** Ouvrir le XLSX avec openpyxl data_only=False ; zéro cellule f, textes conservés exactement et montant 1234567 de type n. Puis exécuter les exports d'intégration existants.

### KF-05 — Les lectures multi-requêtes ne fixent pas de snapshot comptable

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Risque de concurrence étayé par le code.
- **Fichier :** [`apps/api/src/kora/accounting/reports.py:193`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/accounting/reports.py#L193).
- **Preuve technique :** account_ledger calcule d'abord ouverture/totaux puis lit les lignes ; full_ledger appelle trial_balance puis une seconde requête. get_engine ne fixe aucune isolation spécifique : PostgreSQL utilise normalement READ COMMITTED. Les états N et N-1 sont aussi calculés séparément.
- **Impact :** Sous écritures concurrentes, un même export ou écran peut mélanger deux instants et afficher totaux, solde progressif et lignes incohérents. Ce scénario n'a pas été reproduit dans cet environnement.
- **Solution :** Produire le rapport sous snapshot cohérent (transaction REPEATABLE READ dédiée, ou requête unifiée). Gérer séparément l'audit d'export et les reprises transactionnelles.
- **Test de validation :** Insérer/valider une écriture entre les deux requêtes à l'aide d'une barrière ; vérifier que totaux, détails et soldes reflètent tous le même instant.

### KF-06 — Compteur de tentatives de connexion non atomique

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Risque de concurrence étayé par le code.
- **Fichier :** [`apps/api/src/kora/auth/service.py:129`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/auth/service.py#L129).
- **Preuve technique :** login lit l'utilisateur sans FOR UPDATE puis fait failed_login_count += 1. Deux sessions peuvent lire le même ancien compteur et enregistrer la même valeur. complete_login MFA, lui, verrouille l'utilisateur.
- **Impact :** Sous tentatives simultanées distribuées, le verrouillage par compte peut compter moins d'échecs que prévu ; la limite Redis par IP reste une protection complémentaire.
- **Solution :** Verrouiller l'utilisateur ou réaliser une mise à jour atomique avec retour de valeur ; appliquer un ordre de verrous cohérent avec audit et sessions.
- **Test de validation :** Envoyer N mots de passe faux avec connexions simultanées et IP distinctes sur base de test ; vérifier le seuil et Retry-After, sans perte d'incrément.

### KF-07 — Dernier dirigeant : contrôle de cardinalité non sérialisé

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Risque de concurrence étayé par le code.
- **Fichier :** [`apps/api/src/kora/organization/service.py:268`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/organization/service.py#L268).
- **Preuve technique :** Chaque retrait/rétrogradation verrouille sa propre CompanyMembership. _ensure_a_director_remains compte les dirigeants sans verrou commun à la société ; deux membres distincts peuvent tous deux voir deux dirigeants.
- **Impact :** Deux opérations autorisées simultanées peuvent laisser un dossier autonome sans dirigeant. La sérialisation ultérieure du journal d'audit ne rend pas rétroactivement atomique le comptage.
- **Solution :** Verrouiller la société avant de compter et de modifier les adhésions, dans un ordre uniforme ; conserver le contrôle métier et une preuve de concurrence.
- **Test de validation :** Deux dirigeants, deux connexions, chacun rétrograde ou retire un dirigeant différent : une seule opération doit réussir, au moins un dirigeant doit subsister.

### KF-08 — Activation MFA sans réauthentification récente

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/auth/mfa.py:101`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/auth/mfa.py#L101).
- **Preuve technique :** /auth/mfa/setup accepte CurrentUser seul ; start_setup génère/remplace un secret tant que le MFA n'est pas activé. enable vérifie le code du nouveau secret mais ni mot de passe courant ni ancienneté d'authentification. Aucun verrou de ligne utilisateur dans setup/enable.
- **Impact :** Un jeton d'accès compromis peut permettre d'enrôler un facteur contrôlé par l'attaquant et gêner les connexions futures. Risques concurrents lors du setup à tester.
- **Solution :** Exiger mot de passe ou preuve d'authentification forte récente pour l'enrôlement ; verrouiller la transition, notifier l'utilisateur et invalider les autres sessions selon politique.
- **Test de validation :** Avec seul bearer, refuser un enrôlement sans réauthentification ; tester setup concurrents, replay du code et validité des sessions après activation.

### KF-09 — Sauvegardes et pièces partagent les droits de suppression

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/scripts/backup.py:58`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/scripts/backup.py#L58).
- **Preuve technique :** Les sauvegardes utilisent objects._client et le même bucket/compte que les pièces ; prune supprime les anciens objets. deploy/vps/compose.yml transmet ces identifiants à API et worker. Aucun stockage WORM ou réplication indépendante configuré dans le dépôt.
- **Impact :** Le chiffrement protège la confidentialité mais pas la suppression malveillante par une application compromise. Le paramétrage réel du fournisseur reste inconnu.
- **Solution :** Compte et bucket de sauvegarde séparés, protection de rétention/versions administrée hors application, copie indépendante des pièces et clés séquestrées hors VPS.
- **Test de validation :** Sous identifiants API, tenter la suppression d'une sauvegarde protégée : refus. Restaurer base, pièces et clés depuis les seules copies hors serveur dans un environnement isolé.

### KF-10 — La reprise complète après perte du VPS n'est pas démontrée

- **Priorité / gravité :** P0 / Élevée.
- **Statut de preuve :** Preuve opérationnelle manquante.
- **Fichier :** [`deploy/vps/restore.sh:25`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/deploy/vps/restore.sh#L25).
- **Preuve technique :** restore.sh restaure PostgreSQL ; test_backup.py vérifie les objets chiffrés, pas un cycle pg_dump/pg_restore sur une nouvelle instance ni la récupération des pièces et des clés. La CI ne lance pas de restauration complète. Aucun accès au VPS réel n'a été utilisé.
- **Impact :** On ne peut pas garantir un RTO/RPO ni l'accès aux justificatifs après sinistre. C'est un blocage de validation production, pas la preuve que les sauvegardes actuelles sont inutilisables.
- **Solution :** Ajouter un exercice automatisé de restauration sur serveur vierge, base + S3 + clés + version du code ; mesurer la durée ; tester une clé secondaire et un backup ancien.
- **Test de validation :** Détruire uniquement une pile éphémère, reconstruire, restaurer, vérifier migrations, RLS, chaînes d'audit, comptages et hash de plusieurs pièces ; consigner RPO/RTO et date.

### KF-11 — Déploiement non versionné et sans sauvegarde préalable imposée

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`deploy/vps/deploy.sh:22`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/deploy/vps/deploy.sh#L22).
- **Preuve technique :** Le script avance main, reconstruit puis lance compose up et les migrations. Pas de sauvegarde pré-migration imposée, pas de rollback d'image par digest, pas de contrôle de checkout propre ni de procédure automatique de retour. Plusieurs images sont référencées par tags mobiles.
- **Impact :** Une erreur de migration ou de build peut prolonger une indisponibilité ; reproduire exactement une version dépend des registres au moment de la reconstruction.
- **Solution :** Release identifiée par SHA et digest, validation CI préalable, backup vérifié avant migration, schéma expand/contract, arrêt contrôlé si nécessaire et procédure de rollback documentée.
- **Test de validation :** Sur staging, simuler migration refusée, build indisponible et healthcheck échoué ; démontrer le retour à une version connue sans perte de données.

### KF-12 — Supervision limitée aux healthchecks et logs locaux

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Absence dans le dépôt ; configuration VPS non vérifiée.
- **Fichier :** [`apps/api/src/kora/api/health.py:47`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/api/health.py#L47).
- **Preuve technique :** ready teste seulement SELECT 1 et Redis ping. Pas de configuration de métriques, alertes externes, dead letters, succès de backup, expiration TLS, saturation disque ou contrôles périodiques d'intégrité dans le dépôt.
- **Impact :** Le processus peut rester vivant pendant une défaillance métier ou une sauvegarde en échec ; rotation locale des logs ne remplace pas l'alerte.
- **Solution :** Sondes externes et métriques API/PostgreSQL/Redis/worker/stockage ; alertes orientées actions, traces corrélées, contrôle périodique sauvegarde et audit. Conserver ready léger et ajouter des contrôles métier séparés.
- **Test de validation :** Injecter panne worker, disque presque plein, erreur S3 et backup en échec sur staging ; vérifier la réception d'une alerte et la procédure associée.

### KF-13 — Exports et stockage sans budget global de ressources

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/exports/service.py:65`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/exports/service.py#L65).
- **Preuve technique :** Les exports construisent le Document complet avant le seuil MAX_PDF_ROWS ; Excel n'a pas de plafond équivalent. full_ledger matérialise toutes les lignes. Le nombre de pièces est limité par écriture, sans quota total par société. compose.yml ne fixe pas de limites CPU/RAM.
- **Impact :** Un tenant très actif peut épuiser mémoire, connexions ou stockage et dégrader tous les clients du VPS. Aucune capacité chiffrée n'a été mesurée.
- **Solution :** Limiter avant lecture, exporter en streaming ou worker avec quotas, plafonner nombre d'exports concurrents et stockage par tenant, fixer les budgets conteneurs et préserver PostgreSQL.
- **Test de validation :** Charge multi-tenant avec grands livres de 10k/100k/1M lignes synthétiques et exports concurrents ; mesurer RSS, p95/p99, files, erreurs, équité entre tenants et arrêt contrôlé.

### KF-14 — La CSP autorise les scripts inline

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/web/src/proxy.ts:47`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/web/src/proxy.ts#L47).
- **Preuve technique :** contentSecurityPolicy inclut script-src 'self' 'unsafe-inline' en production. Le commentaire expose le compromis lié au prérendu Next.js. Pas de dangerouslySetInnerHTML repéré ; cela ne prouve pas l'absence de toute XSS.
- **Impact :** La CSP ne bloque pas un script inline si une autre vulnérabilité d'injection apparaît. Aucune XSS exploitable n'a été démontrée.
- **Solution :** Étudier nonces/hashes et politique compatible avec le rendu Next ; commencer en Report-Only puis supprimer unsafe-inline après validation.
- **Test de validation :** Parcours Next complets avec politique stricte, zéro violation légitime ; injection de script de test dans un banc isolé bloquée par la CSP.

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

### KF-17 — La PWA ne sauvegarde pas les saisies hors connexion

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/web/public/sw.js:1`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/web/public/sw.js#L1).
- **Preuve technique :** Le service worker met uniquement la page hors connexion en cache. EntryEditor garde les saisies en useState ; aucun stockage local durable/synchronisation d'écritures n'a été trouvé. UUID idempotent côté API ne fournit pas à lui seul un mode offline.
- **Impact :** Sur réseau instable ou fermeture d'onglet avant enregistrement, une PME peut perdre sa saisie. Ne pas annoncer la comptabilité utilisable hors ligne.
- **Solution :** Brouillons locaux isolés par utilisateur/tenant, protection des données sur téléphone partagé, synchronisation idempotente et résolution des conflits, indicateur de statut clair.
- **Test de validation :** Saisir en 3G dégradée, couper réseau, fermer/rouvrir, reconnecter ; obtenir une seule écriture exacte, puis vérifier déconnexion et changement d'utilisateur sans fuite locale.

### KF-18 — Le tableau de bord annonce encore la comptabilité à venir

- **Priorité / gravité :** P2 / Faible.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/web/src/app/[lang]/(app)/dossiers/[companyId]/page.tsx:111`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/web/src/app/[lang]/(app)/dossiers/[companyId]/page.tsx#L111).
- **Preuve technique :** Le dashboard contient seulement paramétrage/exercice et affiche t.dashboard.accountingComing alors que les routes comptables existent. Aucun KPI financier n'est chargé sur cette page.
- **Impact :** Parcours incohérent et faible visibilité sur les chiffres utiles aux dirigeants : caisse, banque, Mobile Money, créances et anomalies.
- **Solution :** Supprimer le message obsolète et définir des indicateurs calculés sur les écritures validées, avec période et fraîcheur explicites ; garder la saisie guidée facilement accessible.
- **Test de validation :** Vérifier FR/EN desktop/mobile et comparer chaque KPI au grand livre sur un jeu de comptes de référence.

### KF-19 — L'API accepte des devises non prises en charge par les exports

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/api/v1/companies.py:64`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/api/v1/companies.py#L64).
- **Preuve technique :** CompanyCreate accepte toute chaîne de trois majuscules. exports.document.currency_decimals accepte seulement GNF/XOF/XAF/EUR/USD. La devise n'est ensuite plus modifiable par update_company.
- **Impact :** Un dossier créé par API avec une autre devise peut fonctionner partiellement mais échouer à l'export et nécessiter une réparation administrée.
- **Solution :** Référentiel partagé des devises supportées, validation à la création et tests de contrat frontend/backend ; définir une migration pour les dossiers déjà concernés.
- **Test de validation :** Créer JPY et ZZZ via API : refus clair si hors périmètre ; toutes les devises autorisées doivent être saisissables, affichables et exportables avec les mêmes décimales.

### KF-20 — Les audits de dépendances ne sont pas dans la CI

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`.github/workflows/ci.yml:1`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/.github/workflows/ci.yml#L1).
- **Preuve technique :** La CI couvre gitleaks, lint, typage, tests, build et contrat. Aucun job pip-audit/npm audit/SBOM/scan d'image ni politique de mise à jour automatisée n'est défini. Audits locaux exécutés : zéro vulnérabilité connue dans les bases consultées.
- **Impact :** Une vulnérabilité publiée après ce contrôle ne bloque pas les futures releases. Les tags Docker non figés compliquent aussi la traçabilité.
- **Solution :** SCA Python/JS, SBOM et scan d'images sur release ; politique d'exceptions avec expiration et seuils définis ; pinning des images de production par digest.
- **Test de validation :** Dans une branche de test, injecter une dépendance de démonstration vulnérable : la CI doit échouer avec un diagnostic et une procédure d'exception traçable.

### KF-21 — Accessibilité et expérience 3G : preuves insuffisantes

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Couverture de validation manquante.
- **Fichier :** [`apps/web/playwright.config.ts:26`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/web/playwright.config.ts#L26).
- **Preuve technique :** Les E2E couvrent Chromium desktop et émulation Pixel 5. Pas de tests axe, lecteur d'écran, contraste mesuré, WebKit ou throttling réseau/CPU. Les composants ont des labels et états aria ; certains champs ont h-8, soit 32 px à l'échelle standard. Cela ne prouve pas une non-conformité WCAG.
- **Impact :** 56 E2E verts ne démontrent ni conformité WCAG ni confort sur téléphone guinéen peu puissant. Aucune inspection visuelle locale authentifiée n'a pu être effectuée.
- **Solution :** Audit manuel clavier/TalkBack, axe et contraste ; mesurer chargement et saisie sur Android réel en 3G ; viser des cibles tactiles confortables et tester Safari si supporté.
- **Test de validation :** Parcours inscription, saisie, photo justificatif, validation et export à 360 px, zoom 200 %, clavier seul, TalkBack et réseau lent ; zéro perte de saisie et zéro obstacle critique.

### KF-22 — Mise en file après commit sans outbox durable

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/worker/tasks.py:48`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/worker/tasks.py#L48).
- **Preuve technique :** _prepare_and_deliver prépare et commit le jeton via le service puis appelle deliver_email.send. enqueue_best_effort peut perdre une notification ; purge peut finir avec un objet orphelin si S3 et Redis sont indisponibles. Ces cas sont journalisés mais sans réconciliation durable identifiée.
- **Impact :** Emails ou purges perdus à la frontière DB/Redis ; réessais possibles mais l'utilisateur ou l'exploitation doit parfois intervenir.
- **Solution :** Outbox transactionnelle et worker idempotent, suivi des dead letters, réconciliation périodique des objets orphelins avec délai de sécurité.
- **Test de validation :** Arrêter Redis entre commit et enqueue puis redémarrer ; retrouver la tâche et livrer/purger une seule fois sans invalider un lien utile.

### KF-23 — Sauvegarde chargée intégralement avant contrôle de taille

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/scripts/backup.py:50`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/scripts/backup.py#L50).
- **Preuve technique :** upload fait path.read_bytes avant de vérifier MAX_BYTES=2 GiB ; chiffrement, empaquetage et relecture gardent plusieurs buffers. backup.sh conserve aussi des dumps locaux non chiffrés dans un répertoire 700 ; aucune politique de chiffrement disque vérifiable dans le dépôt.
- **Impact :** La sauvegarde elle-même peut provoquer un OOM sur petit VPS ; confidentialité locale dépend du serveur et de ses accès administrateur.
- **Solution :** Contrôle stat avant lecture, limite adaptée à la RAM et transfert/chiffrement par blocs ; espace de travail chiffré, umask strict, nettoyage sûr y compris sur échec.
- **Test de validation :** Backup synthétique dépassant le seuil refusé sans lire le contenu ; mesurer RSS en upload/download et tester l'échec de transfert sans résidu accessible.

## Backlog produit P3

| Sujet | Preuve d'absence / écart | Impact | Solution et validation |
|---|---|---|---|
| Ventes et achats | Pas de modèles/routes de factures/avoirs/tiers commerciaux | Pas d'outil commercial complet | Construire le cycle légal ; recette numérotation, mentions et avoirs |
| Relevés et rapprochement | Pas de connecteurs opérateurs/imports/score de rapprochement | Journal MM ≠ intégration Orange/MTN | Adaptateurs, staging et rapprochement humain ; tester doublons/frais/opérations inversées |
| Imports | Pas de pipeline FEC/Excel/balance | Reprise d'historique manuelle | Import avec staging et contrôle ; tests encodage, doublons, équilibre et rejets |
| Financement / partage | Rôle partenaire sans service de partage | Pas de dossier bancaire partageable | Pack validé et liens révocables ; tests permissions, expiration et journal d'accès |
| Abonnements / paiement | Aucun moteur/route/webhook | SaaS payant non automatisé | État/ledger paiement et adaptateurs ; tests idempotence, authenticité et rapprochement |
| IA | Aucun module fournisseur/agent | Pas d'automatisation IA réelle | Suggestions supervisées avec provenance ; tests isolation, évaluation métier et non-exécution sans accord |
| Portefeuille cabinet | API de base sans dashboard d'exploitation complet | Suivi multisociétés limité | Vue portefeuille source-backed et affectations ; tests droits et agrégats multi-tenant |

Toutes ces extensions devront avoir leurs propres critères d'acceptation avant de recevoir le statut « fonctionnel ».
