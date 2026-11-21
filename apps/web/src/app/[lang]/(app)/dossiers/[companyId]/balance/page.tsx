import type { Metadata } from "next";
import Link from "next/link";
import { Fragment } from "react";
import { DataTable } from "@/components/data-table";
import { TableDensitySelect } from "@/components/table-density-select";

import { ExportLinks } from "@/components/ledger/export-links";
import { PeriodFilter } from "@/components/ledger/period-filter";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCompany, getFiscalYears, getTrialBalance } from "@/lib/dal";
import { formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";
import { dateWithin, pickFiscalYear } from "@/lib/periods";
import { tablePreferences } from "@/lib/table-preferences";
import { cn } from "@/lib/utils";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.reports.balanceTitle };
}

const COLUMNS = [
  "opening_debit",
  "opening_credit",
  "period_debit",
  "period_credit",
  "closing_debit",
  "closing_credit",
] as const;
type Column = (typeof COLUMNS)[number];
type Amounts = Record<Column, string>;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function addRows(rows: Amounts[]): Record<Column, bigint> {
  const total = Object.fromEntries(COLUMNS.map((c) => [c, 0n])) as Record<Column, bigint>;
  for (const row of rows) for (const c of COLUMNS) total[c] += BigInt(row[c]);
  return total;
}

