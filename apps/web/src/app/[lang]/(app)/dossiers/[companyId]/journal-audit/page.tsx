import type { Metadata } from "next";
import Link from "next/link";
import { DataTable } from "@/components/data-table";
import { TableDensitySelect } from "@/components/table-density-select";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { verifyAuditChainAction } from "@/lib/actions/companies";
import { getAuditEvents } from "@/lib/dal";
import { formatDateTime } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";
import { tablePreferences, tableRange } from "@/lib/table-preferences";

import { AuditVerifier } from "./audit-verifier";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.audit.title };
}

export default async function AuditPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/journal-audit">) {
  const { companyId } = await params;
  const { page, size, density, offset } = tablePreferences(await searchParams);
  const [{ t, locale }, events] = await Promise.all([
    getDictionary(),
    getAuditEvents(companyId, size, offset),
  ]);
  const actions: Record<string, string> = t.audit.actions;
  const { from, to } = tableRange(events.total, events.offset, events.items.length, size);
  const pageHref = (target: number) => `?page=${target}&taille=${size}&densite=${density}`;

  return (
    <>
      <PageHeader
        title={t.audit.title}
        subtitle={t.audit.subtitle}
        actions={
          <AuditVerifier
            action={verifyAuditChainAction.bind(null, companyId)}
            labels={{
              verify: t.audit.verify,
              pending: t.common.pending,
              ok: t.audit.chainOk,
              broken: t.audit.chainBroken,
            }}
          />
        }
      />
      <form method="get" className="flex flex-wrap items-center gap-3 rounded-xl border bg-card p-4">
        <TableDensitySelect density={density} labels={t.table} />
        <select name="taille" defaultValue={size} aria-label={t.table.pageSize} className="border-input bg-background min-h-11 rounded-lg border px-3 text-sm">
          {[25, 50, 100].map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <Button type="submit" className="min-h-11" variant="outline">{t.reports.show}</Button>
      </form>
      {events.items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t.audit.empty}</p>
      ) : (
        <DataTable label={t.audit.title} density={density}>
          <TableHeader>
            <TableRow>
              <TableHead className="w-14">{t.audit.seq}</TableHead>
              <TableHead className="w-36">{t.audit.date}</TableHead>
              <TableHead>{t.audit.action}</TableHead>
              <TableHead>{t.audit.details}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.items.map((event) => (
              <TableRow key={event.seq}>
                <TableCell className="tabular-nums">{event.seq}</TableCell>
                <TableCell>{formatDateTime(event.occurred_at, locale)}</TableCell>
                <TableCell className="whitespace-normal">{actions[event.action] ?? event.action}</TableCell>
                <TableCell className="max-w-md whitespace-normal">
                  <details>
                    <summary className="cursor-pointer text-sm font-medium text-primary">{t.audit.details}</summary>
                    <pre className="mt-2 max-w-[240px] whitespace-pre-wrap wrap-anywhere rounded-md bg-muted p-2 text-xs sm:max-w-md">{JSON.stringify(event.payload, null, 2)}</pre>
                  </details>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}
      <nav className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm" aria-label={t.table.pagination}>
        <span className="text-muted-foreground">
          {interpolate(t.common.pageRange, { from, to, total: events.total })}
        </span>
        <div className="flex gap-2">
          {page > 1 ? (
            <Button asChild variant="outline" size="sm">
              <Link href={pageHref(page - 1)}>{t.common.previous}</Link>
            </Button>
          ) : null}
          {events.items.length > 0 && to < events.total ? (
            <Button asChild variant="outline" size="sm">
              <Link href={pageHref(page + 1)}>{t.common.next}</Link>
            </Button>
          ) : null}
        </div>
      </nav>
    </>
  );
}
