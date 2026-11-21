# Style UI — conventions du front Kora Finance

Ce document fixe les conventions visuelles et comportementales du front
(`apps/web`). Il matérialise l'audit UX/UI (P3) : chaque règle est une décision,
pas une préférence. Toute nouvelle page ou composant doit s'y conformer ; toute
dérivation doit être justifiée ici.

## 1. Principes

1. **Server-first** : les pages sont des Server Components ; le JavaScript client
   se limite à ce qui a besoin d'interactivité (`InlineAction`, `LocaleSwitcher`,
   `OfflineSync`). La composition d'une page = chargement de données, résolution
   des permissions, assemblage de composants (voir `ventes/page.tsx` : 171 lignes
   qui délèguent à `@/components/sales/`).
2. **Mobile-first** : navigation latérale en desktop, barre horizontale défilante
   en téléphone ; le contenu passe avant la navigation.
3. **Fonctionne sans JavaScript** : les filtres et les formulaires de consultation
   sont des `<form method="get">` — l'état reste partageable par URL.
4. **i18n systématique** : tout libellé passe par le dictionnaire (`fr.ts`, `en.ts`,
   type `Dictionary = typeof fr`) ; aucun texte codé en dur dans le JSX. Les
   composants serveur reçoivent `t` en prop ; les composants non serveurs utilisent
   `getClientDictionary()` (boundaries framework uniquement).
5. **Permissions dans le rendu** : les actions sont conditionnées par `can(company,
   permission)` ; la nav du dossier est filtrée par le layout (`[companyId]/layout.tsx`).

## 2. Tokens de couleur (globals.css)

Palette OKLCH et hexadécimale, thème clair (`:root`) et sombre (`.dark`). Trois règles :

- **Contraste AA obligatoire (4.5:1)** pour tout texte de taille normale, en clair
  comme en sombre. Le script `scripts/front-audit-contraste.py` vérifie les paires
  réellement rendues par les primitives (`python3 scripts/front-audit-contraste.py`
  — pur Python standard, aucune dépendance) ;
- les composants n'utilisent **jamais** de texte clair sur fond `--destructive`
  plein : ils posent du texte `text-destructive` sur fond neutre teinté 10 %
  (`bg-destructive/10`) ; hover 15 % — valeurs calibrées pour 4.5:1 ;
- `--primary`, `--ring`, `--sidebar-primary` et `--chart-1..5` portent l'identité
  de marque ; les déclinaisons dark doivent conserver un contraste AA avec leur
  foreground.

Nouveau token = nouvelle ligne dans `:root` ET dans `.dark`, puis paire ajoutée
au script d'audit. `--chart-1..5` : bleu puis orange d'abord (série mensuelle du
tableau de bord), teintes de marque ensuite.

## 3. Structure d'une page

```
<PageHeader title subtitle actions />   <- titre h1 + sous-titre + action principale
<p class="text-muted-foreground -mt-4 mb-4 text-xs">…notice expert…</p>
[filtres GET]
<Table>…</Table>                        <- données
<Cartes d'action>…</Cartes>             <- formulaires server action
```

- `PageHeader` est systématique ; `PageSkeleton` sert de fallback `Suspense` et
  de `loading.tsx` (les trois niveaux de segments en possèdent un, géométriquement
  identique à la page cible) ;
