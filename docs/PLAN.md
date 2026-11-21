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
- **4D — Relances de factures échues** ✅ (2026-11-17, branche
  `feature/kora-4d-relances` : migration 0019 `sales_reminders` (RLS forcée, FK
  composites, unicité (dossier, facture, jour du rappel)) ; une relance vise une
  facture ÉMISE, ÉCHUE (échéance passée à la date du rappel) et non soldée
  (même calcul du solde qu'en 4C) ; le niveau (1re, 2e, 3e relance…) est compté
  par le service sous verrou FOR UPDATE de la facture — jamais saisi ; deux
  courses concurrentes se sérialisent sur le verrou : 20 relances concurrentes
  le même jour = 1 création + 19 refus 409 ; relance immuable (aucune
  suppression ni modification — le contrat n'expose que GET/POST) ; l'email
  français au client part dans le worker (jamais pendant la requête) : une panne
  de la file n'annule pas la relance, `email_queued` porté par la réponse et
  renvoi journalisé depuis l'historique ; adresse destinataire figée à l'envoi
  (traçabilité) ; routes `/receivables/overdue` (candidates : retard, historique,
  email du tier), `/reminders` et `/reminders/{id}/resend`, `DocumentOut`
  enrichi additivement (`reminders_count`) ; WhatsApp : évolution future (canal
  borné à EMAIL par CHECK) ; zéro écriture comptable (4E à venir) ; page Ventes
  fr/en : factures échues candidates, formulaire de relance (message
  personnalisé facultatif), historique avec renvoi).
- **4D-bis — Envoi du document de vente par email avec son PDF** ✅ (2026-11-18,
  branche `feature/kora-4d-bis-email-document` : migration 0022
  `sales_document_emails` (RLS forcée, FK composites, envoi immuable) ; un envoi
  vise un document numéroté (facture/avoir ÉMIS, devis envoyé/accepté/refusé) —
  un brouillon n'a ni numéro ni PDF (409), une facture annulée ne part pas (409)
  et un envoi déjà en file pour une facture annulée entre-temps est abandonné
  dans le worker sans réessai ; destinataire = adresse explicite de la demande,
  sinon l'email de la fiche du tier (sans l'un ni l'autre : refus clair) ;
  contrairement à la relance (4D), pas d'unicité quotidienne — le client peut
  redemander l'exemplaire, chaque envoi est enregistré et journalisé
  (`sales_document.emailed`) ; le PDF joint est rendu dans le worker depuis les
  instantanés figés à l'émission (4B-bis, jamais les fiches vivantes) ;
  `OutgoingEmail` porte désormais des pièces jointes (base64 dans la file JSON,
  réhydratation dans le worker) ; routes `POST /sales/{id}/email` et
  `GET /sales/{id}/emails` (contrat 113→115 chemins, 188→192 schémas, pur
  ajout), permissions `sales:manage` (envoi) et `sales:read` (historique) ;
  gabarit d'email fr/en ; aucune écriture comptable (garde-fou retesté) ; page
  Ventes fr/en : carte « Envoyer un document par email » (document, destinataire
  facultatif, message facultatif) avec renvoi possible).
- **B2 — Relances automatiques configurables** ✅ (2026-11-19, branche
  `feature/kora-b2-relances-auto` : Phase B lot 2 de la mission DataSphere ;
  migration 0023 `sales_reminder_policies` (RLS forcée, UNE politique par
  dossier — upsert audité `sales_reminder_policy.updated`) et
  `sales_reminders.created_by_user_id` rendu nullable (origine système) ;
  échéancier d'escalade `offsets_days` — 1 à 6 seuils, entiers 1..365,
  strictement croissants, ex. [1, 7, 15] = 1re relance à J+1, 2e à J+7, 3e à
  J+15 ; le planificateur (`python -m kora.worker.scheduler`, service compose
  `scheduler`, `KORA_REMINDER_SCAN_INTERVAL_SECONDS` 3 600 s) enfile un
  balayage (`scan_automatic_reminders`, fan-out depuis `companies` hors RLS)
  qui exécute la politique de chaque dossier sous tenant lié
  (`run_reminder_policy`, échec fermé) ; réutilise TOUTES les règles 4D :
  facture ÉMISE/ÉCHUE/non soldée, niveau compté sous verrou FOR UPDATE,
  unicité (dossier, facture, jour) — un balayage doublé ou une relance
  manuelle du même jour ne crée jamais de doublon, rattrapage d'un niveau par
  jour, arrêt au dernier seuil ; re-contrôles sous verrou (statut, échéance,
  solde, email) avec points de sauvegarde par relance ; audit
  `sales_reminder.auto_created` (origine "automatique", auteur NULL) ;
  routes `GET/PUT /reminders/policy` (contrat 115→116 chemins, 146→148
  opérations, 192→194 schémas, pur ajout) ; aucune écriture comptable
  (garde-fou retesté) ; page Ventes fr/en : carte « Relances automatiques »
  (lecture pour tous, réglage `sales:manage`).
- **4E — Intégration comptable des ventes** ✅ (2026-11-18, branche
  `feature/kora-4e-comptabilisation` : migration 0020 colonnes de liaison
  `sales_documents.entry_id` et `sales_payments.entry_id` (FK composites RESTRICT
  vers `journal_entries`, NULL tant que non comptabilisé) ; la comptabilisation
  est un **acte explicite du comptable** (permission `entries:post`), jamais
  automatique — aucune émission, aucun règlement, aucune relance n'écrit en
  comptabilité (garde-fou maintenu et retesté) ; facture émise → écriture
  validée du journal des ventes (débit 411x au TTC, crédit du compte de produits
  701 choisi au HT, crédit du compte collecté de chaque taux — 4431 pour la TVA
  normale), avoir → écriture inverse, règlement → écriture du journal de
  trésorerie selon le mode (571 caisse au journal CA, 521 banque aux journaux
  BQ/MM) créditée au compte de tiers ; comptes résolus dans le plan du dossier :
  compte client par défaut de la fiche (411x), sinon 411 ; la date de l'écriture
  est le fait générateur (issued_on / paid_on) — exercice ouvert exigé (refus
  dans un exercice clôturé ou verrouillé) ; montants issus des instantanés
  d'émission, jamais recalculés ; 20 comptabilisations concurrentes de la même
  facture = 1 écriture + 19 refus 409 (verrou du document) ; interlocks : un
  règlement comptabilisé ne se supprime qu'après contre-passation de son
  écriture, une facture comptabilisée ne s'annule qu'après contre-passation ;
  routes `POST /sales/{id}/entry` et `POST /payments/{id}/entry`, `DocumentOut`/
  `PaymentOut` enrichis additivement (`entry_id`) ; taux sans compte collecté
  refusé avec un message clair ; page Ventes fr/en : badge « Comptabilisée » et
  bouton Comptabiliser sur les documents émis et les encaissements).
- **4F — Achats : factures fournisseurs, décaissements et lettrage** ✅ (2026-11-18,
  branche `feature/kora-4f-achats` : miroir complet du cycle de vente appliqué aux
  dépenses — migration 0021 `purchase_documents`/`purchase_document_lines`/
  `purchase_payments`/`purchase_payment_allocations` (RLS forcée, FK composites,
  `entry_id` dès la création sur le modèle 0020) ; le compteur `document_sequences`
  s'élargit aux types `supplier_invoice`/`supplier_credit_note` (doc_kind 16→24
  caractères), même numérotation sans trou (FACH/AVF) : 100 émissions concurrentes =
  100 numéros consécutifs, ROLLBACK après échec = compteur restauré ; le numéro
  imprimé par le fournisseur est conservé séparément (`reference`, pièce
  justificative) ; règle dure des mentions fiscales étendue aux achats (NIU/NCC et
  adresse du fournisseur, NIF et adresse du dossier) ; le tier doit être
  fournisseur ; décaissements = somme stricte des affectations, solde restant dû
  TTC − affectations − avoirs partiels émis calculé en lecture, échéancier
  fournisseurs en cinq buckets ; comptabilisation explicite du comptable
  (`entries:post`) : facture → journal des achats AC (débit du compte de charge
  601 choisi au HT, débit du compte récupérable de chaque taux — 4452, crédit du
  compte de tiers 401x au TTC), avoir → écriture inverse, décaissement → journal
  de trésorerie selon le mode (CA/BQ/MM) débité au crédit du compte de tiers ;
  20 comptabilisations concurrentes = 1 écriture + 19 refus 409 ; interlocks
  symétriques avec contre-passation ; routes `/purchases`, `/purchase-payments`,
  `/payables/aging`, `/purchases/{id}/entry`, `/purchase-payments/{id}/entry`
  (contrat 104→113 chemins, 170→188 schémas, pur ajout strict : aucune définition
  existante modifiée) ; permissions `purchases:read`/`purchases:manage` réutilisant
  le modèle des ventes ; page Achats fr/en (documents, décaissements, échéancier,
  bouton Comptabiliser avec `entries:post`) ; garde-fou retesté : aucun chemin
  d'émission ni de décaissement n'écrit en comptabilité).
- **B3 — Acomptes clients, avances fournisseurs, trop-perçus, remboursements et
  affectation ultérieure** ✅ (2026-11-19, branche `feature/kora-b3-acomptes-avances` :
  migration 0024 `sales_refunds`/`purchase_refunds` (RLS forcée, `entry_id` RESTRICT)
  + colonne `entry_id` sur les affectations (couverture comptable) ; un règlement
  porte désormais un **reste non affecté** : acompte reçu sans facture (tier client
  exigé) ou trop-perçu sur facture — comptabilisé au 4191 (sinon parent 419 du
  référentiel préchargé), jamais au 411 ; miroir achats 4091/409 ; **affectation
  ultérieure** à cibles absolues idempotentes (répéter = no-op, hausse seule,
  disponible = montant − remboursements, soldes sous verrou FOR UPDATE, course
  concurrente testée) ; **remboursements** immuables bornés au disponible, interlocks
  contre-passation ; écritures explicites du comptable : règlement mixte (411x +
  419/4191), **transfert d'acompte** (débit 4191/crédit 411x, journal OD) et
  écriture de remboursement (débit 4191, crédit trésorerie) ; routes
  `/payments/{id}/allocations`, `/payments/{id}/refund`, `/payment-refunds/{id}`
  (+ `/entry`), `/payments/{id}/allocation-entry` et miroirs achats
  (contrat 116→126 chemins, 148→158 opérations, 194→200 schémas, pur ajout) ;
  pages Ventes et Achats fr/en (formulaire acompte/avance, badge « Non affecté »,
  affectation/remboursement inline, transfert OD) ; PaymentIn évolue
  rétrocompatiblement (allocations facultatif, amount et partner_id facultatifs) ;
  22 tests nouveaux + deux tests datés en dur corrigés à la racine (échéances
  dynamiques).)

- **B4 — Échéanciers clients, export de la balance âgée, indicateurs de
  recouvrement et DSO** ✅ (2026-11-20, branche `feature/kora-b4-recouvrement` :
  Phase B lot 4 de la mission DataSphere ; migration 0025
  `sales_payment_schedule_lines` (RLS forcée, FK composite CASCADE vers
  `sales_documents`, unicité (dossier, facture, tranche), montants strictement
  positifs) ; l'échéancier est un **outil de planification du recouvrement** —
  il n'écrit jamais en comptabilité et ne modifie jamais le solde ; le plan
  d'une facture est remplacé en bloc (PUT idempotent, tranches renumérotées
  1..N, maximum 24 tranches), la somme planifiée ne dépasse pas le solde
  restant dû (contrôlé sous verrou FOR UPDATE du document — sérialisé avec les
  règlements 4C : la course règlement/échéancier est testée) ; le statut des
  tranches est calculé en lecture : les encaissements lettrés couvrent les
  lignes dans l'ordre — réglée / en retard / à venir, à un as_of arbitraire ;
  routes `GET/PUT /sales/{id}/schedule` et `GET /receivables/schedules` (liste
  groupée du dossier, jamais N+1 requêtes), audit `sales_schedule.updated` ;
  indicateurs de recouvrement calculés en lecture depuis les mêmes soldes que
  la balance âgée 4C (`GET /receivables/kpis`) : encours, part échue en points
  de base, retard moyen pondéré, **DSO en jours de ventes** borné à la fenêtre
  (7..365 jours, 90 par défaut), **taux de recouvrement** = encaissements nets
  des remboursements B-3 ÷ factures émises de la fenêtre, top débiteurs (cinq
  tiers au plus fort solde avec leur retard maximum) ; export PDF/Excel de la
  balance âgée (`GET /receivables/aging/export`, permission `sales:read`) :
  une section par bucket, une ligne par facture non soldée, la même répartition
  que la route JSON, sous quota d'exports KF-13 et journalisé
  `export.generated` (contrat 126→130 chemins, 158→164 opérations, 200→208
  schémas, pur ajout) ; page Ventes fr/en : carte Échéanciers clients (plans
  statués + formulaire de planification de trois tranches), carte Indicateurs
  de recouvrement (DSO, taux, part échue, top débiteurs), boutons PDF/Excel
  sur la balance âgée ; 17 tests nouveaux (plan statué, ordre de couverture,
  refus de statuts, bornes, RLS, permissions, audit, course sur le verrou du
  document, dataset de KPIs à dates relatives, DSO borné, remboursements nets,
  export PDF/Excel et traçabilité).)
## Phase 5 — Import et migration
FEC, Excel, balance d'ouverture en tâche de fond, rapport de contrôle.
- 100 000 lignes importées sans timeout, rapport exhaustif.

**5A — Précontrôle structurel (premier incrément).** CSV normalisé UTF-8,
séparateur `;`, en-tête exact `journal;ecriture;date;compte;libelle;debit;credit`.
Dates ISO, montants en unités mineures entières (GNF sans décimale), identifiant
source unique par journal sur le fichier. Le libellé est celui de l'écriture,
identique sur ses lignes. Le groupe peut être non contigu. Les bornes de montant
et de lignes par écriture sont partagées avec le modèle comptable.
Le moteur de contrôle est sans effet de bord, limité à 100 000 lignes, et
retourne compteurs, totaux exacts des lignes structurellement valides et erreurs
numérotées sans données source. Une erreur de groupe invalide le rapport entier.
Rapport valide ne signifie pas écritures importables : il reste à vérifier le
plan comptable, les journaux, dates, exercices, droits et doublons en base.
Les adaptateurs FEC/Excel, limites de taille en octets et décodage des fichiers,
staging isolé, exécution asynchrone, idempotence et validation humaine sont
les incréments suivants ; aucun endpoint d'import ni écriture n'est ajouté en 5A.

**5B — Précontrôle FEC textuel.** Profil limité à 18 colonnes dans l'ordre
documenté par `FEC_COLUMNS`, UTF-8 avec BOM facultatif, tabulation ou barre
verticale choisie explicitement, sans échappement de séparateur. Limite de
32 Mio et de 100 000 lignes. Dates `AAAAMMJJ`, montants positifs ou nuls,
virgule ou point décimal, conversion exacte en unités mineures selon l'échelle
choisie (0 ou 2), sans arrondi. Les sept champs normalisés réutilisent le
contrôle 5A, dont le libellé identique par écriture. Les onze autres champs
ne sont pas validés et ne sont pas importés. Ce profil ne certifie pas la
conformité d'un FEC ; correspondances SYSCOHADA, devises, métadonnées et
conservation des pièces nécessitent un contrôle métier avant tout import.
Excel, staging et exécution restent à livrer.

**5C — Précontrôle Excel normalisé.** Classeur `.xlsx` à une seule feuille,
sept colonnes comme le CSV, identifiants et dates ISO en texte, montants en
unités mineures entières (cellules entières ou texte). Pas de conversion
flottante, formule, cellule fusionnée, macro ni lien externe. Plafonds de
16 Mio compressés, 64 Mio décompressés, 128 parties ZIP et 100 000 lignes.
Contrôle XML UTF-8 sans DTD ni entités avant lecture seule ; rejet des lignes
hors bornes et des colonnes supplémentaires. Réutilisation du contrôle 5A.
Ce lot n'expose aucune route et ne persiste aucune donnée ; le staging,
les droits, les contrôles métier et l'assistant d'import restent nécessaires.

**5D1 — Contrôle métier commun.** Le moteur structurel peut transmettre une
ligne normalisée à un contrôle pur (jamais une écriture en base). Un catalogue
en mémoire des journaux, comptes et exercices distingue codes inconnus,
désactivés, comptes de regroupement, exercices absents ou clôturés et périodes
verrouillées. Le rapport reste sans valeurs source ; les totaux restent ceux
du contrôle structurel. Le CSV en octets bénéficie aussi du plafond 32 Mio.
Le futur service doit charger le catalogue dans le contexte tenant autorisé,
contrôler les doublons persistants, la devise et revalider sous transaction
avant import. Aucun endpoint ni stockage ajouté dans ce lot.

**5D2a — Catalogue réel et accès tenant.** Le service de précontrôle résout
le rôle effectif sous un instantané REPEATABLE READ avec RLS et exige
`entries:write`. Tous les référentiels sont filtrés par tenant ; un dossier
inaccessible retourne 404, une permission insuffisante 403. Le premier
profil tenant exige une devise source explicitement déclarée GNF, identique
à la devise du dossier. Le parsing ne retient pas la connexion PostgreSQL.
Ce service ne crée aucune écriture ni route publique ; staging, doublons,
exécution et revalidation des droits restent à livrer.

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
