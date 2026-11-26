# Audit de suivi — 27 novembre 2026

Prolongement de `AUDIT_SUIVI_20261109.md` (§1–§43). Référence courante : `71b2952f467db49fe49c2f49a16b7329449e24f2`
(`main`, merge PR #210 du 2026-11-26). Périmètre : vérification des lots fusionnés
depuis le 2026-11-24 (PR #195 à #210), cartographie de complétude par domaine,
environnements, backlog dédoublonné P0–P3 et tableau de pilotage. Audit réalisé
depuis un bac à sable d'exécution : **aucun accès au VPS de production ni à REC**,
aucune donnée de production consultée, aucun déploiement effectué.

## 1. État vérifié des lots récents (PR #195 → #210)

| PR | Objet | Vérification dans le code `71b2952` |
|---|---|---|
| #202 | 2FA exigible pour l'administration plateforme | `core/config.py` (`KORA_PLATFORM_ADMIN_REQUIRE_MFA`), garde d'accès admin ; recette documentée (worklog 2026-11-24/25) |
| #204 | Journal des requêtes lentes + pool dimensionné | `KORA_SLOW_REQUEST_MS` + réglages pool dans la configuration API |
| #207 | Page `/administration/licences` en erreur (fonctions serveur appelées depuis un module client) | Corrigé ; garde-fou `client-boundary.test.ts` présent ; **aucun E2E Playwright licences** (seul `administration-modules.spec.ts` existe) |
| #208 | Passthrough des réglages vers les conteneurs (2FA, pool, slow log, plafonds N-B6) | `deploy/vps/compose.yml` complété ; contrôle CI `scripts/check-compose-env.py` |
| #209 | Worklog de recette locale des écrans d'administration | `worklog.md` (2026-11-25) |
| #210 | Mode preview intégrable en iframe (`KORA_PREVIEW_EMBED`) | `proxy.ts` (CSP), `session.ts` (SameSite), `next.config.ts` (allowedOrigins) — production inchangée sans la variable |

CI sur `main` (run `45843916910`, branche PR #210, 2026-11-26) : 9/9 jobs verts
(gitleaks, SCA, périmètre, contrat, restauration synthétique, Web eslint+tsc+vitest+build,
API ruff+mypy+pytest, E2E Playwright, résultat). Plancher de couverture backend 90 %
actif depuis #201.

**Constat de production (reporté tel quel du worklog 2026-11-25)** : « Le prochain
déploiement doit inclure #204, #207 et #208. » L'état réellement déployé n'est pas
vérifiable depuis ce bac à sable : à traiter comme une action opérateur obligatoire
(backlog PROD-1). Une CI verte ne prouve pas l'état du VPS.

## 2. Cartographie de complétude par domaine

| Domaine (phase du plan produit) | Livré et testé (preuve) | Manquant |
|---|---|---|
| Import comptable CSV/Excel/FEC | Dépôt chiffré (`accounting_import_batches`, migration 0026, clé wrappée, dédoublonnage sha256, expiration), précontrôle (`upload` + `precheck`, `import_fec/xlsx/validation/business/service`), 7 fichiers de tests imports | Analyse détaillée→prévisualisation persistée, confirmation humaine, génération transactionnelle de brouillons, annulation, gestion des conflits/reprises, tests inter-entreprises |
| Espace cabinet | API `firms` (création, liste, membres, affectations), accès contrôlés dans `test_permissions.py` | Frontend multi-clients (portefeuille, filtres, échéances, pièces manquantes, tâches de révision), E2E dédiés, tests de séparation inter-cabinets et de révocation |
| Commercial / licences | Migrations 0027–0032 (modules, offres, licences, publication, affectation, suspension), 17 fichiers de tests (offres, licences, renouvellement, enforcement, catalogues), UI admin licences+modules, renouvellement HTTP+UI (#199/#200), 2FA admin (#202) | Catalogue tarifaire versionné, périodes d'essai, abonnements mensuels/annuels, factures, paiements, relances, résiliations — **bloqué métier** (tarifs, entité facturante, contrat de paiement à valider avant activation) |
| Trésorerie / rapprochement | Relevés bancaires + unicité + prévisions (0011–0014), relevés XLSX (0015), `treasury.py`, partenaires (0016), KPIs recouvrement + balance âgée + échéanciers (§43, B-4) | Imports Orange Money / MTN MoMo dédiés, commissions, transferts internes, connecteurs API (architecture seule — aucun contrat opérateur revendiqué) |
| Sécurité production | CI 9 jobs (gitleaks, SCA, couverture 90 %, restauration synthétique, E2E), 2FA admin exigible, passthrough compose contrôlé en CI, CSP `frame-ancestors 'none'` par défaut | E2E positifs licences admin ; vérification de l'activation réelle du MFA admin sur le VPS (dépend du déploiement) |
| OCR / assistant IA | — (aucune trace de stack OCR/LLM dans le code) | Tout (P2 : provenance, confiance, correction humaine obligatoires) |
| Dossier de financement | — | Tout (P2) |
| UX premium / offline | PWA hors connexion chiffrée (KF-17 corrigé), i18n FR/EN, recettes FR/EN ordinateur+mobile documentées | Preuves accessibilité/3G (KF-21), notifications |
| OHADA multi-pays | SYSCOHADA révisé 2017 + fiscalité GN (`fiscal_defaults_gn.py`, `syscohada_revise_2017.csv`) | Versionnement du référentiel, paramètres par pays, devises, langues (P3) |

## 3. Environnements

| Environnement | État | Preuve |
|---|---|---|
| DEV (recette locale sans Docker) | Pile PG 54330 / Redis 63790 / S3 9000 opérationnelle après réparation (venv + répertoires runtime PG) ; scripts idempotents ajoutés au dépôt | `scripts/recette-sans-docker/` (PR séparée) |
| REC | Non accessible depuis ce bac à sable — aucune affirmation d'état | — |
| PROD | Non accessible ; correctifs #204/#207/#208 non encore déployés selon le worklog 2026-11-25 | worklog.md (2026-11-25) |

## 4. Backlog dédoublonné (P0 → P3)

Colonnes : backend / frontend / tests / sécurité / déploiement — « ✔ » livré,
« ◐ » partiel, « ✗ » absent, « n/a » sans objet.

| ID | P | Domaine | Sujet | Bk | Fe | Te | Sé | Dép | Action | Preuve |
|---|---|---|---|---|---|---|---|---|---|---|
| PROD-1 | P0 | Production | Déployer #204/#207/#208/#209/#210 puis vérifier santé conteneurs, migrations, sauvegardes, rollback | n/a | n/a | n/a | n/a | ✗ | Opérateur : déploiement versionné + tests de restauration post-déploiement (autorisation explicite requise) | worklog 2026-11-25 |
| SEC-1 | P0 | QA admin | E2E Playwright positifs de l'administration des licences (anti-régression #207) | n/a | ✗ | ✗ | ◐ | n/a | Spéc E2E FR/EN : liste, suspension, réactivation, renouvellement, conflit 409 | e2e : seul `administration-modules.spec.ts` existe |
| SEC-2 | P0 | Sécurité | Vérifier l'activation réelle de `KORA_PLATFORM_ADMIN_REQUIRE_MFA` sur l'environnement déployé (après PROD-1) | ✔ | ✔ | ✔ | ◐ | ✗ | Contrôle post-déploiement (connexion admin sans 2FA → refus) | #202 + #208 |
| IMP-1 | P1 | Import | Prévisualisation persistée du rapport de précontrôle (lectures paginées) | ◐ | ✗ | ◐ | ✔ | n/a | Persister le rapport, route GET paginée, écran de revue | 0026 + precheck existants |
| IMP-2 | P1 | Import | Confirmation humaine → génération transactionnelle de brouillons (aucune écriture validée auto, idempotence par batch) | ✗ | ✗ | ✗ | ✔ | n/a | Lot principal Phase 2 : service + routes + écran + tests de concurrence et d'invariants | architecture import existante |
| IMP-3 | P1 | Import | Annulation d'un batch non validé, gestion des conflits/reprises | ✗ | ✗ | ✗ | ✔ | n/a | Après IMP-2 | — |
| IMP-4 | P1 | Import | Tests inter-entreprises (isolation des batches et rapports) | ✗ | n/a | ✗ | ✔ | n/a | Avec IMP-2 | `test_isolation_tenants.py` comme modèle |
| CAB-1 | P1 | Cabinet | Espace cabinet multi-clients (portefeuille, filtres, statuts exercices, échéances, pièces manquantes, tâches révision) | ✔ | ✗ | ◐ | ✔ | n/a | Frontend + E2E sur les API firms/affectations existantes | `firms.py`, `test_permissions.py` |
| CAB-2 | P1 | Cabinet | Tests de séparation inter-cabinets + révocation d'accès collaborateur | ✔ | n/a | ◐ | ✔ | n/a | Étendre `test_isolation_tenants` au périmètre firms | — |
| SAAS-1 | P1 | Commercial | Catalogue versionné, essais, abonnements mensuels/annuels, factures, échéances, relances, résiliations | ✗ | ✗ | ✗ | ✔ | n/a | **Validation métier préalable** (tarifs, entité facturante, PSP) puis lots M6d… | 0027–0032 + tests existants |
| MOMO-1 | P1 | Trésorerie | Imports Orange Money / MTN MoMo, commissions, transferts internes, rapprochement assisté | ◐ | ✗ | ◐ | ✔ | n/a | Réutiliser relevés 0011–0015 ; connecteurs réels seulement après autorisation opérateur | `treasury.py` |
| IA-1 | P2 | IA | OCR justificatifs + assistant contrôlé (provenance, confiance, correction humaine, aucune écriture auto) | ✗ | ✗ | ✗ | ✗ | n/a | Étude d'architecture d'abord, puis lot piloté | §2 |
| FIN-1 | P2 | Financement | Dossier de financement (états, indicateurs, liens sécurisés expirables révocables, journal des consultations) | ✗ | ✗ | ✗ | ✗ | n/a | Réutiliser exports PDF existants + liens d'invitation comme modèle | — |
| UX-1 | P2 | UX | Preuves accessibilité + réseaux lents (KF-21), notifications | ◐ | ◐ | ✗ | n/a | n/a | Audits automatisés + E2E throttling | KF-21 |
| HYG-1 | P2 | Hygiène | Outbox durable + réconciliation S3 (KF-22 / N-B4) | ◐ | n/a | ◐ | n/a | n/a | Après IMP-2 (même périmètre transactionnel) | audit 2026-11-09 §2 |
| OHADA-1 | P3 | OHADA | Multi-pays : référentiel versionné, fiscalité par pays, devises, langues | ✗ | ✗ | ✗ | n/a | n/a | Après validation par professionnel qualifié du pays (règle projet) | §2 |
| MOD-1 | P3 | Modules | Stock, immobilisations, budgets, analytique, multidevise | ✗ | ✗ | ✗ | n/a | n/a | Selon demande pilote réel | §2 |

## 5. Tableau de pilotage (au 2026-11-27)

| Indicateur | Valeur |
|---|---|
| Version `main` | `71b2952f467db49fe49c2f49a16b7329449e24f2` |
| Dernière PR | #210 (fusionnée 2026-11-26) |
| CI/CD | run `45843916910` : 9/9 verts sur PR #210 ; couverture backend ≥ 90 % (#201) |
| DEV | Pile de recette locale sans Docker opérationnelle (PG/Redis/S3 + API + web) |
| REC | Non vérifiable depuis le bac à sable |
| PROD | Non vérifiable ; #204/#207/#208 en attente de déploiement (worklog 2026-11-25) |
| Backend | Complet : général, lettrage, clôture, états, ventes/achats, trésorerie/rapprochement, recouvrement, licences/modules, imports (dépôt+précontrôle) |
| Frontend | Parcours dossier complet + admin plateforme (licences/modules) + PWA hors connexion ; espace cabinet absent ; revue d'import absente |
| Tests | API > 100 fichiers (imports, licences, concurrence, isolation, restauration) ; E2E 17 specs (dont modules admin) ; manques : licences admin, cabinet, import pipeline |
| Sécurité | RLS/RBAC/MFA/audit/chiffrement au repos actifs et testés ; MFA admin exigible (#202) — activation déployée à confirmer (SEC-2) |
| Sauvegardes | Restauration synthétique en CI (digests, RLS, chaînes d'audit) ; dernier test PROD réel : non vérifiable |
| Migrations | 0032 (2026-11-23) |
| Commercialisation | Pilote non ouvert ; offres/licences/modules livrés ; facturation/paiement bloqués sur validation métier |
| Maturité | **78/100** — justifié : +produit livré étendu (ventes/achats/trésorerie/licences, §42-43), +CI complète avec plancher 90 %, +2FA admin, +restauration synthétique ; −PROD en retard sur main (PROD-1), −import pipeline incomplet (IMP-*), −espace cabinet absent (CAB-*), −facturation absente (SAAS-1) |
| Prochaine action | PROD-1 (opérateur) puis SEC-1 puis IMP-1/IMP-2 |

## 6. Limites du présent audit

- Bac à sable d'exécution sans accès au VPS ni à REC : aucune affirmation sur
  leur état ; PROD-1 reste une action opérateur.
- PRs ouvertes à re-vérifier à chaque session avec un jeton à périmètre limité.
- Le score de maturité est une évaluation d'audit, pas une certification : il
  ne vaut que pour `71b2952` et les preuves citées.
