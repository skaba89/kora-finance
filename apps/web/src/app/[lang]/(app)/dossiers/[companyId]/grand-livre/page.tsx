import type { Metadata } from "next";
import Link from "next/link";
import { DataTable } from "@/components/data-table";
import { TableDensitySelect } from "@/components/table-density-select";

import { ExportLinks } from "@/components/ledger/export-links";
import { PeriodFilter } from "@/components/ledger/period-filter";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getAccounts, getCompany, getFiscalYears, getLedger } from "@/lib/dal";
import { formatDate, formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";
import { dateWithin, pickFiscalYear } from "@/lib/periods";
import { PAGE_SIZES, tablePreferences, tableRange } from "@/lib/table-preferences";
import { cn } from "@/lib/utils";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.reports.ledgerTitle };
}

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function LedgerPage({ params, searchParams }: PageProps<"/[lang]/dossiers/[companyId]/grand-livre">) {
  const { companyId } = await params;
  const query = await searchParams;
  const [{ t, locale }, company, years] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getFiscalYears(companyId),
  ]);
  const r = t.reports;
  const year = pickFiscalYear(years, one(query.exercice), new Date().toISOString().slice(0, 10));
  if (!year) {
    return (
      <>
        <PageHeader title={r.ledgerTitle} />
        <p className="text-muted-foreground text-sm">{r.noFiscalYear}</p>
      </>
    );
  }
  const dateFrom = dateWithin(one(query.du), year) ?? year.start_date;
  const dateTo = dateWithin(one(query.au), year) ?? year.end_date;
  const number = /^[1-9][0-9]{0,11}$/.test(one(query.compte) ?? "") ? one(query.compte) : undefined;
  const { page, size, offset, density } = tablePreferences(query, 100);

  const account = number
    ? (await getAccounts(companyId, { q: number, limit: 50, offset: 0 })).items.find((a) => a.number === number)
    : undefined;
  const ledger = account
    ? await getLedger(companyId, {
        account_id: account.id,
        fiscal_year_id: year.id,
        date_from: dateFrom,
        date_to: dateTo,
        limit: size,
        offset,
      })
    : null;

  const currency = company.company.currency;
  const money = (value: string) => (value === "0" ? "" : formatMoney(BigInt(value), currency, locale));
  const signed = (value: string) => {
    const amount = BigInt(value);
    if (amount === 0n) return formatMoney(0n, currency, locale);
    return `${formatMoney(amount < 0n ? -amount : amount, currency, locale)} ${amount < 0n ? r.creditSide : r.debitSide}`;
  };
  const pageHref = (target: number) =>
    `?compte=${number}&exercice=${year.id}&du=${dateFrom}&au=${dateTo}&taille=${size}&densite=${density}&page=${target}`;
  const range = ledger ? tableRange(ledger.total, ledger.offset, ledger.items.length, size) : null;

  return (
    <>
      <PageHeader title={r.ledgerTitle} subtitle={r.ledgerSubtitle} />
      <PeriodFilter
        key={pageHref(1)}
        years={years}
        yearId={year.id}
        dateFrom={dateFrom}
        dateTo={dateTo}
        locale={locale}
        labels={{ fiscalYear: r.fiscalYear, from: r.from, to: r.to, show: r.show }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="grand-livre-compte">{r.account}</Label>
          <Input
            id="grand-livre-compte"
            name="compte"
            defaultValue={number}
            inputMode="numeric"
            pattern="[1-9][0-9]{0,11}"
            placeholder="521"
            className="w-32"
            required
          />
        </div>
        <select name="taille" defaultValue={String(size)} aria-label={t.table.pageSize} className="border-input bg-background min-h-11 rounded-lg border px-3 text-sm">
          {PAGE_SIZES.map(value => <option key={value} value={value}>{interpolate(t.table.rowsPerPage, { count: value })}</option>)}
        </select>
        <TableDensitySelect density={density} labels={t.table} />
      </PeriodFilter>

      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        {account ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground">{r.exportAccount}</span>
            <ExportLinks
              companyId={companyId}
              kind="grand-livre"
              fiscalYearId={year.id}
              dateFrom={dateFrom}
              dateTo={dateTo}
              accountId={account.id}
              label={r.exportAccount}
            />
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">{r.exportAll}</span>
          <ExportLinks
            companyId={companyId}
            kind="grand-livre"
            fiscalYearId={year.id}
            dateFrom={dateFrom}
            dateTo={dateTo}
            label={r.exportAll}
          />
        </div>
      </div>

      {!number ? <p className="text-muted-foreground text-sm">{r.chooseAccount}</p> : null}
      {number && !account ? (
        <p role="alert" className="text-destructive text-sm">
          {interpolate(r.unknownAccount, { number })}
        </p>
      ) : null}

      {ledger ? (
        <>
          <h2 className="mb-3 text-lg font-semibold">
            <span className="font-mono">{ledger.account.number}</span> {ledger.account.label}
          </h2>
          {/* Téléphone : une fiche par mouvement, solde progressif en évidence. */}
          <ul className={cn("divide-y rounded-xl border bg-card sm:hidden", density === "compact" && "[&_li]:py-2")}>
            <li className="bg-muted/40 flex justify-between gap-2 p-3 text-sm font-medium">
              <span>{r.openingRow}</span>
              <span className="tabular-nums">{signed(ledger.opening)}</span>
            </li>
            {ledger.items.length === 0 ? <li className="text-muted-foreground p-3 text-sm">{r.empty}</li> : null}
            {ledger.items.map((item, index) => (
              <li key={`${item.entry_id}-${index}`} className="flex flex-col gap-1 p-3 text-sm">
                <div className="text-muted-foreground flex justify-between gap-2">
                  <span className="tabular-nums">{formatDate(item.entry_date, locale)}</span>
                  <Link
                    href={`/dossiers/${companyId}/ecritures/${item.entry_id}`}
                    className="font-mono underline-offset-4 hover:underline"
                  >
                    {item.journal_code} {item.number}
                  </Link>
                </div>
                <span>{item.label}</span>
                <div className="flex justify-between gap-2">
                  <span className="tabular-nums">
                    {item.debit !== "0" ? `${r.debit} ${money(item.debit)}` : `${r.credit} ${money(item.credit)}`}
                  </span>
                  <span className="font-medium tabular-nums">{signed(item.balance)}</span>
                </div>
              </li>
            ))}
            <li className="bg-muted/40 flex justify-between gap-2 p-3 text-sm font-semibold">
              <span>{r.closingRow}</span>
              <span className="tabular-nums">{signed(ledger.closing)}</span>
            </li>
          </ul>
          <DataTable label={r.ledgerTitle} density={density} desktopOnly>
            <TableHeader>
              <TableRow>
                <TableHead>{t.entries.date}</TableHead>
                <TableHead>{t.entries.journal}</TableHead>
                <TableHead className="hidden md:table-cell">{t.entries.reference}</TableHead>
                <TableHead>{t.entries.label}</TableHead>
                <TableHead className="text-right">{r.debit}</TableHead>
                <TableHead className="text-right">{r.credit}</TableHead>
                <TableHead className="text-right">{r.balance}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow className="bg-muted/40">
                <TableCell colSpan={4} className="font-medium">
                  {r.openingRow}
                </TableCell>
                <TableCell />
                <TableCell />
                <TableCell className="text-right font-medium whitespace-nowrap tabular-nums">
                  {signed(ledger.opening)}
                </TableCell>
              </TableRow>
              {ledger.items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-muted-foreground">
                    {r.empty}
                  </TableCell>
                </TableRow>
              ) : null}
              {ledger.items.map((item, index) => (
                <TableRow key={`${item.entry_id}-${index}`}>
                  <TableCell className="whitespace-nowrap tabular-nums">{formatDate(item.entry_date, locale)}</TableCell>
                  <TableCell className="font-mono whitespace-nowrap">
                    <Link
                      href={`/dossiers/${companyId}/ecritures/${item.entry_id}`}
                      className="underline-offset-4 hover:underline"
                    >
                      {item.journal_code} {item.number}
                    </Link>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">{item.reference}</TableCell>
                  <TableCell className="min-w-40 whitespace-normal">{item.label}</TableCell>
                  <TableCell className="text-right whitespace-nowrap tabular-nums">{money(item.debit)}</TableCell>
                  <TableCell className="text-right whitespace-nowrap tabular-nums">{money(item.credit)}</TableCell>
                  <TableCell className="text-right whitespace-nowrap tabular-nums">{signed(item.balance)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
            <TableFooter>
              <TableRow>
                <TableCell colSpan={4} className="font-semibold">
                  {r.closingRow}
                </TableCell>
                <TableCell className="text-right font-semibold whitespace-nowrap tabular-nums">
                  {money(ledger.period_debit)}
                </TableCell>
                <TableCell className="text-right font-semibold whitespace-nowrap tabular-nums">
                  {money(ledger.period_credit)}
                </TableCell>
                <TableCell className="text-right font-semibold whitespace-nowrap tabular-nums">
                  {signed(ledger.closing)}
                </TableCell>
              </TableRow>
            </TableFooter>
          </DataTable>
          {range ? (
            <nav className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm" aria-label={t.table.pagination}>
              <span className="text-muted-foreground">
                {interpolate(t.common.pageRange, {
                  from: range.from,
                  to: range.to,
                  total: ledger.total,
                })}
              </span>
              <div className="flex gap-2">
                {page > 1 ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(Math.min(page - 1, range.lastPage))}>{t.common.previous}</Link>
                  </Button>
                ) : null}
                {page < range.lastPage ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(page + 1)}>{t.common.next}</Link>
                  </Button>
                ) : null}
              </div>
            </nav>
          ) : null}
        </>
      ) : null}
      <p className="text-muted-foreground mt-4 text-xs">{r.draftsExcluded}</p>
    </>
  );
}
