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
- **4A — Référentiel des tiers** ✅ (2026-11-13, branche `feature/kora-4a-referentiel` :
  table `partners` (client et/ou fournisseur, jamais supprimé, nom unique insensible à la
  casse), mentions obligatoires des factures dès la fiche (NIU/NCC ou NIF, RCCM, adresse),
  comptes de tiers par défaut 411x/401x validés par le service, RLS par dossier,
  permissions `partners:read`/`partners:manage`, page fr/en avec recherche, filtres et
  désactivation ; créer ou modifier un tier n'écrit rien en comptabilité).
- **4B — Devis, factures et avoirs à numérotation sans trou** ✅ (2026-11-14, branche
  `feature/kora-4b-factures` : migration 0017 `document_sequences`/`sales_documents`/
  `sales_document_lines`, compteur verrouillé FOR UPDATE et incrément dans la même
  transaction que l'émission — 100 émissions concurrentes = 100 numéros consécutifs
  testés sur PostgreSQL réel, ROLLBACK après échec post-incrément = compteur restauré ;
  brouillons jamais numérotés, annulation numéro conservé, avoir annulateur ;
  mentions légales figées dans des instantanés JSONB à l'émission ; permissions
  `sales:read`/`sales:manage`, page Ventes fr/en ; aucun chemin n'écrit en
  comptabilité — l'intégration est la Phase 4E).
- **4B-bis — PDF conforme des documents de vente** ✅ (2026-11-15, branche
  `feature/kora-4b-bis-pdf` : PDF des documents numérotés rendu exclusivement depuis
  les instantanés figés (émetteur, tier, taux datés, montants) — raison sociale,
  NIU/NCC, RCCM, adresses, HT / TVA / TTC décomposés par taux, référence de
  l'exercice, timbre des documents annulés/refusés, mention « Annule et remplace »,
  numéro d'affichage FAC/DEV/AV-année-00042 ; route API `sales:read` avec quota
  d'exports et audit `sales_document.exported`, bouton PDF fr/en via BFF ;
  **règle dure à l'émission** : facture et avoir refusent de naître sans NIU/NCC et
  adresse du client, NIF et adresse de l'émetteur — le devis reste averti ;
  corrections d'hygiène : registre Alembic complet (`alembic check` rétabli) et
  `uv.lock` réaligné).
- **4C — Règlements clients et lettrage commercial** ✅ (2026-11-17, branche
  `feature/kora-4c-reglements-lettrage` : migration 0018 `sales_payments`/
  `sales_payment_allocations` (RLS, FK composites), règlement = encaissement
  affecté à une ou plusieurs factures émises du même tier, montant recalculé =
  somme des affectations, solde restant dû TTC − affectations − avoirs partiels
  émis calculé en lecture (aucun statut dérivé stocké) ; contrôle du solde sous
  verrou FOR UPDATE des factures, ordre trié sans interblocage — 20 règlements
  concurrents de 1 000 sur TTC 10 000 = 10 succès + 10 refus, somme lettrée
  exactement 10 000 ; interlock : une facture lettrée ne s'annule pas (règlements
  à supprimer d'abord, journalisés) ; routes `/payments` et `/receivables/aging`
  (balance âgée en cinq buckets à date arbitraire), `DocumentOut` enrichi
  additivement (`outstanding_ttc`, `payment_status`) ; permissions
  `sales:read`/`sales:manage` réutilisées, audit `sales_payment.created`/`deleted`,
  zéro écriture comptable (4E à venir) ; page Ventes fr/en : solde dû, règlements,
  formulaire d'encaissement Mobile Money en tête, balance âgée).

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
