"use client";

import { useFlash } from "@/components/flash/flash-context";

/**
 * Bandeau de confirmation contextuel, rendu par `PageHeader` juste sous le
 * titre : visible même au milieu d'une page dense, effacé automatiquement
 * après quelques secondes ou par son bouton de fermeture. Ne rend rien hors
 * du `FlashProvider` (pages publiques) ni quand aucun succès n'est en cours.
 */
export function FlashBanner() {
  const ctx = useFlash();
  if (!ctx || !ctx.flash) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="mb-6 flex items-start justify-between gap-3 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300"
    >
      <p className="font-medium">{ctx.flash.message}</p>
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
