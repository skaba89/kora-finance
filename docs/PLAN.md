# Plan de livraison Kora Finance

Plan validé par l'utilisateur le 2026-10-23. Cahier des charges : `docs/CAHIER_DES_CHARGES.md`.
Chaque phase se termine par : CI verte, build OK, `CLAUDE.md` et `worklog.md` à jour,
résumé livré/restant. Les phases 1 et 2 sont découpées en sous-livrables testables ;
les phases suivantes sont détaillées au moment de les démarrer.

## Phase 0 — Fondations du dépôt ✅
Monorepo, docker-compose, CI bloquante, linters, harnais de tests (pytest sur vrai
Postgres, Vitest, Playwright), `CLAUDE.md`, `worklog.md`.
- Critère : `docker compose up` démarre la pile ; un test cassé fait échouer la CI.

## Phase 1 — Socle
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

## Phase 3 — Trésorerie, Mobile Money et rapprochement
Comptes bancaires, caisses, portefeuilles (adaptateur par opérateur), import CSV/Excel
avec détection du format (PDF au cas par cas, limites signalées explicitement),
rapprochement avec score de confiance et validation manuelle, frais et retraits,
prévisionnel 30/60/90 jours.
- Précision/rappel du rapprochement mesurés sur des relevés réels anonymisés.
- Réimport du même relevé = zéro doublon.

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
