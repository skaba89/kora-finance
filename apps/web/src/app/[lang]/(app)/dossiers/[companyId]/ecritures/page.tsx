import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { can, getCompany, getEntries, getJournals } from "@/lib/dal";
import { formatDate, formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.entries.title };
}

const PAGE_SIZE = 50;
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
  const statusParam = one(query.statut);
  const status = STATUSES.find((s) => s === statusParam);
  const page = Math.max(1, Number.parseInt(one(query.page) ?? "1", 10) || 1);

  const [{ t, locale }, company, journals] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getJournals(companyId),
  ]);
  const journal = journals.find((j) => j.id === journalParam);
  const entries = await getEntries(companyId, {
    q,
    journal_id: journal?.id,
    status,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });
  const currency = company.company.currency;
  const base = `/dossiers/${companyId}/ecritures`;
  const pageHref = (target: number) => {
    const search = new URLSearchParams();
    if (q) search.set("q", q);
    if (journal) search.set("journal", journal.id);
    if (status) search.set("statut", status);
    search.set("page", String(target));
    return `?${search.toString()}`;
  };
  const from = entries.total === 0 ? 0 : entries.offset + 1;
  const to = entries.offset + entries.items.length;

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

      <form method="get" className="mb-4 flex flex-wrap items-end gap-3" role="search">
        <div className="flex min-w-56 flex-1 flex-col gap-1.5">
          <label htmlFor="recherche-ecriture" className="text-sm font-medium">
            {t.common.search}
          </label>
          <Input id="recherche-ecriture" name="q" defaultValue={q} />
        </div>
        <select
          name="journal"
          defaultValue={journal?.id ?? ""}
          aria-label={t.entries.journal}
          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
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
          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
        >
          <option value="">{t.entries.allStatuses}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t.entries.statuses[s]}
            </option>
          ))}
        </select>
        <Button type="submit" variant="secondary">
          {t.common.filter}
        </Button>
      </form>

      {entries.items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t.entries.empty}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t.entries.date}</TableHead>
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
                  {entry.status === "DRAFT" ? (
                    <Badge variant="outline" className="ml-2 sm:hidden">
                      {t.entries.statuses.DRAFT}
                    </Badge>
                  ) : null}
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
        </Table>
      )}

      {entries.total > PAGE_SIZE ? (
        <nav className="mt-4 flex items-center justify-between text-sm" aria-label="pagination">
          <span className="text-muted-foreground">
            {interpolate(t.common.pageRange, { from, to, total: entries.total })}
          </span>
          <div className="flex gap-2">
            {page > 1 ? (
              <Button asChild variant="outline" size="sm">
                <Link href={pageHref(page - 1)}>{t.common.previous}</Link>
              </Button>
            ) : null}
            {to < entries.total ? (
              <Button asChild variant="outline" size="sm">
                <Link href={pageHref(page + 1)}>{t.common.next}</Link>
              </Button>
            ) : null}
          </div>
        </nav>
      ) : null}
    </>
  );
}