export default async function BalancePage({ params, searchParams }: PageProps<"/[lang]/dossiers/[companyId]/balance">) {
  const { companyId } = await params;
  const query = await searchParams;
  const { density } = tablePreferences(query);
  const [{ t, locale }, company, years] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getFiscalYears(companyId),
  ]);
  const year = pickFiscalYear(years, one(query.exercice), new Date().toISOString().slice(0, 10));
  if (!year) {
    return (
      <>
        <PageHeader title={t.reports.balanceTitle} />
        <p className="text-muted-foreground text-sm">{t.reports.noFiscalYear}</p>
      </>
    );
  }
  const dateFrom = dateWithin(one(query.du), year) ?? year.start_date;
  const dateTo = dateWithin(one(query.au), year) ?? year.end_date;
  const classNumber = Number(one(query.classe));
  const accountClass = Number.isInteger(classNumber) && classNumber >= 1 && classNumber <= 8 ? classNumber : undefined;
  const includeZero = one(query.tous) === "1";

  const balance = await getTrialBalance(companyId, {
    fiscal_year_id: year.id,
    date_from: dateFrom,
    date_to: dateTo,
    class: accountClass,
    include_zero: includeZero,
  });
  const currency = company.company.currency;
  const money = (value: bigint | string) => {
    const amount = BigInt(value);
    return amount === 0n ? "" : formatMoney(amount, currency, locale);
  };
  const byClass = new Map<string, typeof balance.rows>();
  for (const row of balance.rows) {
    const key = row.number.charAt(0);
    byClass.set(key, [...(byClass.get(key) ?? []), row]);
  }
  const period = `exercice=${year.id}&du=${dateFrom}&au=${dateTo}`;
  /** Solde net « montant D/C » à partir des colonnes débit/crédit d'une ligne. */
  const side = (debit: string | bigint, credit: string | bigint) => {
    const net = BigInt(debit) - BigInt(credit);
    if (net === 0n) return formatMoney(0n, currency, locale);
    const abs = net < 0n ? -net : net;
    return `${formatMoney(abs, currency, locale)} ${net < 0n ? t.reports.creditSide : t.reports.debitSide}`;
  };
  const r = t.reports;

  return (
    <>
      <PageHeader title={r.balanceTitle} subtitle={r.balanceSubtitle} />
      <PeriodFilter
        key={JSON.stringify([year.id, dateFrom, dateTo, accountClass, includeZero, density])}
        years={years}
        yearId={year.id}
        dateFrom={dateFrom}
        dateTo={dateTo}
        locale={locale}
        labels={{ fiscalYear: r.fiscalYear, from: r.from, to: r.to, show: r.show }}
      >
        <select
          name="classe"
          defaultValue={accountClass ?? ""}
          aria-label={r.accountClass}
          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
        >
          <option value="">{r.allClasses}</option>
          {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
            <option key={n} value={n}>
              {interpolate(r.classLabel, { n })}
            </option>
          ))}
        </select>
        <label className="flex h-9 items-center gap-2 text-sm">
          <input type="checkbox" name="tous" value="1" defaultChecked={includeZero} />
          {r.includeZero}
        </label>
        <TableDensitySelect density={density} labels={t.table} />
      </PeriodFilter>

      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted-foreground">{r.export}</span>
        <ExportLinks
          companyId={companyId}
          kind="balance"
          fiscalYearId={year.id}
          dateFrom={dateFrom}
          dateTo={dateTo}
          label={r.export}
        />
      </div>

      {balance.balanced === false ? (
        <Alert variant="destructive" role="alert" className="mb-4">
          <AlertDescription>{r.unbalanced}</AlertDescription>
        </Alert>
      ) : null}
      {balance.balanced ? (
        <Badge variant="secondary" className="mb-4">
          {r.balanced}
        </Badge>
      ) : null}

      {balance.rows.length === 0 ? (
        <p className="text-muted-foreground text-sm">{r.empty}</p>
      ) : null}
      {/* Téléphone : une fiche par compte, solde de clôture en évidence. */}
      {balance.rows.length > 0 ? (
        <ul className={cn("divide-y rounded-xl border bg-card sm:hidden", density === "compact" && "[&_li]:py-2")}>
          {balance.rows.map((row) => (
            <li key={row.account_id} className="flex flex-col gap-1 p-3 text-sm">
              <Link
                href={`/dossiers/${companyId}/grand-livre?compte=${row.number}&${period}`}
                className="font-medium underline-offset-4 hover:underline"
              >
                <span className="font-mono">{row.number}</span> {row.label}
              </Link>
              <div className="text-muted-foreground flex justify-between gap-2">
                <span>{r.opening}</span>
                <span className="tabular-nums">{side(row.opening_debit, row.opening_credit)}</span>
              </div>
              <div className="text-muted-foreground flex justify-between gap-2">
                <span>{r.period}</span>
                <span className="text-right tabular-nums">
                  {r.debitSide} {formatMoney(BigInt(row.period_debit), currency, locale)} · {r.creditSide}{" "}
                  {formatMoney(BigInt(row.period_credit), currency, locale)}
                </span>
              </div>
              <div className="flex justify-between gap-2 font-medium">
                <span>{r.closing}</span>
                <span className="tabular-nums">{side(row.closing_debit, row.closing_credit)}</span>
              </div>
            </li>
          ))}
          <li className="bg-muted/40 flex flex-col gap-1 p-3 text-sm font-semibold">
            <span>{r.total}</span>
            <div className="flex justify-between gap-2">
              <span>{r.debit}</span>
              <span className="tabular-nums">{formatMoney(BigInt(balance.totals.closing_debit), currency, locale)}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span>{r.credit}</span>
              <span className="tabular-nums">{formatMoney(BigInt(balance.totals.closing_credit), currency, locale)}</span>
            </div>
          </li>
        </ul>
      ) : null}
      {balance.rows.length === 0 ? null : (
        <DataTable label={r.balanceTitle} density={density} desktopOnly>
          <TableHeader>
            <TableRow>
              <TableHead rowSpan={2} className="align-bottom">
                {r.account}
              </TableHead>
              <TableHead colSpan={2} className="border-l text-center">
                {r.opening}
              </TableHead>
              <TableHead colSpan={2} className="border-l text-center">
                {r.period}
              </TableHead>
              <TableHead colSpan={2} className="border-l text-center">
                {r.closing}
              </TableHead>
            </TableRow>
            <TableRow>
              {COLUMNS.map((c) => (
                <TableHead key={c} className={c.endsWith("debit") ? "border-l text-right" : "text-right"}>
                  {c.endsWith("debit") ? r.debit : r.credit}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...byClass.entries()].map(([classKey, rows]) => {
              const subtotal = addRows(rows);
              return (
                <Fragment key={classKey}>
                  {rows.map((row) => (
                    <TableRow key={row.account_id}>
                      <TableCell className="min-w-48 whitespace-normal">
                        <Link
                          href={`/dossiers/${companyId}/grand-livre?compte=${row.number}&${period}`}
                          className="font-mono underline-offset-4 hover:underline"
                        >
                          {row.number}
                        </Link>{" "}
                        {row.label}
                      </TableCell>
                      {COLUMNS.map((c) => (
                        <TableCell key={c} className="text-right whitespace-nowrap tabular-nums">
                          {money(row[c])}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                  <TableRow className="bg-muted/40 font-medium">
                    <TableCell>{interpolate(r.subtotal, { n: classKey })}</TableCell>
                    {COLUMNS.map((c) => (
                      <TableCell key={c} className="text-right whitespace-nowrap tabular-nums">
                        {money(subtotal[c])}
                      </TableCell>
                    ))}
                  </TableRow>
                </Fragment>
              );
            })}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell className="font-semibold">{r.total}</TableCell>
              {COLUMNS.map((c) => (
                <TableCell key={c} className="text-right font-semibold whitespace-nowrap tabular-nums">
                  {money(balance.totals[c])}
                </TableCell>
              ))}
            </TableRow>
          </TableFooter>
        </DataTable>
      )}
      <p className="text-muted-foreground mt-4 text-xs">{r.draftsExcluded}</p>
    </>
  );
}
