import type { Metadata } from "next";
import Link from "next/link";
import { FileSearch } from "lucide-react";

import { DataTable } from "@/components/data-table";
import { ExportLinks } from "@/components/ledger/export-links";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { can, getCompany, getEntries, getFiscalYears, getJournals } from "@/lib/dal";
import { formatDate, formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";
import { pickFiscalYear } from "@/lib/periods";
import { PAGE_SIZES, tablePreferences, tableRange } from "@/lib/table-preferences";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.entries.title };
}

const STATUSES = ["DRAFT", "POSTED"] as const;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function EntriesPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/ecritures">) {
  const { companyId } = await params;
  const query = await searchParams;
  const q = one(query.q)?.slice(0, 100) || undefined;
  const journalParam = one(query.journal);
  const yearParam = one(query.exercice);
  const statusParam = one(query.statut);
  const status = STATUSES.find((s) => s === statusParam);
  const { page, size, density, offset } = tablePreferences(query);

  const [{ t, locale }, company, journals, years] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getJournals(companyId),
    getFiscalYears(companyId),
  ]);
  const currentYear = pickFiscalYear(years, undefined, new Date().toISOString().slice(0, 10));
  const journal = journals.find((j) => j.id === journalParam);
  const year = years.find((y) => y.id === yearParam);
  const exportYear = year ?? currentYear;
  const entries = await getEntries(companyId, {
    q,
    journal_id: journal?.id,
    fiscal_year_id: year?.id,
    status,
    limit: size,
    offset,
  });
  const currency = company.company.currency;
  const base = `/dossiers/${companyId}/ecritures`;
  const pageHref = (target: number) => {
    const search = new URLSearchParams();
    if (q) search.set("q", q);
    if (journal) search.set("journal", journal.id);
    if (year) search.set("exercice", year.id);
    if (status) search.set("statut", status);
    search.set("taille", String(size));
    search.set("densite", density);
    search.set("page", String(target));
    return `?${search.toString()}`;
  };
  const { from, to, lastPage } = tableRange(entries.total, entries.offset, entries.items.length, size);

  return (
    <>
      <PageHeader
        title={t.entries.title}
        subtitle={t.entries.subtitle}
        actions={
          can(company, "entries:write") ? (
            <Button asChild>
              <Link href={`${base}/nouvelle`}>{t.entries.newEntry}</Link>
            </Button>
          ) : null
        }
      />

      <form method="get" className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border bg-card p-4" role="search" aria-label={t.entries.title}>
        <div className="flex w-full min-w-0 flex-col gap-1.5 sm:flex-1 sm:basis-48">
          <label htmlFor="recherche-ecriture" className="text-sm font-medium">
            {t.common.search}
          </label>
          <Input id="recherche-ecriture" name="q" defaultValue={q} maxLength={100} className="min-h-11" />
        </div>
        <select
          name="journal"
          defaultValue={journal?.id ?? ""}
          aria-label={t.entries.journal}
          className="border-input bg-background min-h-11 min-w-0 max-w-full rounded-lg border px-3 text-sm"
        >
          <option value="">{t.entries.allJournals}</option>
          {journals.map((j) => (
            <option key={j.id} value={j.id}>
              {j.code} — {j.label}
            </option>
          ))}
        </select>
        <select
          name="statut"
          defaultValue={status ?? ""}
          aria-label={t.common.status}
          className="border-input bg-background min-h-11 min-w-0 max-w-full rounded-lg border px-3 text-sm"
        >
          <option value="">{t.entries.allStatuses}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t.entries.statuses[s]}
            </option>
          ))}
        </select>
        <select name="exercice" defaultValue={year?.id ?? ""} aria-label={t.nav.fiscalYears} className="border-input bg-background min-h-11 min-w-0 max-w-full rounded-lg border px-3 text-sm">
          <option value="">{t.entries.allFiscalYears}</option>
          {years.map(y => <option key={y.id} value={y.id}>{formatDate(y.start_date, locale)} – {formatDate(y.end_date, locale)}</option>)}
        </select>
        <select name="taille" defaultValue={String(size)} aria-label={t.table.pageSize} className="border-input bg-background min-h-11 rounded-lg border px-3 text-sm">
          {PAGE_SIZES.map(value => <option key={value} value={value}>{interpolate(t.table.rowsPerPage, { count: value })}</option>)}
        </select>
        <select name="densite" defaultValue={density} aria-label={t.table.density} className="border-input bg-background min-h-11 rounded-lg border px-3 text-sm">
          <option value="comfortable">{t.table.comfortable}</option>
          <option value="compact">{t.table.compact}</option>
        </select>
        <Button type="submit" className="min-h-11">
          {t.common.filter}
        </Button>
        <Button asChild variant="ghost" className="min-h-11"><Link href={base}>{t.table.reset}</Link></Button>
      </form>

      {exportYear ? (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">{t.reports.exportJournal} — {t.table.fullFiscalYear}</span>
          <ExportLinks
            companyId={companyId}
            kind="ecritures"
            fiscalYearId={exportYear.id}
            label={t.reports.exportJournal}
          />
        </div>
      ) : null}

      {entries.items.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card p-8 text-center">
          <FileSearch aria-hidden className="text-muted-foreground size-8" />
          <p className="text-muted-foreground text-sm">{t.entries.empty}</p>
        </div>
      ) : (
        <DataTable label={t.entries.title} density={density}>
          <TableHeader>
            <TableRow>
              <TableHead aria-sort="descending">{t.entries.date}</TableHead>
              <TableHead>{t.entries.journal}</TableHead>
              <TableHead className="hidden sm:table-cell">{t.entries.reference}</TableHead>
              <TableHead>{t.entries.label}</TableHead>
              <TableHead className="text-right">{t.entries.amount}</TableHead>
              <TableHead className="hidden sm:table-cell">{t.common.status}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.items.map((entry) => (
              <TableRow key={entry.id}>
                <TableCell className="tabular-nums">{formatDate(entry.entry_date, locale)}</TableCell>
                <TableCell className="font-mono">
                  {entry.journal_code}
                  {entry.number !== null ? <span className="text-muted-foreground"> {entry.number}</span> : null}
                </TableCell>
                <TableCell className="hidden sm:table-cell">{entry.reference}</TableCell>
                <TableCell className="whitespace-normal">
                  <Link href={`${base}/${entry.id}`} className="underline-offset-4 hover:underline">
                    {entry.label}
                  </Link>
                  <div className="mt-1 flex flex-wrap items-center gap-1 sm:hidden">
                    <Badge variant={entry.status === "POSTED" ? "secondary" : "outline"}>{t.entries.statuses[entry.status]}</Badge>
                    {entry.reference && <span className="text-muted-foreground wrap-anywhere text-xs">{entry.reference}</span>}
                  </div>
                </TableCell>
                <TableCell className="text-right whitespace-nowrap tabular-nums">
                  {formatMoney(BigInt(entry.total_debit), currency, locale)}
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  <Badge variant={entry.status === "POSTED" ? "secondary" : "outline"}>
                    {t.entries.statuses[entry.status]}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}

      <nav className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm" aria-label={t.table.pagination}>
          <span className="text-muted-foreground">
            {interpolate(t.common.pageRange, { from, to, total: entries.total })}
          </span>
          <div className="flex gap-2">
            {page > 1 ? (
              <Button asChild variant="outline" size="sm">
                <Link href={pageHref(Math.min(page - 1, lastPage))}>{t.common.previous}</Link>
              </Button>
            ) : null}
            {page < lastPage ? (
              <Button asChild variant="outline" size="sm">
                <Link href={pageHref(page + 1)}>{t.common.next}</Link>
              </Button>
            ) : null}
          </div>
      </nav>
    </>
  );
}
