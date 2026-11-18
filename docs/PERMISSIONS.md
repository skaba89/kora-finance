# Matrice des permissions

> Fichier généré depuis `apps/api/src/kora/tenancy/permissions.py` (`make permissions-doc`). Ne pas modifier à la main.

| Permission | Description | SUPER_ADMIN | CABINET_ADMIN | CABINET_COLLABORATEUR | PME_DIRIGEANT | PME_COMPTABLE | PME_LECTEUR | PARTENAIRE_FINANCIER |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `company:read` | Consulter la fiche de l'entreprise | — | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `company:update` | Modifier la fiche de l'entreprise (raison sociale, RCCM, NIF…) | — | ✅ | — | ✅ | — | — | — |
| `members:read` | Voir les utilisateurs ayant accès au dossier | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `members:manage` | Ajouter, modifier ou retirer des utilisateurs du dossier | — | ✅ | — | ✅ | — | — | — |
| `fiscal_years:read` | Consulter les exercices comptables | — | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `fiscal_years:manage` | Créer des exercices et verrouiller des périodes | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `fiscal_years:close` | Clôturer, rouvrir un exercice et déverrouiller une période | — | ✅ | — | ✅ | — | — | — |
| `accounts:read` | Consulter le plan comptable | — | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `accounts:manage` | Personnaliser le plan comptable | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `taxes:read` | Consulter les taux de taxes | — | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `taxes:manage` | Paramétrer les taux de taxes | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `audit:read` | Consulter et vérifier le journal d'audit | — | ✅ | — | ✅ | ✅ | — | — |
| `journals:manage` | Créer et paramétrer les journaux comptables | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `entries:read` | Consulter les journaux et les écritures | — | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `entries:write` | Saisir et modifier des écritures en brouillon | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `entries:post` | Valider des écritures (numérotation définitive) et les contre-passer | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `lettering:manage` | Lettrer et délettrer les comptes de tiers | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `treasury:read` | Consulter les comptes de trésorerie (banques, caisses, Mobile Money) et leurs mouvements | — | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `treasury:manage` | Créer des comptes de trésorerie et enregistrer dépôts, retraits, frais et virements internes | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `partners:read` | Consulter le référentiel des tiers (clients, fournisseurs) | — | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `partners:manage` | Créer, modifier et désactiver des tiers | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `sales:read` | Consulter les devis, factures et avoirs | — | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `sales:manage` | Créer, émettre (numérotation définitive), convertir et annuler devis, factures et avoirs | — | ✅ | ✅ | ✅ | ✅ | — | — |
| `purchases:read` | Consulter les factures et avoirs fournisseurs | — | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `purchases:manage` | Créer, émettre (numérotation définitive), annuler et payer factures et avoirs fournisseurs | — | ✅ | ✅ | ✅ | ✅ | — | — |

SUPER_ADMIN : aucune permission sur les dossiers (administration de la plateforme uniquement). PARTENAIRE_FINANCIER : accès limité aux dossiers de financement partagés (phase 6).
