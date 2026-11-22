"use client";

import { useActionState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ImportState } from "@/lib/actions/imports";
import { formatDateTime, formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import type { fr } from "@/lib/i18n/fr";

export function ImportPrecheck({ action, labels: t, locale }: {
  action: (state: ImportState, data: FormData) => Promise<ImportState>;
  labels: typeof fr.imports;
  locale: Locale;
}) {
  const [state, submit, pending] = useActionState(action, { status: "idle" });
  const report = !pending && state.status === "success" ? state.report : null;
  return <div className="space-y-4">
    <form action={submit} className="space-y-4 rounded-xl border bg-card p-4 sm:p-6">
      <p className="text-sm text-muted-foreground">{t.instructions}</p>
      <fieldset disabled={pending} className="min-w-0 space-y-3">
        <label className="block space-y-1 text-sm font-medium">{t.format}
          <select name="format" className="block min-h-11 w-full rounded-lg border bg-background px-3"><option value="csv">CSV</option><option value="xlsx">Excel (.xlsx)</option><option value="fec">FEC</option></select>
        </label>
        <label className="block space-y-1 text-sm font-medium">{t.delimiter}
          <select name="delimiter" className="block min-h-11 w-full rounded-lg border bg-background px-3"><option value="pipe">{t.pipe}</option><option value="tab">{t.tab}</option></select>
        </label>
        <label className="block space-y-1 text-sm font-medium">{t.file}<Input name="file" type="file" accept=".csv,.xlsx,.txt,.fec" required className="min-h-11" onChange={event => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.setCustomValidity(file && file.size > 10 * 1024 * 1024 ? t.tooLarge : "");
        }} /></label>
        <Button type="submit" className="min-h-11" disabled={pending}>{pending ? t.pending : t.check}</Button>
      </fieldset>
    </form>
    {!pending && state.status === "error" && <p role="alert" className="rounded-lg border border-destructive p-3 text-sm">{state.message}</p>}
    {report && state.status === "success" && <section aria-label={t.issues} className="space-y-4 rounded-xl border bg-card p-4 sm:p-6">
      <h2 aria-live="polite" className="font-semibold">{report.valid ? t.valid : t.invalid}</h2>
      <p className="text-sm text-muted-foreground">{t.expires} {formatDateTime(state.expiresAt, locale)}</p>
      <dl className="grid gap-3 sm:grid-cols-2">
        {[[t.rows, report.rows], [t.entries, report.entries], [t.debit, formatMoney(BigInt(report.debit), "GNF", locale)], [t.credit, formatMoney(BigInt(report.credit), "GNF", locale)], [t.issues, report.issue_count]].map(([label, value]) => <div key={label} className="min-w-0 rounded-lg border p-3"><dt className="text-sm text-muted-foreground">{label}</dt><dd className="font-semibold tabular-nums wrap-break-word">{value}</dd></div>)}
      </dl>
      {report.issue_count > report.issues.length && <p className="text-sm">{t.truncated}</p>}
      {report.issues.length > 0 && <table className="w-full text-left text-sm"><thead><tr><th className="p-2">{t.row}</th><th className="p-2">{t.code}</th></tr></thead><tbody>{report.issues.map((issue, index) => <tr key={`${issue.row}-${index}`} className="border-t"><td className="p-2 tabular-nums">{issue.row}</td><td className="p-2 wrap-anywhere">{issue.code}</td></tr>)}</tbody></table>}
    </section>}
  </div>;
}
