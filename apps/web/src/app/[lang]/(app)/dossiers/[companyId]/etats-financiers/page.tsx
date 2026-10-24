import type { Metadata } from "next";
import Link from "next/link";

import { ExportLinks } from "@/components/ledger/export-links";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCompany, getFinancialStatements, getFiscalYears } from "@/lib/dal";
import { formatDate, formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";
import { dateWithin, pickFiscalYear } from "@/lib/periods";
import { cn } from "@/lib/utils";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.statements.title };
}

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

type Line = { code: string; label: string; is_total: boolean };

export default async function StatementsPage({ params, searchParams }: PageProps<"/[lang]/dossiers/[companyId]/etats-financiers">) {
  const { companyId } = await params;
  const query = await searchParams;
  const [{ t, locale }, company, years] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getFiscalYears(companyId),
  ]);
  const s = t.statements;
  const year = pickFiscalYear(years, one(query.exercice), new Date().toISOString().slice(0, 10));
  if (!year) {
    return (
      <>
        <PageHeader title={s.title} />
        <p className="text-muted-foreground text-sm">{t.reports.noFiscalYear}</p>
      </>
    );
  }
  const dateTo = dateWithin(one(query.au), year) ?? year.end_date;
  const view = one(query.etat) === "resultat" ? "resultat" : "bilan";
  // Écran : postes vides masqués par défaut (lisibilité) ; la présentation complète
  // reste disponible, et sera celle des exports officiels.
  const showEmpty = one(query.tous) === "1";
  const data = await getFinancialStatements(companyId, { fiscal_year_id: year.id, date_to: dateTo });
  const currency = company.company.currency;
  const money = (value: string | null | undefined, line: Line) => {
    if (value === null || value === undefined) return "";
    const amount = BigInt(value);
    return amount === 0n && !line.is_total ? "" : formatMoney(amount, currency, locale);
  };
  const tab = (target: "bilan" | "resultat", label: string) => (
    <Link
      href={`?etat=${target}&exercice=${year.id}&au=${dateTo}${showEmpty ? "&tous=1" : ""}`}
      aria-current={view === target ? "page" : undefined}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm",
        view === target ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </Link>
  );
  const hasPrevious = data.previous_period !== null;
  const rowClass = (line: Line) => (line.is_total ? "bg-muted/40 font-semibold" : undefined);
  const visible = <T extends Line>(lines: T[], amounts: (line: T) => (string | null)[]) =>
    showEmpty ? lines : lines.filter((line) => line.is_total || amounts(line).some((v) => v !== null && v !== "0"));
  const assets = visible(data.assets, (l) => [l.gross, l.depreciation, l.net, l.previous_net]);
  const liabilities = visible(data.liabilities, (l) => [l.amount, l.previous_amount]);
  const income = visible(data.income_statement, (l) => [l.amount, l.previous_amount]);

  /** Tableau à deux colonnes (N, N-1) : passif et compte de résultat. */
  const simpleTable = (title: string, lines: (Line & { amount: string; previous_amount: string | null })[]) => (
    <section aria-label={title} className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      <ul className="divide-y rounded-md border sm:hidden">
        {lines.map((line) => (
          <li key={line.code} className={cn("flex justify-between gap-3 p-3 text-sm", rowClass(line))}>
            <span>
              <span className="text-muted-foreground font-mono text-xs">{line.code}</span> {line.label}
            </span>
            <span className="text-right whitespace-nowrap tabular-nums">
              {money(line.amount, line)}
              {hasPrevious && line.previous_amount !== null ? (
                <span className="text-muted-foreground block text-xs">{money(line.previous_amount, line)}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      <Table className="hidden text-sm sm:table">
        <TableHeader>
          <TableRow>
            <TableHead>{s.item}</TableHead>
            <TableHead className="text-right">{s.yearN}</TableHead>
            {hasPrevious ? <TableHead className="text-right">{s.yearN1}</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {lines.map((line) => (
            <TableRow key={line.code} className={rowClass(line)}>
              <TableCell className="whitespace-normal">
                <span className="text-muted-foreground mr-2 font-mono text-xs">{line.code}</span>
                {line.label}
              </TableCell>
              <TableCell className="text-right whitespace-nowrap tabular-nums">{money(line.amount, line)}</TableCell>
              {hasPrevious ? (
                <TableCell className="text-right whitespace-nowrap tabular-nums">
                  {money(line.previous_amount, line)}
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );

  return (
    <>
      <PageHeader title={s.title} subtitle={s.subtitle} />
      <Alert className="mb-4">
        <AlertDescription>{interpolate(s.expertWarning, { reference: data.reference })}</AlertDescription>
      </Alert>

      <form method="get" className="mb-4 flex flex-wrap items-end gap-3">
        <input type="hidden" name="etat" value={view} />
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="etats-exercice">{t.reports.fiscalYear}</Label>
          <select
            id="etats-exercice"
            name="exercice"
            defaultValue={year.id}
            className="border-input bg-background h-9 rounded-md border px-3 text-sm"
          >
            {years.map((y) => (
              <option key={y.id} value={y.id}>
                {formatDate(y.start_date, locale)} – {formatDate(y.end_date, locale)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="etats-au">{t.reports.to}</Label>
          <Input id="etats-au" name="au" type="date" defaultValue={dateTo} className="w-auto" />
        </div>
        <label className="flex h-9 items-center gap-2 text-sm">
          <input type="checkbox" name="tous" value="1" defaultChecked={showEmpty} />
          {s.showEmpty}
        </label>
        <Button type="submit" variant="secondary">
          {t.reports.show}
        </Button>
      </form>

      <nav className="mb-4 flex gap-1" aria-label={s.title}>
        {tab("bilan", s.balanceSheet)}
        {tab("resultat", s.incomeStatement)}
      </nav>

      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <span>{interpolate(s.asOf, { date: formatDate(data.period.date_to, locale) })}</span>
        {data.balanced ? <Badge variant="secondary">{s.balanced}</Badge> : null}
        <span>
          {s.netResult} : <span className="font-medium tabular-nums">{formatMoney(BigInt(data.net_result), currency, locale)}</span>
        </span>
        {!hasPrevious ? <span className="text-muted-foreground">{s.noPrevious}</span> : null}
        <ExportLinks
          companyId={companyId}
          kind="etats-financiers"
          fiscalYearId={year.id}
          dateTo={dateTo}
          label={t.reports.export}
        />
      </div>
      {!data.balanced ? (
        <Alert variant="destructive" role="alert" className="mb-4">
          <AlertDescription>
            <p>{s.unbalanced}</p>
            {data.unmapped_accounts.length > 0 ? (
              <p>{interpolate(s.unmapped, { accounts: data.unmapped_accounts.join(", ") })}</p>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      {view === "bilan" ? (
        <div className="flex flex-col gap-8">
          <section aria-label={s.assets} className="flex flex-col gap-2">
            <h2 className="text-lg font-semibold">{s.assets}</h2>
            <ul className="divide-y rounded-md border sm:hidden">
              {assets.map((line) => (
                <li key={line.code} className={cn("flex justify-between gap-3 p-3 text-sm", rowClass(line))}>
                  <span>
                    <span className="text-muted-foreground font-mono text-xs">{line.code}</span> {line.label}
                    {line.depreciation !== "0" ? (
                      <span className="text-muted-foreground block text-xs">
                        {s.gross} {money(line.gross, line)} · {s.depreciation} {money(line.depreciation, line)}
                      </span>
                    ) : null}
                  </span>
                  <span className="text-right whitespace-nowrap tabular-nums">
                    {money(line.net, line)}
                    {hasPrevious ? (
                      <span className="text-muted-foreground block text-xs">{money(line.previous_net, line)}</span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
            <Table className="hidden text-sm sm:table">
              <TableHeader>
                <TableRow>
                  <TableHead>{s.item}</TableHead>
                  <TableHead className="text-right">{s.gross}</TableHead>
                  <TableHead className="text-right">{s.depreciation}</TableHead>
                  <TableHead className="text-right">
                    {s.net} {s.yearN}
                  </TableHead>
                  {hasPrevious ? (
                    <TableHead className="text-right">
                      {s.net} {s.yearN1}
                    </TableHead>
                  ) : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {assets.map((line) => (
                  <TableRow key={line.code} className={rowClass(line)}>
                    <TableCell className="whitespace-normal">
                      <span className="text-muted-foreground mr-2 font-mono text-xs">{line.code}</span>
                      {line.label}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap tabular-nums">{money(line.gross, line)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap tabular-nums">
                      {money(line.depreciation, line)}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap tabular-nums">{money(line.net, line)}</TableCell>
                    {hasPrevious ? (
                      <TableCell className="text-right whitespace-nowrap tabular-nums">
                        {money(line.previous_net, line)}
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>
          {simpleTable(s.liabilities, liabilities)}
        </div>
      ) : (
        simpleTable(s.incomeStatement, income)
      )}
      <p className="text-muted-foreground mt-6 text-xs">
        {t.reports.draftsExcluded} {s.tftPending}
      </p>
    </>
  );
}
