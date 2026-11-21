import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeftRight, Landmark, Scale, TrendingUp, Wallet } from "lucide-react";

import { DataTable } from "@/components/data-table";
import { KpiCard } from "@/components/kpi-card";
import { ExportLinks } from "@/components/ledger/export-links";
import { PeriodFilter } from "@/components/ledger/period-filter";
import { PageHeader } from "@/components/page-header";
import { TableDensitySelect } from "@/components/table-density-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCompany, getCashFlowStatement, getFinancialStatements, getFiscalYears } from "@/lib/dal";
import { formatDate, formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";
import { dateWithin, pickFiscalYear } from "@/lib/periods";
import { tablePreferences } from "@/lib/table-preferences";
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
  const rawView = one(query.etat);
  const view: "bilan" | "resultat" | "flux" =
    rawView === "resultat" ? "resultat" : rawView === "flux" ? "flux" : "bilan";
  // Écran : postes vides masqués par défaut (lisibilité) ; la présentation complète
  // reste disponible, et sera celle des exports officiels.
  const showEmpty = one(query.tous) === "1";
  const { density } = tablePreferences(query);
  const currency = company.company.currency;
  const money = (value: string | null | undefined, line: Line) => {
    if (value === null || value === undefined) return "";
    const amount = BigInt(value);
    return amount === 0n && !line.is_total ? "" : formatMoney(amount, currency, locale);
  };
  const tab = (target: "bilan" | "resultat" | "flux", label: string) => (
    <Link
      href={`?etat=${target}&exercice=${year.id}&au=${dateTo}&densite=${density}${showEmpty ? "&tous=1" : ""}`}
      aria-current={view === target ? "page" : undefined}
      className={cn(
        "inline-flex min-h-11 items-center rounded-lg px-3 py-2 text-sm font-medium",
        view === target ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {label}
    </Link>
  );
  const rowClass = (line: Line) => (line.is_total ? "bg-muted/40 font-semibold" : undefined);
  const visible = <T extends Line>(lines: T[], amounts: (line: T) => (string | null)[]) =>
    showEmpty ? lines : lines.filter((line) => line.is_total || amounts(line).some((v) => v !== null && v !== "0"));
  const withPrevious = (data: { previous_period: unknown }) => data.previous_period !== null;

  if (view === "flux") {
    const tft = await getCashFlowStatement(companyId, { fiscal_year_id: year.id, date_to: dateTo });
    const lineAmounts = (l: { amount: string; previous_amount: string | null }) => [l.amount, l.previous_amount];
    const groups: { title: string; rows: (Line & { amount: string; previous_amount: string | null })[] }[] = [];
    let current: (typeof groups)[number] | null = null;
    for (const line of tft.lines) {
      if (line.is_section) {
        current = { title: line.label, rows: [] };
        groups.push(current);
        continue;
      }
      if (line.code === "TO" || line.code === "XV" || line.code === "TC") {
        continue; // affichés dans la synthèse au-dessus des sections
      }
      const row = {
        code: line.code,
        label: line.label,
        is_total: line.is_total,
        amount: line.amount,
        previous_amount: line.previous_amount,
      };
      if (current) current.rows.push(row);
    }
    const tftPrev = withPrevious(tft);
    return (
      <>
        <PageHeader title={s.title} subtitle={s.cashFlowSubtitle} />
        <Alert className="mb-4">
          <AlertDescription>{interpolate(s.expertWarning, { reference: tft.reference })}</AlertDescription>
        </Alert>

        <PeriodFilter
          years={years}
          yearId={year.id}
          dateTo={dateTo}
          locale={locale}
          labels={{ fiscalYear: t.reports.fiscalYear, from: t.reports.from, to: t.reports.to, show: t.reports.show }}
        >
          <input type="hidden" name="etat" value={view} />
          <TableDensitySelect density={density} labels={t.table} />
          <label className="flex h-9 items-center gap-2 text-sm">
            <input type="checkbox" name="tous" value="1" defaultChecked={showEmpty} />
            {s.showEmpty}
          </label>
        </PeriodFilter>

        <nav className="mb-4 flex flex-wrap gap-1 rounded-xl border bg-card p-1" aria-label={s.title}>
          {tab("bilan", s.balanceSheet)}
          {tab("resultat", s.incomeStatement)}
          {tab("flux", s.cashFlow)}
        </nav>

        <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
          <span>{interpolate(s.asOf, { date: formatDate(tft.period.date_to, locale) })}</span>
          {tft.coherent ? <Badge variant="secondary">{s.coherent}</Badge> : null}
          {!tftPrev ? <span className="text-muted-foreground">{s.noPrevious}</span> : null}
          <ExportLinks
            companyId={companyId}
            kind="tft"
            fiscalYearId={year.id}
            dateTo={dateTo}
            label={t.reports.export}
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <KpiCard label={s.opening} value={formatMoney(BigInt(tft.opening), currency, locale)} icon={Wallet} />
          <KpiCard label={s.variation} value={formatMoney(BigInt(tft.variation), currency, locale)} icon={ArrowLeftRight} negative={BigInt(tft.variation) < 0n} />
          <KpiCard label={s.closing} value={formatMoney(BigInt(tft.closing), currency, locale)} icon={Landmark} primary />
        </div>
        {!tft.coherent ? (
          <Alert variant="destructive" role="alert" className="mb-4">
            <AlertDescription>
              <p>{s.incoherent}</p>
              {tft.unmapped_accounts.length > 0 ? (
                <p>{interpolate(s.unmapped, { accounts: tft.unmapped_accounts.join(", ") })}</p>
              ) : null}
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-col gap-8">
          {groups.map((group) => {
            const rows = visible(group.rows, lineAmounts);
            if (rows.length === 0) return null;
            return (
              <section key={group.title} aria-label={group.title} className="flex flex-col gap-2">
                <h2 className="text-lg font-semibold">{group.title}</h2>
                <DataTable label={`${s.item} — ${group.title}`} density={density}>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{s.item}</TableHead>
                      <TableHead className="text-right">{s.yearN}</TableHead>
                      {tftPrev ? <TableHead className="text-right">{s.yearN1}</TableHead> : null}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((line) => (
                      <TableRow key={line.code} className={rowClass(line)}>
                        <TableCell className="whitespace-normal">
                          <span className="text-muted-foreground mr-2 font-mono text-xs">{line.code}</span>
                          {line.label}
                        </TableCell>
                        <TableCell className="text-right whitespace-nowrap tabular-nums">{money(line.amount, line)}</TableCell>
                        {tftPrev ? (
                          <TableCell className="text-right whitespace-nowrap tabular-nums">{money(line.previous_amount, line)}</TableCell>
                        ) : null}
                      </TableRow>
                    ))}
                  </TableBody>
                </DataTable>
              </section>
            );
          })}
        </div>
        <p className="text-muted-foreground mt-6 text-xs">{t.reports.draftsExcluded}</p>
      </>
    );
  }

  const data = await getFinancialStatements(companyId, { fiscal_year_id: year.id, date_to: dateTo });
  const hasPrevious = data.previous_period !== null;
  const assets = visible(data.assets, (l) => [l.gross, l.depreciation, l.net, l.previous_net]);
  const liabilities = visible(data.liabilities, (l) => [l.amount, l.previous_amount]);
  const income = visible(data.income_statement, (l) => [l.amount, l.previous_amount]);

  /** Tableau à deux colonnes (N, N-1) : passif et compte de résultat. */
  const simpleTable = (title: string, lines: (Line & { amount: string; previous_amount: string | null })[]) => (
    <section aria-label={title} className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      <ul className="divide-y rounded-xl border bg-card sm:hidden">
        {lines.map((line) => (
          <li key={line.code} className={cn("flex flex-wrap justify-between gap-3 p-3 text-sm", rowClass(line))}>
            <span>
              <span className="text-muted-foreground font-mono text-xs">{line.code}</span> {line.label}
            </span>
            <span className="ml-auto min-w-0 break-words text-right tabular-nums">
              {hasPrevious && <span className="text-muted-foreground block text-xs">{s.yearN}</span>}
              {money(line.amount, line)}
              {hasPrevious && line.previous_amount !== null ? (
                <span className="text-muted-foreground block text-xs">{s.yearN1} · {money(line.previous_amount, line)}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      <DataTable label={`${s.item} — ${title}`} density={density} desktopOnly>
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
      </DataTable>
    </section>
  );

  return (
    <>
      <PageHeader title={s.title} subtitle={s.subtitle} />
      <Alert className="mb-4">
        <AlertDescription>{interpolate(s.expertWarning, { reference: data.reference })}</AlertDescription>
      </Alert>

      <PeriodFilter
        years={years}
        yearId={year.id}
        dateTo={dateTo}
        locale={locale}
        labels={{ fiscalYear: t.reports.fiscalYear, from: t.reports.from, to: t.reports.to, show: t.reports.show }}
      >
        <input type="hidden" name="etat" value={view} />
        <TableDensitySelect density={density} labels={t.table} />
        <label className="flex h-9 items-center gap-2 text-sm">
          <input type="checkbox" name="tous" value="1" defaultChecked={showEmpty} />
          {s.showEmpty}
        </label>
      </PeriodFilter>

      <nav className="mb-4 flex flex-wrap gap-1 rounded-xl border bg-card p-1" aria-label={s.title}>
        {tab("bilan", s.balanceSheet)}
        {tab("resultat", s.incomeStatement)}
        {tab("flux", s.cashFlow)}
      </nav>

      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <span>{interpolate(s.asOf, { date: formatDate(data.period.date_to, locale) })}</span>
        {data.balanced ? <Badge variant="secondary">{s.balanced}</Badge> : null}
        {!hasPrevious ? <span className="text-muted-foreground">{s.noPrevious}</span> : null}
        <ExportLinks
          companyId={companyId}
          kind="etats-financiers"
          fiscalYearId={year.id}
          dateTo={dateTo}
          label={t.reports.export}
        />
      </div>
      <div className={cn("grid gap-3", view === "bilan" ? "sm:grid-cols-3" : "sm:grid-cols-2")}>
        {view === "bilan" && data.assets.filter((line) => line.code === "BZ").map((line) => (
          <KpiCard key={line.code} label={s.assets} value={formatMoney(BigInt(line.net), currency, locale)} icon={Landmark} />
        ))}
        {view === "bilan" && data.liabilities.filter((line) => line.code === "DZ").map((line) => (
          <KpiCard key={line.code} label={s.liabilities} value={formatMoney(BigInt(line.amount), currency, locale)} icon={Scale} />
        ))}
        {view === "resultat" && data.income_statement.filter((line) => line.code === "XB").map((line) => (
          <KpiCard key={line.code} label={t.dashboard.revenue} value={formatMoney(BigInt(line.amount), currency, locale)} icon={Landmark} />
        ))}
        <KpiCard label={s.netResult} value={formatMoney(BigInt(data.net_result), currency, locale)} icon={TrendingUp} primary />
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
            <ul className="divide-y rounded-xl border bg-card sm:hidden">
              {assets.map((line) => (
                <li key={line.code} className={cn("flex flex-wrap justify-between gap-3 p-3 text-sm", rowClass(line))}>
                  <span>
                    <span className="text-muted-foreground font-mono text-xs">{line.code}</span> {line.label}
                    {line.depreciation !== "0" ? (
                      <span className="text-muted-foreground block text-xs">
                        {s.gross} {money(line.gross, line)} · {s.depreciation} {money(line.depreciation, line)}
                      </span>
                    ) : null}
                  </span>
                  <span className="ml-auto min-w-0 break-words text-right tabular-nums">
                    {hasPrevious && <span className="text-muted-foreground block text-xs">{s.yearN}</span>}
                    {money(line.net, line)}
                    {hasPrevious ? (
                      <span className="text-muted-foreground block text-xs">{s.yearN1} · {money(line.previous_net, line)}</span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
            <DataTable label={`${s.item} — ${s.assets}`} density={density} desktopOnly>
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
            </DataTable>
          </section>
          {simpleTable(s.liabilities, liabilities)}
        </div>
      ) : (
        simpleTable(s.incomeStatement, income)
      )}
      <p className="text-muted-foreground mt-6 text-xs">{t.reports.draftsExcluded}</p>
    </>
  );
}
