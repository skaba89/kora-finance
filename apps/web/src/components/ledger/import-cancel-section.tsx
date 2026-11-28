"use client";

import { Button } from "@/components/ui/button";
import type { fr } from "@/lib/i18n/fr";
import type { components } from "@/lib/api/schema";

type CancellationOut = components["schemas"]["ImportCancellationOut"];

/** Section d'annulation d'un dépôt importé : définitive, elle supprime le
 * fichier déposé et les brouillons encore présents ; une écriture déjà
 * validée interdit l'annulation (contre-passation obligatoire). */
export function ImportCancelSection({ cancellation, error, cancelling, onCancel, labels: t }: {
  cancellation: CancellationOut | null;
  error: string | null;
  cancelling: boolean;
  onCancel: () => void;
  labels: typeof fr.imports;
}) {
  if (cancellation !== null) {
    return <div aria-live="polite" className="space-y-3 rounded-lg border bg-background p-3">
      <h3 className="font-semibold">{t.cancelledTitle}</h3>
      {cancellation.entries_removed > 0 && <dl className="grid gap-3 sm:grid-cols-2">
        {[[t.cancelledDrafts, cancellation.entries_removed], [t.lines, cancellation.lines_removed]].map(([label, value]) => <div key={label} className="min-w-0 rounded-lg border p-3"><dt className="text-sm text-muted-foreground">{label}</dt><dd className="font-semibold tabular-nums wrap-break-word">{value}</dd></div>)}
      </dl>}
      <p className="text-sm text-muted-foreground">{t.cancelledHint}</p>
    </div>;
  }
  return <div className="space-y-3 rounded-lg border bg-background p-3">
    <p className="text-sm text-muted-foreground">{t.cancelHint}</p>
    {error !== null && <p role="alert" className="rounded-lg border border-destructive p-3 text-sm">{error}</p>}
    <Button type="button" variant="outline" className="min-h-11" disabled={cancelling} onClick={onCancel}>
      {cancelling ? t.cancelPending : t.cancel}
    </Button>
  </div>;
}
