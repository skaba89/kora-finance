"use client";

import { useState, useTransition } from "react";
import { useActionState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ImportCancelSection } from "@/components/ledger/import-cancel-section";
import { ImportConfirmSection } from "@/components/ledger/import-confirm-section";
import { ImportIssuesView } from "@/components/ledger/import-issues-view";
import type { ImportCancelState, ImportConfirmState, ImportIssuesPage, ImportState } from "@/lib/actions/imports";
import { formatDateTime, formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import type { fr } from "@/lib/i18n/fr";
import type { components } from "@/lib/api/schema";

type IssueOut = components["schemas"]["ImportIssueOut"];
type ReportOut = components["schemas"]["ImportReportOut"];
type ConfirmationOut = components["schemas"]["ImportConfirmationOut"];
type CancellationOut = components["schemas"]["ImportCancellationOut"];

export function ImportPrecheck({ action, loadMore, confirm, cancel, companyId, labels: t, locale }: {
  action: (state: ImportState, data: FormData) => Promise<ImportState>;
  loadMore: (batchId: string, offset: number) => Promise<ImportIssuesPage>;
  confirm: (batchId: string) => Promise<ImportConfirmState>;
  cancel: (batchId: string) => Promise<ImportCancelState>;
  companyId: string;
  labels: typeof fr.imports;
  locale: Locale;
}) {
  const [state, submit, pending] = useActionState(action, { status: "idle" });
  const report = !pending && state.status === "success" ? state.report : null;
  const batchId = !pending && state.status === "success" ? state.batchId : null;
  const [extra, setExtra] = useState<IssueOut[]>([]);
  const [loadingMore, startLoading] = useTransition();
  const [confirmation, setConfirmation] = useState<ConfirmationOut | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirming, startConfirm] = useTransition();
  const [cancellation, setCancellation] = useState<CancellationOut | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelling, startCancel] = useTransition();

  // Ajustement de state pendant le rendu (pattern React) : un nouveau rapport
  // de précontrôle repart d'une page vierge, sans effet ni rendu supplémentaire.
  const [previousReport, setPreviousReport] = useState<ReportOut | null>(null);
  if (report !== previousReport) {
    setPreviousReport(report);
    setExtra([]);
    setConfirmation(null);
    setConfirmError(null);
    setCancellation(null);
    setCancelError(null);
  }

  const shown = report ? [...report.issues, ...extra] : [];
  const remaining = report ? report.issue_count - shown.length : 0;

  const loadNextPage = () => {
    if (!report || !batchId) return;
    startLoading(async () => {
      const page = await loadMore(batchId, shown.length);
      if (page.status === "error") return;
      setExtra(previous => [...previous, ...page.issues]);
    });
  };

  const confirmNow = () => {
    if (!batchId) return;
    startConfirm(async () => {
      const result = await confirm(batchId);
      if (result.status === "error") {
        setConfirmError(result.message);
        return;
      }
      if (result.status === "success") setConfirmation(result.confirmation);
    });
  };

  const cancelNow = () => {
    if (!batchId) return;
    startCancel(async () => {
      const result = await cancel(batchId);
      if (result.status === "error") {
        setCancelError(result.message);
        return;
      }
      if (result.status === "success") setCancellation(result.cancellation);
    });
  };

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
      <ImportIssuesView
        issues={shown}
        remaining={remaining}
        truncated={report.issue_count > report.issues.length}
        loadingMore={loadingMore}
        onLoadMore={loadNextPage}
        labels={t}
      />
      {report.valid && cancellation === null && <ImportConfirmSection
        confirmation={confirmation}
        error={confirmError}
        confirming={confirming}
        onConfirm={confirmNow}
        companyId={companyId}
        labels={t}
        locale={locale}
      />}
      <ImportCancelSection
        cancellation={cancellation}
        error={cancelError}
        cancelling={cancelling}
        onCancel={cancelNow}
        labels={t}
      />
    </section>}
  </div>;
}
