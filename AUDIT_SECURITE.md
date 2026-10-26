# Audit sécurité — Kora Finance

Date : 26 octobre 2026 — dépôt privé `skaba89/kora-finance`

Référence figée : `7a51c45258301e8cfc50a0305ce023e08d286202` (`main` au début de l'audit). Les constats visent ce commit, pas l'état réel d'un VPS. Aucun accès aux données de production, aucune migration ni aucun déploiement effectués.

## Verdict et référentiel

Revue orientée OWASP ASVS 5.0.0, avec objectif de contrôle de niveau L2 à définir formellement pour ce SaaS financier. Ceci n'est pas une certification ASVS : il n'y a pas de matrice de chaque exigence vérifiée par pentest. La classification ci-dessous couvre les familles examinées, avec preuves positives et réserves explicites. Source de version : https://asvs.owasp.org/ (stable 5.0.0, consulté le 26/10/2026).

| Famille de contrôle | Éléments positifs constatés | Réserve / prochaine validation |
|---|---|---|
| Authentification et sessions | Argon2, politique mot de passe, JWT typés, rotation refresh, token_version, TOTP et codes de secours | KF-06/KF-08 ; grâce refresh 20 s permet des jetons frères, à inclure dans le modèle de menace ; logout simple ne révoque pas instantanément tous les access tokens |
| Autorisations | Backend require(permission), rôles limités, 404 tenant, tests négatifs | Pas de contrôle dynamique additionnel ici ; multi-tenant à tester aussi sur exports/pièces et pool concurrent |
| Isolation DB | FORCE RLS, NOBYPASSRLS, contexte local à chaque transaction, FK tenant | KF-01/KF-02 ; tables identité globales et paramètre tenant choisi par application ne protègent pas contre une application entièrement compromise |
| Validation / injections | ORM, limites Pydantic et pagination, garde-fous SQL, échappement PDF | KF-04 reproduit ; aucun SQLi confirmé, pas de preuve d'absence universelle |
| Cryptographie / secrets | AES-256-GCM, clés par objet, Fernet multi-clés, secrets non codés dans Settings | Accès owner au runtime, absence d'ancrage indépendant d'audit, procédure de rotation complète à démontrer |
| Navigateur / CSRF | Cookies httpOnly/Secure HTTPS/SameSite Lax, Server Actions, frame-ancestors/object-src none | CSP inline ; protections Origin des actions Next à tester derrière proxy réel ; pas de conclusion de faille CSRF sans reproduction |
| Fichiers | Taille 10 Mo, plafond par écriture, signatures MIME, noms nettoyés, hash de contenu | Signature seule n'analyse pas la structure d'un PDF/image ou les contenus actifs ; scan/quarantaine à envisager selon menace |
| Journalisation | Audit chaîné, logs JSON, redaction gitleaks CI | Les têtes ne sont pas ancrées hors DB ; pas de preuve de centralisation/alerting ni rétention effectivement déployés |
| Dépendances / chaîne logicielle | uv.lock/package-lock, actions GitHub par SHA | Aucun avis connu détecté localement ; scan CI et images à compléter |
| Disponibilité / logique métier | Rate limit auth, limites de ligne et upload, verrouillage séquences | Exports synchrones, absence de quotas globaux, cas concurrents et restauration à compléter |

## Secrets et dépendances

Aucune valeur secrète n'est reproduite dans ces livrables. Gitleaks CI du SHA : « no leaks found ». L'historique complet n'a pas été re-scanné localement. npm audit local : 0 avis ; pip-audit local : 76 distributions, 0 avis. Ces résultats sont datés, dépendants des bases de vulnérabilités et ne valident ni configuration, ni composants système du VPS, ni images réellement installées.

Les identifiants de stockage et secrets de chiffrement sont exigés ; cela ne valide pas leur entropie réelle, la restriction du bucket ou leur stockage hors VPS. Le champ JWT impose une longueur minimale, pas une mesure d'entropie. Les secrets de production n'ont pas été lus.

## Anomalies et validation

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

### KF-04 — Injection de formule dans les exports Excel

- **Priorité / gravité :** P1 / Élevée.
- **Statut de preuve :** Reproduit localement ; correctif testé, non fusionné.
- **Fichier :** [`apps/api/src/kora/exports/xlsx.py:37`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/exports/xlsx.py#L37).
- **Preuve technique :** sheet.append reçoit directement les textes métier. Le test test_xlsx_security.py fournit '=1+1' dans les métadonnées et le détail : huit cellules deviennent de type f au lieu de s. Test exécuté : échec avant correctif, succès après sérialisation littérale.
- **Impact :** Un texte comptable contrôlé par un utilisateur peut être interprété comme formule lors de l'ouverture du classeur. Le comportement des liens externes dépend d'Excel et de ses protections ; aucune exfiltration réelle n'a été tentée.
- **Solution :** Forcer le type chaîne des cellules textuelles pour tous les points d'écriture, y compris en-têtes et notes ; conserver les montants numériques. Correctif préparé sur branche séparée fix/audit-xlsx-literal-text.
- **Test de validation :** Ouvrir le XLSX avec openpyxl data_only=False ; zéro cellule f, textes conservés exactement et montant 1234567 de type n. Puis exécuter les exports d'intégration existants.

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

### KF-14 — La CSP autorise les scripts inline

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/web/src/proxy.ts:47`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/web/src/proxy.ts#L47).
- **Preuve technique :** contentSecurityPolicy inclut script-src 'self' 'unsafe-inline' en production. Le commentaire expose le compromis lié au prérendu Next.js. Pas de dangerouslySetInnerHTML repéré ; cela ne prouve pas l'absence de toute XSS.
- **Impact :** La CSP ne bloque pas un script inline si une autre vulnérabilité d'injection apparaît. Aucune XSS exploitable n'a été démontrée.
- **Solution :** Étudier nonces/hashes et politique compatible avec le rendu Next ; commencer en Report-Only puis supprimer unsafe-inline après validation.
- **Test de validation :** Parcours Next complets avec politique stricte, zéro violation légitime ; injection de script de test dans un banc isolé bloquée par la CSP.

### KF-20 — Les audits de dépendances ne sont pas dans la CI

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`.github/workflows/ci.yml:1`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/.github/workflows/ci.yml#L1).
- **Preuve technique :** La CI couvre gitleaks, lint, typage, tests, build et contrat. Aucun job pip-audit/npm audit/SBOM/scan d'image ni politique de mise à jour automatisée n'est défini. Audits locaux exécutés : zéro vulnérabilité connue dans les bases consultées.
- **Impact :** Une vulnérabilité publiée après ce contrôle ne bloque pas les futures releases. Les tags Docker non figés compliquent aussi la traçabilité.
- **Solution :** SCA Python/JS, SBOM et scan d'images sur release ; politique d'exceptions avec expiration et seuils définis ; pinning des images de production par digest.
- **Test de validation :** Dans une branche de test, injecter une dépendance de démonstration vulnérable : la CI doit échouer avec un diagnostic et une procédure d'exception traçable.

### KF-22 — Mise en file après commit sans outbox durable

- **Priorité / gravité :** P2 / Modérée.
- **Statut de preuve :** Établi par lecture du code.
- **Fichier :** [`apps/api/src/kora/worker/tasks.py:48`](https://github.com/skaba89/kora-finance/blob/7a51c45258301e8cfc50a0305ce023e08d286202/apps/api/src/kora/worker/tasks.py#L48).
- **Preuve technique :** _prepare_and_deliver prépare et commit le jeton via le service puis appelle deliver_email.send. enqueue_best_effort peut perdre une notification ; purge peut finir avec un objet orphelin si S3 et Redis sont indisponibles. Ces cas sont journalisés mais sans réconciliation durable identifiée.
- **Impact :** Emails ou purges perdus à la frontière DB/Redis ; réessais possibles mais l'utilisateur ou l'exploitation doit parfois intervenir.
- **Solution :** Outbox transactionnelle et worker idempotent, suivi des dead letters, réconciliation périodique des objets orphelins avec délai de sécurité.
- **Test de validation :** Arrêter Redis entre commit et enqueue puis redémarrer ; retrouver la tâche et livrer/purger une seule fois sans invalider un lien utile.


## Plan de vérification avant homologation interne

Sur staging éphémère : matrice complète rôle × action × tenant, UUID étrangers dans corps et URL, accès aux pièces/exports, réutilisation d'un pool après commit/rollback/erreur ; changement de droits pendant une session ; expiration/revocation/refresh concurrents ; MFA setup/enable/disable concurrents ; CSRF et headers au proxy ; uploads falsifiés, polyglottes, fichiers volumineux et lenteur ; SQL direct avec rôle app pour les invariants financiers ; scan DAST autorisé sur staging uniquement. Documenter chaque exigence ASVS retenue avec résultat conforme/non conforme/non testé/non applicable et preuve.
