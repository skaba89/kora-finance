"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { formatDateTime, formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import type { fr } from "@/lib/i18n/fr";
import type { components } from "@/lib/api/schema";

type ConfirmationOut = components["schemas"]["ImportConfirmationOut"];

/** Section de confirmation d'un import précontrôlé : rien n'est validé
 * automatiquement, la confirmation crée des brouillons dans une transaction. */
export function ImportConfirmSection({ confirmation, error, confirming, onConfirm, companyId, labels: t, locale }: {
  confirmation: ConfirmationOut | null;
  error: string | null;
  confirming: boolean;
  onConfirm: () => void;
  companyId: string;
  labels: typeof fr.imports;
  locale: Locale;
}) {
  if (confirmation !== null) {
    return <div aria-live="polite" className="space-y-3 rounded-lg border bg-background p-3">
      <h3 className="font-semibold">{t.confirmedTitle}</h3>
      <dl className="grid gap-3 sm:grid-cols-2">
        {[[t.entries, confirmation.entries], [t.lines, confirmation.lines], [t.debit, formatMoney(BigInt(confirmation.debit), "GNF", locale)], [t.credit, formatMoney(BigInt(confirmation.credit), "GNF", locale)]].map(([label, value]) => <div key={label} className="min-w-0 rounded-lg border p-3"><dt className="text-sm text-muted-foreground">{label}</dt><dd className="font-semibold tabular-nums wrap-break-word">{value}</dd></div>)}
      </dl>
      <p className="text-sm text-muted-foreground">{t.confirmedHint} {formatDateTime(confirmation.confirmed_at, locale)}</p>
      <Button asChild variant="outline" className="min-h-11"><Link href={`/dossiers/${companyId}/ecritures`}>{t.seeEntries}</Link></Button>
    </div>;
  }
  return <div className="space-y-3 rounded-lg border bg-background p-3">
    <p className="text-sm text-muted-foreground">{t.confirmHint}</p>
    {error !== null && <p role="alert" className="rounded-lg border border-destructive p-3 text-sm">{error}</p>}
    <Button type="button" className="min-h-11" disabled={confirming} onClick={onConfirm}>
      {confirming ? t.confirmPending : t.confirm}
    </Button>
  </div>;
}
