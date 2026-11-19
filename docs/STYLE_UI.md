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

Palette OKLCH, thème clair (`:root`) et sombre (`.dark`). Trois règles :

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
