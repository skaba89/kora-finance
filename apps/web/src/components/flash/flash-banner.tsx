"use client";

import { useSyncExternalStore } from "react";

import { useFlash } from "@/components/flash/flash-context";

const subscribeNoop = () => () => {};

/**
 * Pathname réel du navigateur, relu à chaque rendu du composant : à la
 * navigation le banner re-rend et détecte la nouvelle page. Snapshot serveur
 * `null` : sûr pour le prerender (PPR), sans `usePathname` ni Suspense.
 */
function useBrowserPathname(): string | null {
  return useSyncExternalStore(
    subscribeNoop,
    () => window.location.pathname,
    () => null,
  );
}

/**
 * Bandeau de confirmation contextuel, rendu par `PageHeader` juste sous le
 * titre : visible même au milieu d'une page dense, effacé automatiquement
 * après quelques secondes ou par son bouton de fermeture. Ne s'affiche que
 * sur la page où le succès a eu lieu — il ne traîne pas sur la suivante.
 * Ne rend rien hors du `FlashProvider` (pages publiques) ni au prerender.
 */
export function FlashBanner() {
  const ctx = useFlash();
  const currentPath = useBrowserPathname();

  if (!ctx || !ctx.stored || ctx.stored.path !== currentPath) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="mb-6 flex items-start justify-between gap-3 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300"
    >
      <p className="font-medium">{ctx.stored.message}</p>
      <button
        type="button"
        onClick={ctx.hideFlash}
        aria-label={ctx.closeLabel}
        className="-mr-1 shrink-0 rounded p-1 leading-none text-emerald-700 hover:bg-emerald-100 dark:text-emerald-300 dark:hover:bg-emerald-900"
      >
        &times;
      </button>
    </div>
  );
}