- les formulaires de saisie utilisent `ActionForm` + `Field`/`SelectField` ;
  les actions unitaires par ligne utilisent `InlineAction` (pendingLabel +
  showSuccess, pas d'`alert()` ni de `useState` manuel) ;
- un bandeau de confirmation sous le `PageHeader` (`<p class="…text-xs">`) éclaire
  l'utilisateur sur la séparation saisie/comptabilisation — présent sur ventes,
  achats, écritures.

## 4. Tables

- `tabular-nums` est appliqué au niveau de la primitive `Table` : les montants,
  dates et numéros s'alignent verticalement — exigence comptable ;
- montants alignés à droite (`className="text-right"` sur `TableHead`/`TableCell`),
  numéros de documents en `font-mono text-xs`, tirets « — » pour les valeurs
  nulles (jamais de cellule vide) ;
- l'en-tête utilise toujours `TableHead` (jamais un `div`), les listes longues
  paginent côté serveur (`pageHref` reconstruit la query).

## 5. Filtres de période

Le composant `PeriodFilter` (`components/ledger/`) est le **seul** patron autorisé
pour un filtre exercice + dates : select d'exercice, champs « du » (optionnel) et
« au », bouton « Afficher », champs additionnels en `children`. Les états qui ne
se lisent qu'à une date d'arrêté (bilan, résultat, flux) omettent `dateFrom`.

Utilisateurs actuels : grand-livre, balance, états financiers (3 vues).
À venir : toute nouvelle page d'états doit l'utiliser ; la page écritures en
recevra un quand le DAL exposera `date_from`/`date_to` (évolution API, hors lot UI).

## 6. États vides et chargement

- état vide = une phrase actionnable (`t.sales.empty`), jamais un écran blanc ni
  une table sans ligne ;
- chargement = `loading.tsx` par segment + fallbacks `Suspense` dans les layouts ;
  aucune donnée ne fait apparaître une table vide pendant le chargement ;
- erreurs = boundaries `error.tsx` (trois niveaux) + `ErrorScreen` : navigation
  parente conservée, bouton Réessayer, détails techniques repliés pour le support.

## 7. Accessibilité

- contrastes AA vérifiés numériquement (§2) ;
- `role="alert"` sur les messages d'erreur bloquants ; `aria-label` sur les
  contrôles sans libellé visible (selects de filtres, pagination) ;
- focus visible coloré (`--ring`) ; la navigation principale a
  `aria-label` (`t.nav.mainMenu`) ;
- les icônes décoratives portent `aria-hidden`.

## 8. Ce qui est interdit

- texte codé en dur (fr ou en) dans le JSX ;
- `useEffect` pour un rendu qui peut être serveur ;
- `useState`/`useActionState` pour une action déjà couverte par `InlineAction` ;
- couleurs brutes (`text-teal-700` par exemple) hors tokens quand une classe de
  token existe — `text-teal-700` n'est toléré que sur le logo de l'en-tête ;
- nouveaux `loading.tsx` ou skeletons qui ne reprennent pas la géométrie de la
  page cible (cause de sauts visuels).

## 9. Preuves attendues d'un lot UI

Comme tout lot : Vitest verts, `next typegen && tsc --noEmit` à zéro,
ESLint `--max-warnings=0`, `next build` OK — et pour tout changement de token ou
de primitive, la sortie du script d'audit de contraste jointe à la PR.

## 10. Kora Finance Premium — fondations UX/UI

Lot 1, base `ce89b41` (PR #110). Le design se superpose au produit livré : aucun
changement de calcul, permission, API, migration, session ou synchronisation.

### Tokens et règles

| Usage | Clair | Sombre |
|---|---|---|
| Fond | #F8FAFC | token background existant |
| Texte principal | #0F172A | token foreground existant |
| Primaire | #0F766E | émeraude claire existante |
| Succès | #166534 | #86EFAC |
| Avertissement | #92400E | #FCD34D |
| Information | #1D4ED8 | #93C5FD |

Inter variable, auto-hébergée par Next Font ; repli système. Références techniques
en monospace système. Montants en `tabular-nums`, alignés à droite dans les colonnes
monétaires ; conserver exclusivement les chaînes/BigInt existants. Ne jamais
utiliser la couleur seule pour communiquer un état. Le thème sombre a des tokens
mais son sélecteur et sa recette complète restent à réaliser.

Titres 24 px mobile / 30 px desktop, sous-titre 14 px, cartes 16 px, navigation
14 px. Espacements sur grille de 4 px ; rayon de base 10 px. Conteneur connecté
jusqu'à 1536 px, navigation mobile accessible et défilante, navigation de bureau
sur panneau dédié. Respecter le mouvement réduit et le focus visible.

### Inventaire de continuité

37 fichiers page.tsx ; modules : authentification (7 écrans), dossiers et compte,
tableau de bord, écritures, saisie guidée, balance, grand livre, lettrage, états
financiers, trésorerie et prévisions, tiers, ventes, achats, audit, paramètres,
hors connexion. Primitives existantes : Alert, Badge, Button, Card, Input, Label,
Separator, Table. PageHeader, PageSkeleton, FlashBanner, NavLink et OfflineSync
sont conservés. La PR #110 a déjà livré le parcours Ventes par onglets.

Contrôle des permissions : `can(company, permission)` dans la navigation du dossier ;
les Server Actions et le BFF restent la source de vérité avec l'API et la RLS.

### Suite priorisée

1. Recette visuelle avant/après sur une pile de démonstration (360, 390, 768,
   1024, 1440, 1920 px), contrastes et clavier ; ne pas certifier WCAG sans audit.
2. AppShell et navigation par domaines, amélioration mobile, sélecteur d'entreprise,
   thème utilisateur ; conserver les routes et contrôler les permissions.
3. Dashboard et KpiCard réutilisable, vues métier ventes/achats/rapprochement,
   DataTable avec filtres, densité et actions contextuelles.
4. Parcours cabinet et fonctionnalités non encore livrées : ne pas simuler les
   intégrations, droits, notifications ou fonctionnalités métier absentes.
5. Mesures web vitals et tests utilisateurs avant tout score de maturité final.

Références de benchmark fonctionnel : Pennylane (pilotage), QuickBooks (filtres),
Xero (rapprochement), Odoo (modularité), Stripe (hiérarchie visuelle). Comparer
sur les mêmes tâches et mesurer le temps et les erreurs, pas seulement l'apparence.

### Lot 2A — navigation par domaines

Le modèle `company-navigation.ts` regroupe les routes existantes en Gestion
financière, Comptabilité et Paramètres avec 21 destinations au maximum.
Les permissions sont résolues avant la frontière serveur/client ; les groupes
vides disparaissent. La recherche accent-insensible porte exclusivement sur
les labels et groupes accessibles, sans appel API ni index de données client.
Raccourci Ctrl/Cmd+K pour focaliser la recherche, Échap pour effacer. Navigation
restant disponible sur mobile par défilement horizontal et filtrage. La recherche
de transactions et documents, le sélecteur d'exercice et la sidebar rétractable
sont hors de ce lot ; aucune interface simulée.

### Lot 2B — navigation responsive repliable

La navigation du dossier peut être compactée sur desktop (72 px, icônes et
libellés accessibles) et masquée sur mobile via un bouton à état annoncé.
Les deux états sont distincts : le passage d'un breakpoint à l'autre ne masque
pas accidentellement les liens desktop. Le raccourci Ctrl/Cmd+K réouvre la
navigation et focalise la recherche ; le repli efface le filtre. Par défaut les
liens restent visibles, y compris sur mobile. Aucun stockage de données ni
changement des permissions. Le nom du dossier et le rôle restent accessibles
en mode compact. Captures des deux états dans le rapport Playwright desktop/mobile.

### Lot 3A — tableau de bord financier

`KpiCard` reçoit une valeur déjà formatée (aucun calcul ni arrondi), un libellé,
une icône décorative, un contexte et éventuellement un lien autorisé. Les six
indicateurs existants sont conservés : trésorerie, CA, charges, résultat, créances,
dettes. Grille 1/2/3 colonnes, montants tabulaires et retours à la ligne si nécessaire.
La trésorerie se distingue visuellement ; les montants négatifs conservent leur
signe et leur teinte sémantique. Les raccourcis métier ont des cibles tactiles
de 48 px ; comptes et écritures restent lisibles sans troncature des montants.
Le graphique conserve ses séries et l'échelle BigInt ; grille de lecture,
activation au clavier/toucher et tableau défilant localement.

Le scénario E2E comptable existant vérifie toujours les valeurs après vente
validée et dépense brouillon, puis le débordement global aux six résolutions
360, 390, 768, 1024, 1440 et 1920 px, avec captures. Aucun changement d'API,
de devise, de calcul, de rôle ou d'exercice. Le lot 2C est détaillé dans
`docs/UX_TOPBAR.md`.

### Lot 5A — ventes et recouvrement

Navigation par vues conservée (Documents, Encaissements, Recouvrement).
Filtres serveur existants et pagination 25/50/100 (défaut 100), densité
dans l'URL et réinitialisation réelle. Les documents gardent leur présentation
mobile, leurs actions et leur statut comptable. Le formulaire d'envoi email
porte sur les documents de la page courante. Les encaissements et top débiteurs
utilisent DataTable ; les quatre KPI de recouvrement réutilisent KpiCard avec
les valeurs et les ratios existants. Aucune nouvelle règle de gestion.

### Lot 4A — DataTable comptable (écritures)

`DataTable` conserve le balisage HTML natif et expose une zone de défilement
clavier avec en-têtes fixes, montants tabulaires à droite et deux densités.
La liste des écritures conserve les liens directs et RBAC ; recherche, journal,
statut et exercice sont évalués par l'API existante sur l'ensemble des données.
La taille de page (25/50/100, défaut 50) et la densité sont dans l'URL ; les
liens de pagination préservent les critères. Un état vide et le retour aux
filtres par défaut sont explicites. Statut et référence restent visibles sur mobile.
Le tri serveur par date décroissante est annoncé via `aria-sort` ; aucun tri
partiel trompeur côté client. Les exports PDF/Excel couvrent l'exercice complet
sélectionné (ou courant), indépendamment des filtres de la page.

Le tri configurable global, les colonnes personnalisables et la migration
progressive des autres tableaux restent à livrer. Aucun changement de route
API, de schéma, de permissions ni de précision des montants.

### Lot 4B — balance, grand livre et lettrage

La balance et le grand livre réutilisent `DataTable`, y compris l'en-tête
complet fixe à deux lignes de la balance. Les fiches mobiles restent disponibles
sans duplication visible du tableau. `TableDensitySelect` permet de régler
la densité dans les filtres de période ; les critères restent dans l'URL.
Le grand livre propose 25/50/100 lignes (100 par défaut) ; le lettrage conserve
ses pages de 200 et une sélection unique, avec cibles tactiles et état sélectionné.
Les totaux, soldes, exports, droits et actions métier existants sont conservés.
Les scénarios Playwright couvrent les montants et le lettrage, avec captures.

### Lot 5B — achats et fournisseurs

Raccourcis vers les documents, décaissements et échéancier ; création accessible
depuis le PageHeader pour les rôles autorisés uniquement. Table des documents
avec nom fournisseur si disponible, référence, statut, densité et pagination
serveur 25/50/100 (défaut 50). Une seule instance des actions : les lignes
deviennent des fiches sur téléphone. Les sélecteurs de règlements restent liés
à la page de documents, avec périmètre annoncé en FR/EN. DataTable pour les
décaissements et les tranches d'ancienneté, KpiCard pour le total des dettes
fourni par l'API. Aucune modification de calcul, de permission ni de mutation.

### Lot 6A — trésorerie et rapprochement

Les cinq tableaux de trésorerie utilisent DataTable : en-têtes fixes, défilement
local accessible au clavier et montants tabulaires. Le compte actif est signalé
visuellement et par aria-current. Le libellé du mouvement reste visible sur
mobile. Les cinq indicateurs de rapprochement utilisent KpiCard et les valeurs
de l'API sans recalcul. Les relevés restent consultables en lecture seule ; les
mutations restent réservées à treasury:manage. Les champs des mouvements ont
des identifiants distincts des formulaires de création et de virement.
