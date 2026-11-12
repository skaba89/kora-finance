# Plan de livraison Kora Finance

Plan validé par l'utilisateur le 2026-10-23. Cahier des charges : `docs/CAHIER_DES_CHARGES.md`.
Chaque phase se termine par : CI verte, build OK, `CLAUDE.md` et `worklog.md` à jour,
résumé livré/restant. Les phases 1 et 2 sont découpées en sous-livrables testables ;
les phases suivantes sont détaillées au moment de les démarrer.

## Phase 0 — Fondations du dépôt ✅
Monorepo, docker-compose, CI bloquante, linters, harnais de tests (pytest sur vrai
Postgres, Vitest, Playwright), `CLAUDE.md`, `worklog.md`.
- Critère : `docker compose up` démarre la pile ; un test cassé fait échouer la CI.

## Phase 1 — Socle ✅ (2026-10-23)
Auth (JWT + refresh tokens rotatifs avec détection de réutilisation, 2FA TOTP,
verrouillage après N échecs), rate limiting, tenants + memberships + RBAC 7 rôles,
création d'entreprise (RCCM, NIF, forme juridique, devise), exercices, plan SYSCOHADA
révisé préchargé et personnalisable, taxes paramétrables datées, journal d'audit chaîné
SHA-256, squelette PWA fr/en.
- Tests cross-tenant sur 100 % des routes.
- Une ligne d'audit altérée en base est détectée par le vérificateur.
- Le N-ième mot de passe erroné verrouille le compte.
- Matrice rôle × permission entièrement testée.

## Phase 2 — Comptabilité générale et états financiers
Journaux, saisie en partie double, saisie guidée, pièces jointes, lettrage, verrouillage
de période, clôture/réouverture, à-nouveaux, balance, grand livre, bilan, compte de
résultat, TFT, exports PDF/Excel, saisie hors-ligne des brouillons.
- Tests par propriétés : aucune séquence d'opérations ne produit de déséquilibre.
- Bilan actif = passif ; résultat du CR = résultat du bilan.
- Les à-nouveaux reproduisent exactement le bilan de clôture.
- Jeu de données de référence validé par un expert-comptable.

Découpage (2026-10-24) :
- ✅ **2a** Journaux, écritures en partie double (brouillon → validée), numérotation sans
  trou par journal et exercice, écritures validées immuables (contre-passation), saisie web.
- ✅ **2b** Balance générale et grand livre (agrégats SQL paginés).
- ✅ **2c** Lettrage des comptes de tiers.
- ✅ **2d** Verrouillage de période, clôture / réouverture d'exercice, à-nouveaux.
- ✅ **2e** Bilan et compte de résultat (référentiel d'affectation versionné, à valider par un expert).
- ✅ **2e-bis** Tableau des flux de trésorerie, méthode directe (arbitrage : `docs/ARBITRAGE_COMPTABLE.md`).
- ✅ **2f** Exports PDF et Excel.
- **2g1** Pièces justificatives (stockage S3 chiffré). ✅
- **2g2** Saisie guidée pour non-comptables (« j'ai payé une facture », « j'ai reçu un paiement »). ✅
- **2g3a** ✅ Saisie hors connexion (libre et guidée) avec synchronisation en brouillons.
- **2g3b** Photos de pièces justificatives prises hors connexion.
- **2h** ✅ Tableau de bord (indicateurs, trésorerie par compte, évolution mensuelle, raccourcis) et accueil direct (2026-10-27).

Ordre validé le 2026-10-27 : tableau de bord, puis phases 3 → 8 dans l'ordre.

## Phase 3 — Trésorerie, Mobile Money et rapprochement
Comptes bancaires, caisses, portefeuilles (adaptateur par opérateur), import CSV/Excel
avec détection du format (PDF au cas par cas, limites signalées explicitement),
rapprochement avec score de confiance et validation manuelle, frais et retraits,
prévisionnel 30/60/90 jours.
- Précision/rappel du rapprochement mesurés sur des relevés réels anonymisés.
- Réimport du même relevé = zéro doublon.
- **3E — Prévisionnel 30/60/90 jours** ✅ (2026-11-12, branche `feature/kora-cashflow-forecast` :
  moteur OBSERVE + ENGAGE + ESTIME à trois scénarios, détection de tension, instantanés
  figés comparables au réalisé, exports PDF/Excel audités, page mobile-first fr/en ;
  arithmétique 100 % entière, aucun flux futur inventé).

## Phase 4 — Ventes et achats
Devis, factures, avoirs à numérotation sans trou, PDF avec mentions légales, envoi
email/WhatsApp, relances, balance âgée.
- 100 créations concurrentes = 100 numéros consécutifs.

## Phase 5 — Import et migration
FEC, Excel, balance d'ouverture en tâche de fond, rapport de contrôle.
- 100 000 lignes importées sans timeout, rapport exhaustif.

## Phase 6 — Dossier de financement
Pack généré en un clic, lien signé, révocable et expirable, journal des consultations.
- Un lien révoqué renvoie 410 et ne donne plus accès à aucun document.

## Phase 7 — Assistant IA
Catégorisation avec apprentissage, agent d'audit et verdict de signabilité, questions en
langage naturel via des métriques paramétrées (jamais de SQL libre).
- Aucun chemin de code ne crée d'écriture depuis l'IA sans confirmation humaine (testé).

## Phase 8 — Espace cabinet et abonnements
Tableau de bord de portefeuille, affectation des collaborateurs, plans et limites,
période d'essai, paiement Mobile Money et carte, webhooks idempotents.
- 10 rejeux du même webhook = 1 seul débit.
