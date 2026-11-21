"use client";

import { setLocaleAction } from "@/lib/actions/auth";
import type { Locale } from "@/lib/i18n/config";

const LABELS: Record<Locale, string> = { fr: "Français", en: "English" };

/** Changement de langue : mémorisé dans un cookie, retour sur la page courante. */
export function LocaleSwitcher({ current, label }: { current: Locale; label: string }) {
  const other: Locale = current === "fr" ? "en" : "fr";
  return (
    <form
      action={setLocaleAction}
      onSubmit={(event) => {
        const input = event.currentTarget.elements.namedItem("retour");
        if (input instanceof HTMLInputElement) {
          input.value = window.location.pathname + window.location.search;
        }
      }}
    >
      <input type="hidden" name="locale" value={other} />
      <input type="hidden" name="retour" value="/dossiers" />
      <button
        type="submit"
        className="text-muted-foreground hover:text-foreground inline-flex min-h-11 items-center rounded-md px-2 text-sm underline-offset-4 hover:underline"
        aria-label={`${label} : ${LABELS[other]}`}
        lang={other}
      >
        {LABELS[other]}
      </button>
    </form>
  );
}
