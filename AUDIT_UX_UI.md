# Audit UX/UI de Kora Finance

Date : 2026-11-19 · Base : `main` `2c80da4` (après fusion du lot B-3, PR #101)
Périmètre : application web `apps/web` (37 pages, design system, i18n fr/en, PWA)
Méthode : revue statique du code front (structure, composants, patterns, libellés) —
aucune capture d'écran : l'environnement d'audit n'exécute pas de navigateur.
Limites : CI non confirmée (facturation GitHub Actions, blocage P0 connu) ; les
constats s'appuient exclusivement sur le code cité (fichiers et lignes).

## 1. Ce qui est déjà solide (à préserver)

| Domaine | Constat | Preuves |
|---|---|---|
| Couverture | 37 pages : auth publique, dossiers, comptabilité (écritures, balance, grand-livre, lettrage), trésorerie (relevés, prévisions, instantanés, réglages), tiers, ventes/achats, paramètres, audit, hors-ligne | `apps/web/src/app/**` |
| Design system | 8 primitives cohérentes (alert, badge, button, card, input, label, separator, table) ; `PageHeader`/`PageSkeleton` partagés | `src/components/ui/`, `src/components/page-header.tsx` |
| Mobile-first | Navigation horizontale défilante sur téléphone, sidebar sur `md:` ; tables avec wrapper `overflow-x-auto` | `dossiers/[companyId]/layout.tsx`, `ui/table.tsx:10` |
| Dark mode | Variant `dark` défini, palette oklch complète (`:root` + `.dark`) | `globals.css:5,86` |
| PWA / hors-ligne | Icônes 192/512/maskable/apple, service worker, écrans hors-connexion + saisie hors-ligne, bandeau de synchronisation | `public/icons/`, `components/offline/` |
| i18n | fr/en équilibrés (~1 230 lignes chacun), libellés acompte/avance/remboursement présents, interpolations typées | `src/lib/i18n/fr.ts` (738-745), `en.ts` |
| États vides | Soignés et **actionnables** (« Commencez par “J'ai vendu et j'ai été payé” »), hints par écran | `fr.ts:144-145,204,292` |
| Permissions | Nav filtrée par permission (`can()`), aucun lien mort pour les lecteurs | `dossiers/[companyId]/layout.tsx` |
| Feedback d'action | `InlineAction` avec `pendingLabel`/`showSuccess`, boutons de déconnexion avec confirmation | `components/forms/inline-action.tsx` |
| Accessibilité de base | `role="alert"` sur Alert, `aria-label="pagination"` sur la pagination des écritures, skeletons `aria-hidden` | `ui/alert.tsx`, `ecritures/page.tsx:180` |

## 2. Écarts constatés et priorités

### P1 — à traiter avant tout usage client (commercialisation)

**P1.1 · Aucun écran d'erreur applicatif (`error.tsx`).**
Seul `not-found.tsx` existe (`src/app/[lang]/not-found.tsx`). En cas d'échec
runtime (API indisponible, 500, réseau), l'utilisateur voit l'écran d'erreur brut
de Next.js, en anglais, sans moyen de réagir — sur des écrans sensibles
(comptabilisation, clôture), c'est rédhibitoire.
Remède : `error.tsx` (client component) à trois niveaux — `[lang]/error.tsx`,
`[lang]/(app)/error.tsx`, `dossiers/[companyId]/error.tsx` — avec message fr/en
i18n, bouton « Réessayer » (`router.refresh()`), et rappel du contact de support.
Effort estimé : ~2 h (y compris tests Vitest).

**P1.2 · Identité de marque absente de l'interface.**
`viewport.themeColor = "#0f766e"` (émeraude) et le titre « Kora Finance » portent
la marque, mais la palette d'interface reste le thème **shadcn neutre** :
`--primary: oklch(0.205 0 0)` (gris) — l'app paraît un gabarit sans identité, et
le mobile affiche une barre système émeraude au-dessus d'une UI grise
(incohérence visible dès le premier écran).
Remède : palette de marque émeraude appliquée aux tokens (`--primary`, `--ring`,
`--chart-1…5`, sidebar), déclinaison dark testée pour le contraste WCAG AA ;
favicon/icônes déjà présentes. Effort : ~3 h + revue visuelle sur la démo.

### P2 — qualité perçue et maintenabilité

**P2.1 · Absence de `loading.tsx` par segment lourd.**
Les skeletons existent (`PageSkeleton`) mais ne sont posés que manuellement dans
quelques layouts ; plusieurs pages serveurs (balance, grand-livre, ventes, achats,
trésorerie) affichent un écran blanc pendant le chargement avant de « sauter ».
Remède : `loading.tsx` réutilisant `PageSkeleton` sur les segments lourds
(listés ci-dessus). Effort : ~1 h.

**P2.2 · Pages ventes/achats monolithiques.**
`ventes/page.tsx` : 994 lignes ; `achats/page.tsx` : 693. Tout coexiste (documents,
règlements, acomptes, affectations, remboursements, transferts OD) : risque de
régression à chaque évolution, duplication ventes↔achats déjà présente.
Remède : extraire les blocs réutilisables (formulaire document, éditeur
d'affectation, remboursement, transfert OD) vers `components/sales/` et
`components/purchases/`, sans changement visuel — revue par diff. Effort : ~1 jour.

**P2.3 · Feedback des actions multiples peu visible sur les pages denses.**
Les confirmations passent par `showSuccess` inline ; sur une page de 900 lignes,
l'utilisateur peut manquer le succès d'une comptabilisation ou d'un envoi email.
Remède (léger, sans framework de toasts) : bandeau de confirmation contextuel sous
le `PageHeader` pendant quelques secondes + état du bouton. Effort : ~3 h.
Décision produit à valider avant d'ajouter une librairie de toasts.

### P3 — polissage

**P3.1 · Densité des tables professionnelles.** Comptables travaillent sur 15-30
lignes visibles : resserrer le padding (`py-1.5`) des tables denses
(balance, grand-livre) et aligner les montants à droite en police tabulaire
(`tabular-nums`).
**P3.2 · Contrastes à vérifier sur les badges secondaires et les bandeaux ambre**
(`bg-amber-50/amber-950`) en dark mode.
**P3.3 · Guide de style manquant** : documenter tokens (palette, radius, espacements)
et règles de rédaction (voix, terminologie OHADA) dans `docs/STYLE_UI.md` pour
garder la cohérence des prochains lots.
**P3.4 · Filtres de période** : harmoniser le composant de filtre (dates, exercice)
entre écritures, grand-livre et trésorerie (`ledger/period-filter.tsx` à généraliser).

## 3. Plan de lots proposés

| Lot | Contenu | Sortie |
|---|---|---|
| **UX-1** (P1) | `error.tsx` ×3 + palette de marque émeraude (light/dark) + i18n | PR, Vitest, build, ESLint |
| **UX-2** (P2) | `loading.tsx` par segment + extraction composants ventes/achats | PR, Vitest, build, ESLint |
| **UX-3** (P3) | Densité tables, contrastes, guide de style, filtres harmonisés | PR + `docs/STYLE_UI.md` |

Chaque lot : branche `feature/kora-ux-*`, tests et build locaux comme preuves,
mention « CI non confirmée » dans la PR, validation visuelle sur la démo Docker
(`make up && make seed`) avant fusion.

## 4. Ce que cet audit ne couvre pas

- Exécution réelle au navigateur (aucune capture : environnement sans navigateur) ;
- Backend/BFF (un audit des codes d'erreur API → messages UI est souhaitable) ;
- E2E Playwright — à envisager après UX-1 pour verrouiller les parcours critiques.
