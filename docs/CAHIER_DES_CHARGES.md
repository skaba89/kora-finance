# Kora Finance — Cahier des charges

> Version d'origine fournie par le porteur du projet le 2026-10-23. Écart validé depuis :
> **Next.js 16** au lieu de Next.js 14 (voir `CLAUDE.md`, décisions d'architecture).

## Vision produit
Les PME guinéennes tiennent leur comptabilité à la main ou sur Excel. Elles n'ont pas d'états financiers fiables, ce qui les empêche d'accéder au crédit (banques, FODIP). Une grande partie de leurs flux passe par le Mobile Money, que personne ne rapproche de la comptabilité.

Kora Finance résout ça :
- tenue de comptabilité conforme au SYSCOHADA révisé ;
- rapprochement automatique Mobile Money et bancaire ;
- production d'états financiers fiables, prêts pour un dossier de crédit ;
- assistance IA pour la saisie, le contrôle et l'analyse.

## Clients et rôles
- **PME** : dirigeant, comptable interne, collaborateur en lecture seule.
- **Cabinet comptable** : gère plusieurs PME clientes depuis un seul compte, avec un tableau de bord de portefeuille.
- **Partenaire financier** (banque, FODIP) : accès en lecture, uniquement aux dossiers que la PME a explicitement partagés.
- **Super-admin plateforme** : gestion des abonnements et du support.

Rôles RBAC : SUPER_ADMIN, CABINET_ADMIN, CABINET_COLLABORATEUR, PME_DIRIGEANT, PME_COMPTABLE, PME_LECTEUR, PARTENAIRE_FINANCIER.

## Stack technique
- Backend : FastAPI (Python 3.11+), SQLAlchemy 2.x, Alembic (jamais `create_all()`), Pydantic v2.
- Base de données : PostgreSQL 16, avec isolation multi-tenant (tenant_id sur chaque table + filtrage obligatoire dans la couche d'accès).
- Cache et files : Redis, avec un worker pour les tâches longues (imports, rapprochements, génération de PDF).
- Stockage des pièces : compatible S3 (MinIO en local).
- Frontend : Next.js 14 (App Router) + TypeScript strict + Tailwind + shadcn/ui. *(→ Next.js 16, validé le 2026-10-23)*
- Mobile : application PWA installable, utilisable en connexion instable.
- Auth : JWT avec refresh tokens, 2FA optionnelle, verrouillage après échecs répétés.
- Docker Compose pour le local, CI GitHub Actions, déploiement sur Render ou équivalent.

## Modules à livrer

### 1. Organisation et paramétrage
- Création d'entreprise : raison sociale, RCCM, NIF, forme juridique, exercice comptable, devise (GNF par défaut).
- Multi-exercices, clôture et réouverture contrôlées.
- Plan comptable SYSCOHADA révisé préchargé, personnalisable par entreprise.
- Taux de TVA et autres taxes paramétrables (ne jamais coder un taux en dur : les valeurs par défaut doivent être modifiables et documentées comme « à vérifier auprès de la DGI »).

### 2. Comptabilité générale
- Journaux (achats, ventes, banque, caisse, Mobile Money, OD), saisie en partie double avec contrôle d'équilibre.
- Saisie guidée pour non-comptables (« j'ai payé une facture », « j'ai reçu un paiement ») qui génère les écritures.
- Pièces justificatives attachées à chaque écriture.
- Lettrage clients et fournisseurs, écritures de clôture et d'à-nouveaux.
- Verrouillage des périodes clôturées, aucune suppression d'écriture validée (contre-passation uniquement).

### 3. Ventes et achats
- Clients, fournisseurs, devis, factures, avoirs, numérotation chronologique sans trou.
- Factures PDF conformes avec mentions légales, envoi par email et WhatsApp.
- Suivi des créances, relances, balance âgée.

### 4. Trésorerie et Mobile Money
- Comptes bancaires, caisses et portefeuilles Mobile Money (Orange Money, MTN MoMo et autres opérateurs, via une couche d'abstraction par opérateur).
- Import des relevés (CSV, Excel, PDF si possible) avec détection automatique du format.
- Rapprochement automatique : correspondance par montant, date, référence et tiers, avec score de confiance ; validation manuelle des cas incertains.
- Gestion des frais Mobile Money et des retraits en espèces.
- Prévisionnel de trésorerie à 30, 60 et 90 jours.

### 5. Import et migration
- Import FEC, Excel et balance d'ouverture, pour récupérer l'existant d'une PME ou d'un cabinet.
- Rapport de contrôle après import (déséquilibres, comptes inconnus, doublons).

### 6. États financiers et reporting
- Balance, grand livre, journaux, bilan, compte de résultat, tableau des flux de trésorerie (formats SYSCOHADA).
- Déclarations fiscales préparées (TVA notamment), à partir des taux paramétrés.
- Export PDF et Excel.
- **Dossier de financement** : un pack généré en un clic (états financiers, indicateurs clés, historique de trésorerie) que la PME peut partager avec une banque ou le FODIP via un lien sécurisé et révocable.

### 7. Assistant IA
- Catégorisation automatique des transactions importées, avec apprentissage des corrections de l'utilisateur.
- Agent d'audit comptable : détection d'anomalies (écritures déséquilibrées, comptes mal utilisés, doublons, TVA incohérente) avec un verdict de « signabilité » des comptes.
- Questions en langage naturel sur les chiffres (« quel est mon chiffre d'affaires du trimestre ? »).
- Couche d'abstraction multi-fournisseurs LLM. L'IA propose, l'humain valide : aucune écriture créée par l'IA sans confirmation.

### 8. Espace cabinet comptable
- Tableau de bord de portefeuille : état de chaque dossier client, échéances, anomalies.
- Bascule rapide entre dossiers, affectation des collaborateurs.

### 9. Abonnements et facturation de la plateforme
- Plans (PME, PME+, Cabinet) avec limites, période d'essai, paiement par Mobile Money et carte.

## Exigences non fonctionnelles
- **Sécurité** : isolation stricte entre tenants (tests dédiés qui prouvent qu'un tenant ne voit jamais les données d'un autre), chiffrement des données sensibles, protection OWASP, rate limiting, aucun secret dans le dépôt.
- **Traçabilité** : journal d'audit infalsifiable (chaînage SHA-256) de toutes les actions sur les écritures et les paramètres.
- **Paiements** : idempotence sur tous les webhooks et paiements, pour qu'un client ne soit jamais débité deux fois.
- **Performance** : pas de requêtes N+1, pagination partout, imports volumineux traités en tâche de fond.
- **Contexte guinéen** : interface légère, utilisable en 3G, mode hors-ligne pour la saisie avec synchronisation, montants en GNF sans décimales, formats de date français.
- **Langues** : français par défaut, anglais en second.
- **Sauvegardes** : sauvegarde quotidienne et test de restauration automatisé.
- **Qualité** : tests unitaires et d'intégration sur toute la logique comptable (équilibre, clôture, rapprochement, états financiers), tests de bout en bout sur les parcours principaux, CI qui bloque si un test échoue.

## Méthode de travail
1. Commencer par un audit du dépôt (fait le 2026-10-23 : aucun code existant).
2. Plan par phases avec critères d'acceptation vérifiables, validé avant de coder (`docs/PLAN.md`).
3. Travailler phase par phase : tests verts, build OK, résumé livré/restant à chaque fin de phase.
4. Tenir à jour `CLAUDE.md` et `worklog.md`.
5. Aucun raccourci silencieux.
6. Toute règle fiscale ou comptable incertaine : « à valider par un expert-comptable guinéen ».

## Ordre de priorité
1. Socle : auth, multi-tenant, RBAC, organisation, plan comptable, audit log, CI.
2. Comptabilité générale complète et états financiers.
3. Trésorerie, Mobile Money et rapprochement.
4. Ventes et achats.
5. Import et migration.
6. Dossier de financement partageable.
7. Assistant IA.
8. Espace cabinet et abonnements.
