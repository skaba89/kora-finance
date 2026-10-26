# Audit global — Kora Finance

Date : 26 octobre 2026 — dépôt privé `skaba89/kora-finance`

Référence figée : `7a51c45258301e8cfc50a0305ce023e08d286202` (`main` au début de l'audit). Les constats visent ce commit, pas l'état réel d'un VPS. Aucun accès aux données de production, aucune migration ni aucun déploiement effectués.

## Verdict

**NO-GO pour une commercialisation générale présentée comme une comptabilité SYSCOHADA complète et une production résiliente.** Un pilote fermé sur données de démonstration est envisageable après traitement des P0. Un pilote avec données réelles exige en plus validation comptable et exercice de restauration documenté. Ce verdict ne signifie pas que l'application est une simple maquette : le socle comptable est réel et fortement testé.

Aucun pourcentage arbitraire de « projet terminé » n'est donné. « Implémenté et testé » ci-dessous signifie présence de code et tests correspondants, pas certification fonctionnelle ou aptitude à la production.

## Méthode et limites

Inventaire récursif des 317 fichiers du commit, récupération et vérification SHA de 312 fichiers textuels, analyse syntaxique de tous les Python, revue des routes/services/modèles/migrations critiques, recherche transversale des usages risqués, inspection des tests et journaux CI. Les cinq fichiers non matérialisés sont quatre icônes PNG dans apps/web/public/icons et favicon.ico. README/CLAUDE/worklog servent uniquement de contexte ; le cahier des charges sert à identifier les écarts de périmètre, jamais à prouver une réalisation.

L'historique récent de dix commits et la CI du SHA ont été consultés. L'historique complet des changements métier n'a pas été relu ligne par ligne. La copie locale est un snapshot initialisé sur une branche d'audit ; son commit local n'est pas le commit GitHub original. Les hashes des sources initiales ont été comparés aux blobs GitHub avant toute modification.

Aucun Docker/PostgreSQL/Redis local disponible ; tentative pytest arrêtée par la fixture de migration sur base locale absente. L'installation du navigateur Playwright a échoué (archive téléchargée invalide). Pas de pentest dynamique authentifié, de charge, d'inspection visuelle des écrans métier ni de contrôle du VPS réel. Il serait trompeur de présenter ce travail comme une certification exhaustive ASVS, comptable ou d'exploitation. Les lacunes de preuve sont conservées dans le backlog.

## Architecture vérifiée

Monorepo : apps/api (FastAPI synchrone, SQLAlchemy, Alembic, PostgreSQL), apps/web (Next.js App Router, React/TypeScript), Redis/Dramatiq, stockage S3 compatible, Caddy et Docker Compose pour VPS. Le navigateur parle au BFF Next ; les Server Actions transmettent les JWT à l'API interne. Les cookies sont httpOnly, Secure selon configuration HTTPS, SameSite Lax. L'API vérifie signature, type, issuer/audience et version du jeton ; le décodage non signé dans le proxy Next ne constitue pas à lui seul une autorisation.

Les écritures utilisent int/BIGINT en unités mineures, chaînes à l'API et BigInt dans les calculs frontend. Les sommes SQL et les conversions Python évitent l'arithmétique monétaire en flottants. Les références fiscales sont datées et les affectations d'états sont en CSV versionnés. Les exports sont actuellement synchrones dans le processus API.

## Modules réels

| Module | État constaté | Preuves de code et de tests | Limite principale |
|---|---|---|---|
| Auth, refresh, MFA, reset et emails | Implémenté et testé | auth/*, api/v1/auth.py, mfa.py ; test_auth/mfa/emails.py | Réauthentification MFA et concurrence à durcir ; SMTP production inconnu |
| Multi-tenant / RBAC | Implémenté et testé | db/tenant.py, tenancy/* ; test_isolation_tenants.py, test_permissions.py | Tables d'identité globales hors RLS par conception ; sécurité dépend aussi des contrôles applicatifs |
| Entreprises, membres, cabinets | Implémenté ; espace cabinet partiel | organization/*, api/v1/firms.py ; test_companies/permissions.py | Pas de véritable dashboard portefeuille ; concurrence dernier dirigeant |
| Plan comptable / taxes | Implémenté et testé | accounting/setup.py, service.py, 4 CSV ; test_accounting.py | Référentiel et fiscalité à approuver par expert |
| Journaux / partie double / validation / contre-passation | Implémenté et testé | entries.py, ledger.py, migration 0005 ; test_ledger_invariants.py | KF-01, durcissement SQL et scénarios concurrents à compléter |
| Saisie guidée | Implémenté et testé | guided.py, guided-form.tsx ; test_guided.py, saisie-guidee.spec.ts | Ce n'est ni un module de facturation ni un assistant IA |
| Pièces justificatives chiffrées | Implémenté et testé | attachments/service.py, storage/objects.py, migration 0008 ; test_attachments.py | Rétention externe, scan malveillant et PRA non prouvés |
| Lettrage | Implémenté et testé | lettering.py, migration 0006 ; test_lettering.py | Ne constitue pas un rapprochement bancaire ou opérateur Mobile Money |
| Clôture / à-nouveaux / réouverture | Implémenté et testé sur scénarios fournis | closing.py, migration 0007 ; test_closing.py | Comptabilité réglementaire et concurrence inter-exercices non validées indépendamment |
| Balance / grand livre / journaux | Implémenté et testé | reports.py et exports/* ; test_reports/exports.py | Snapshot cohérent et gros volumes à traiter |
| Bilan / compte de résultat | Implémenté, conformité partielle | statements.py, CSV d'affectations ; test_statements.py | Pas de tableau des flux ni notes annexes ; mapping non signé |
| PWA | Installation/page offline implémentées | manifest.ts, public/sw.js | Pas de saisie offline durable avec synchronisation |
| Ventes/achats commerciaux | Absents | Aucun modèle/route/service clients-fournisseurs-factures-avoirs dans l'inventaire métier | Les opérations guidées « facture client » sont des écritures, pas des factures commerciales |
| Trésorerie et Mobile Money opérationnels | Partiels au niveau comptable | Journaux BQ/CA/MM, comptes 52/55/57 et saisie guidée | Pas de relevés, connecteurs, rapprochement, frais automatisés ni prévisionnel |
| Imports FEC/Excel/balance | Absents | Aucun pipeline d'import métier dans routes/services/worker | Pas de migration automatisée de la comptabilité d'une PME |
| Fiscalité déclarative | Absente comme module déclaratif | Taxes et écritures existent | Pas de déclaration TVA préparée/validée/transmise |
| Dossier de financement / partage révocable | Absent | Rôle partenaire défini sans permission dossier ; pas de service de partage | Pas de pack bancaire validé ni liens de partage |
| Assistant IA | Absent | Pas de module LLM/catégorisation/audit IA | Aucun verdict de signabilité opérationnel |
| Abonnements / encaissements SaaS | Absents | Pas de modèles/API/webhooks de paiement ou plans | Impossible de conclure à une fiabilité de paiement ; à construire |
| Certificats / attestations signés | Absents du périmètre implémenté | Aucun service de certification identifié | Un PDF exporté n'est pas un certificat ni une validation professionnelle |

## Tests et qualité

| Contrôle | Résultat | Portée de la preuve |
|---|---|---|
| Sources récupérées | 312 fichiers texte, SHA Git vérifiés ; 5 icônes binaires non matérialisées | Tous les chemins inventoriés ; pas d'inspection des icônes |
| uv sync --frozen --group dev | Réussi, Python 3.13.16 | Environnement local isolé |
| Ruff check + format --check | Réussi sur le snapshot initial, 137 fichiers formatés | Local ; aucun formatage du code initial |
| mypy | Réussi, 128 fichiers initiaux | Local ; 129 après ajout du test de régression |
| pytest existant local | Tentative interrompue : PostgreSQL 127.0.0.1:55432 absent, 1 erreur de fixture | Aucun test métier backend validé localement |
| pytest CI du commit | 504 passed, 339,96 s ; couverture branches activée, TOTAL 95 % | Journaux GitHub consultés, exécution historique du 25/10/2026 |
| Vitest | 9 fichiers / 44 tests réussis | Rejoué localement et confirmé en CI |
| ESLint / TypeScript / next build | Réussis | Local ; build sans les cinq icônes, donc pas preuve d'intégrité du packaging des images |
| E2E existants | 56 passed, 3,5 min | Journaux CI ; Chromium desktop + Pixel 5 émulé ; pas 56 parcours distincts nécessairement |
| Contrat OpenAPI | Job CI réussi | Pas de régénération locale complète |
| Secrets gitleaks | no leaks found | CI avec historique Git ; pas un certificat d'absence de tout secret |
| npm audit | 0 vulnérabilité connue | Exécuté localement le 26/10/2026 |
| pip-audit | 76 distributions / 0 vulnérabilité connue | .venv local installé depuis lock ; disponibilité des bases d'avis requise |
| Régression XLSX ajoutée sur branche fix/audit-xlsx-literal-text | 1 failed sur code initial, puis 1 passed après correctif | --noconftest ; prouve la sérialisation littérale, pas l'intégration DB |

CI de référence : https://github.com/skaba89/kora-finance/actions/runs/40209700768
Jobs : API 121218096906, E2E 121218096961, Web 121218096854, Secrets 121218096762, contrat 121218096969.

Les tests sont substantiels : vraie base PostgreSQL, rôles distincts, RLS, attaques SQL d'invariants, Hypothesis et 20 validations simultanées. La couverture de 95 % n'empêche pas KF-01/KF-04 : les assertions n'explorent pas toutes les transitions possibles. Les tests PDF vérifient surtout signature/pages et les montants ; ils ne remplacent pas une revue visuelle de tous les états et toutes les longueurs de libellé.

## Points forts vérifiés

RLS ENABLE et FORCE sur les tables métier tenant ; application du contexte transactionnel après chaque begin ; clés étrangères composites sur comptes/journaux/exercices/lignes ; app NOSUPERUSER/NOBYPASSRLS ; contrôle des permissions backend et réponse 404 pour dossier inaccessible ; immuabilité des en-têtes validés ; numérotation verrouillée et contraintes uniques ; audit chaîné transactionnel avec verrou de tête ; chiffrement AES-GCM des objets et enveloppe Fernet ; limites de corps upload ; échappement XML PDF ; lint/typage/contrat/E2E en CI.

Le journal d'audit reste altérable par le propriétaire de la base : un ancrage indépendant n'est pas implémenté. Un rôle applicatif qui peut choisir app.tenant_id n'est pas une frontière contre du SQL arbitraire compromis : la RLS protège surtout les erreurs d'accès dans les chemins contrôlés.

## Registre des anomalies

Le registre détaillé et les tests d'acceptation sont dans BACKLOG_PRIORISE.md ; les rapports spécialisés reprennent les constats concernés. P0 désigne aussi un manque de preuve bloquant la production, pas nécessairement une vulnérabilité exploitable depuis Internet.

- **KF-01 — P0 / Critique :** Le trigger des lignes ne contrôle pas le parent de destination (Établi par lecture du code).
- **KF-02 — P0 / Élevée :** Le secret du propriétaire de schéma est transmis aux services applicatifs (Établi par lecture du code).
- **KF-03 — P1 / Élevée :** Clôture et modifications concurrentes : preuve complémentaire indispensable (Risque identifié ; exploitation non reproduite).
- **KF-04 — P1 / Élevée :** Injection de formule dans les exports Excel (Reproduit localement ; correctif testé, non fusionné).
- **KF-05 — P1 / Élevée :** Les lectures multi-requêtes ne fixent pas de snapshot comptable (Risque de concurrence étayé par le code).
- **KF-06 — P1 / Élevée :** Compteur de tentatives de connexion non atomique (Risque de concurrence étayé par le code).
- **KF-07 — P1 / Élevée :** Dernier dirigeant : contrôle de cardinalité non sérialisé (Risque de concurrence étayé par le code).
- **KF-08 — P1 / Élevée :** Activation MFA sans réauthentification récente (Établi par lecture du code).
- **KF-09 — P1 / Élevée :** Sauvegardes et pièces partagent les droits de suppression (Établi par lecture du code).
- **KF-10 — P0 / Élevée :** La reprise complète après perte du VPS n'est pas démontrée (Preuve opérationnelle manquante).
- **KF-11 — P1 / Élevée :** Déploiement non versionné et sans sauvegarde préalable imposée (Établi par lecture du code).
- **KF-12 — P1 / Élevée :** Supervision limitée aux healthchecks et logs locaux (Absence dans le dépôt ; configuration VPS non vérifiée).
- **KF-13 — P1 / Élevée :** Exports et stockage sans budget global de ressources (Établi par lecture du code).
- **KF-14 — P2 / Modérée :** La CSP autorise les scripts inline (Établi par lecture du code).
- **KF-15 — P1 / Élevée :** Jeu d'états SYSCOHADA incomplet (Établi par lecture du code).
- **KF-16 — P1 / Élevée :** Règles fiscales et exercices nécessitent un arbitrage métier (Validation réglementaire externe nécessaire).
- **KF-17 — P2 / Modérée :** La PWA ne sauvegarde pas les saisies hors connexion (Établi par lecture du code).
- **KF-18 — P2 / Faible :** Le tableau de bord annonce encore la comptabilité à venir (Établi par lecture du code).
- **KF-19 — P2 / Modérée :** L'API accepte des devises non prises en charge par les exports (Établi par lecture du code).
- **KF-20 — P2 / Modérée :** Les audits de dépendances ne sont pas dans la CI (Établi par lecture du code).
- **KF-21 — P2 / Modérée :** Accessibilité et expérience 3G : preuves insuffisantes (Couverture de validation manquante).
- **KF-22 — P2 / Modérée :** Mise en file après commit sans outbox durable (Établi par lecture du code).
- **KF-23 — P2 / Modérée :** Sauvegarde chargée intégralement avant contrôle de taille (Établi par lecture du code).

## Décisions avant ouverture commerciale

Traiter les P0, puis les P1 touchant intégrité/sécurité/PRA ; faire signer les règles et états par un expert-comptable guinéen ; choisir un périmètre commercial honnête (tenue comptable limitée, ou suite complète après réalisation des modules absents). Organiser un pilote avec données synthétiques puis un petit groupe de PME et cabinets, sans annoncer une capacité nationale non mesurée.
