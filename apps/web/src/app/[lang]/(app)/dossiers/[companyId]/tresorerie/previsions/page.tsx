import type { Metadata } from "next";
import Link from "next/link";
import { CalendarClock, Download, Lock, TrendingDown, Wallet } from "lucide-react";

import { ForecastChart } from "@/components/cashflow/forecast-chart";
import { DataTable } from "@/components/data-table";
import { KpiCard } from "@/components/kpi-card";
import { InlineAction } from "@/components/forms/inline-action";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { createCashflowSnapshotAction } from "@/lib/actions/cashflow";
import {
  HORIZONS,
  SCENARIOS,
  statusLabel,
  statusVariant,
  type ForecastHorizon,
  type ForecastScenario,
} from "@/lib/cashflow";
import { can, getCashflowForecast, getCashflowSnapshots, getCompany } from "@/lib/dal";
import { previsionsExportHref } from "@/lib/exports";
import { formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.cashflow.title };
}

const SCENARIO_KEYS: Record<ForecastScenario, "scenarioOptimiste" | "scenarioNeutre" | "scenarioPrudent"> = {
  OPTIMISTE: "scenarioOptimiste",
  NEUTRE: "scenarioNeutre",
  PRUDENT: "scenarioPrudent",
};

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parseHorizon(value: string | undefined): ForecastHorizon {
  const parsed = Number(value);
  return parsed === 30 || parsed === 60 ? parsed : 90;
}

function parseScenario(value: string | undefined): ForecastScenario {
  return value === "OPTIMISTE" || value === "PRUDENT" ? value : "NEUTRE";
}

export default async function CashflowPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/tresorerie/previsions">) {
  const { companyId } = await params;
  const query = await searchParams;
  const [{ t, locale }, company] = await Promise.all([getDictionary(), getCompany(companyId)]);
  const { currency } = company.company;

  const horizon = parseHorizon(one(query.horizon));
  const scenario = parseScenario(one(query.scenario));

  const [forecast, snapshots] = await Promise.all([
    getCashflowForecast(companyId, { horizon, scenario }),
    getCashflowSnapshots(companyId),
  ]);
  // Figer un instantané exige treasury:manage (API) ; le bouton n'est rendu
  // que pour ce rôle — la consultation reste ouverte dès treasury:read.
  const manage = can(company, "treasury:manage");

  const tone = statusVariant(forecast.status);

  return (
    <>
      <PageHeader title={t.cashflow.title} subtitle={t.cashflow.subtitle} />

      <div className="grid gap-4 rounded-xl border bg-card p-4 sm:grid-cols-2">
        <div role="group" aria-label={t.cashflow.horizon} className="space-y-2">
          <p className="text-sm font-medium">{t.cashflow.horizon}</p>
          <div className="flex flex-wrap gap-2">
            {HORIZONS.map((value) => (
              <Button key={value} asChild variant={value === horizon ? "default" : "outline"}>
                <Link href={`?horizon=${value}&scenario=${scenario}`} aria-current={value === horizon ? "true" : undefined}>
                  {interpolate(t.cashflow.horizonDays, { n: value })}
                </Link>
              </Button>
            ))}
          </div>
        </div>
        <div role="group" aria-label={t.cashflow.scenario} className="space-y-2">
          <p className="text-sm font-medium">{t.cashflow.scenario}</p>
          <div className="flex flex-wrap gap-2">
            {SCENARIOS.map((value) => (
              <Button key={value} asChild variant={value === scenario ? "default" : "outline"}>
                <Link href={`?horizon=${horizon}&scenario=${value}`} aria-current={value === scenario ? "true" : undefined}>
                  {t.cashflow[SCENARIO_KEYS[value]]}
                </Link>
              </Button>
            ))}
          </div>
        </div>
      </div>

      {forecast.insufficient_data && (
        <Alert>
          <AlertDescription>{t.cashflow.insufficientData}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">{t.cashflow.status}</span>
        <Badge variant={tone}>{statusLabel(forecast.status, locale)}</Badge>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <KpiCard label={t.cashflow.openingTotal} value={formatMoney(BigInt(forecast.opening_total), currency, locale)} icon={Wallet} primary />
        <KpiCard label={t.cashflow.lowestBalance} value={formatMoney(BigInt(forecast.lowest_balance), currency, locale)} hint={forecast.lowest_balance_date} icon={TrendingDown} negative={BigInt(forecast.lowest_balance) < 0n} />
        <KpiCard label={t.cashflow.firstCritical} value={forecast.first_critical_date ?? t.cashflow.noCritical} icon={CalendarClock} negative={forecast.first_critical_date !== null} />
      </div>
      <Card className="min-w-0">
        <CardHeader><h2 className="text-base font-semibold">{t.cashflow.chartTable}</h2></CardHeader>
        <CardContent className="min-w-0">
          <ForecastChart
            key={`${horizon}-${scenario}`}
            forecast={forecast}
            currency={currency}
            locale={locale}
            labels={{
              balance: t.cashflow.chartBalance,
              inflow: t.cashflow.chartInflow,
              outflow: t.cashflow.chartOutflow,
              week: t.cashflow.chartWeek,
              table: t.cashflow.chartTable,
              independentScales: t.cashflow.independentScales,
            }}
          />
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t.cashflow.exportPdf}>
        {(["pdf", "xlsx"] as const).map((format) => (
          <Button key={format} asChild variant="outline" size="sm">
            <a href={previsionsExportHref(companyId, format, horizon, scenario)} download>
              <Download aria-hidden className="size-4" />
              {format === "pdf" ? t.cashflow.exportPdf : t.cashflow.exportXlsx}
            </a>
          </Button>
        ))}
        {manage ? (
          <>
            <InlineAction
              action={createCashflowSnapshotAction.bind(null, companyId, scenario)}
              label={t.cashflow.freeze}
              pendingLabel={t.common.pending}
              showSuccess
            />
            <Button asChild variant="outline" size="sm">
              <Link href="./previsions/reglages">
                <Lock aria-hidden className="size-4" />
                {t.cashflow.settings}
              </Link>
            </Button>
          </>
        ) : null}
      </div>

      <section className="min-w-0 space-y-3" aria-label={t.cashflow.accounts}>
        <h2 className="text-lg font-semibold">{t.cashflow.accounts}</h2>
        <DataTable label={t.cashflow.accounts}>
          <TableHeader>
            <TableRow>
              <TableHead>{t.cashflow.accountNumber}</TableHead>
              <TableHead>{t.cashflow.accountLabel}</TableHead>
              <TableHead className="text-right">{t.cashflow.accountOpening}</TableHead>
              <TableHead className="text-right">{t.cashflow.accountCommitted}</TableHead>
              {[30, 60, 90]
                .filter((mark) => mark <= forecast.horizon_days)
                .map((mark) => (
                  <TableHead key={mark} className="text-right">
                    {interpolate(t.cashflow.markLabel, { n: mark })}
                  </TableHead>
                ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {forecast.accounts.map((account) => (
              <TableRow key={account.account_id}>
                <TableCell>{account.number}</TableCell>
                <TableCell>{account.label}</TableCell>
                <TableCell className="text-right">
                  {formatMoney(BigInt(account.opening), currency, locale)}
                </TableCell>
                <TableCell className="text-right">
                  {formatMoney(BigInt(account.committed_net), currency, locale)}
                </TableCell>
                {[30, 60, 90]
                  .filter((mark) => mark <= forecast.horizon_days)
                  .map((mark) => (
                    <TableCell key={mark} className="text-right">
                      {account.balances_at_marks[mark] !== undefined
                        ? formatMoney(BigInt(account.balances_at_marks[mark]), currency, locale)
                        : "—"}
                    </TableCell>
                  ))}
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      </section>

      <details className="min-w-0 space-y-3 rounded-xl border bg-card p-4">
        <summary className="cursor-pointer text-lg font-semibold">
          {t.cashflow.dailyTable} —{" "}
          {interpolate(t.cashflow.dailySummary, { n: forecast.days.length })}
        </summary>
        <DataTable label={t.cashflow.dailyTable} density="compact">
          <TableHeader>
            <TableRow>
              <TableHead>{t.cashflow.date}</TableHead>
              <TableHead className="text-right">{t.cashflow.committedInflow}</TableHead>
              <TableHead className="text-right">{t.cashflow.committedOutflow}</TableHead>
              <TableHead className="text-right">{t.cashflow.estimatedInflow}</TableHead>
              <TableHead className="text-right">{t.cashflow.estimatedOutflow}</TableHead>
              <TableHead className="text-right">{t.cashflow.balance}</TableHead>
              <TableHead>{t.cashflow.status}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {forecast.days.map((day) => (
              <TableRow key={day.flow_date}>
                <TableCell>{day.flow_date}</TableCell>
                <TableCell className="text-right">{formatMoney(BigInt(day.committed_inflow), currency, locale)}</TableCell>
                <TableCell className="text-right">{formatMoney(BigInt(day.committed_outflow), currency, locale)}</TableCell>
                <TableCell className="text-right">{formatMoney(BigInt(day.estimated_inflow), currency, locale)}</TableCell>
                <TableCell className="text-right">{formatMoney(BigInt(day.estimated_outflow), currency, locale)}</TableCell>
                <TableCell className="text-right font-semibold">{formatMoney(BigInt(day.balance), currency, locale)}</TableCell>
                <TableCell>
                  <Badge variant={statusVariant(day.status)}>{statusLabel(day.status, locale)}</Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      </details>

      <details className="space-y-3 rounded-xl border bg-card p-4">
        <summary className="cursor-pointer text-lg font-semibold">
          {t.cashflow.assumptions}
        </summary>
        <p>
          {interpolate(t.cashflow.assumptionsScenario, {
            inflow: `${forecast.assumptions.inflow_coefficient.numerator}/${forecast.assumptions.inflow_coefficient.denominator}`,
            outflow: `${forecast.assumptions.outflow_coefficient.numerator}/${forecast.assumptions.outflow_coefficient.denominator}`,
            delay: String(forecast.assumptions.inflow_delay_days),
            advance: String(forecast.assumptions.outflow_advance_days),
          })}
        </p>
        <p>
          {interpolate(t.cashflow.assumptionsScope, {
            months: String(forecast.history_months_used),
          })}
        </p>
        <h3 className="mt-2 font-medium">{t.cashflow.excludedDrafts}</h3>
        {forecast.excluded_drafts.length === 0 ? (
          <p className="text-muted-foreground">{t.cashflow.noExcludedDrafts}</p>
        ) : (
          <ul>
            {forecast.excluded_drafts.map((draft) => (
              <li key={`${draft.entry_date}-${draft.label}`}>
                {draft.entry_date} — {draft.label}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-muted-foreground">{t.cashflow.expertNotice}</p>
      </details>

      <section className="min-w-0 space-y-3" aria-label={t.cashflow.snapshots}>
        <h2 className="text-lg font-semibold">{t.cashflow.snapshots}</h2>
        {snapshots.length === 0 ? (
          <p className="text-muted-foreground">{t.cashflow.snapshotsEmpty}</p>
        ) : (
          <DataTable label={t.cashflow.snapshots}>
            <TableHeader>
              <TableRow>
                <TableHead>{t.cashflow.snapshotAt}</TableHead>
                <TableHead>{t.cashflow.date}</TableHead>
                <TableHead>{t.cashflow.scenario}</TableHead>
                <TableHead className="text-right">{t.cashflow.balance}</TableHead>
                <TableHead>{t.cashflow.status}</TableHead>
                <TableHead>{t.cashflow.snapshotVsActual}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {snapshots.map((snapshot) => (
                <TableRow key={snapshot.id}>
                  <TableCell>{snapshot.generated_at}</TableCell>
                  <TableCell>{snapshot.as_of}</TableCell>
                  <TableCell>{t.cashflow[SCENARIO_KEYS[snapshot.scenario]]}</TableCell>
                  <TableCell className="text-right">
                    {formatMoney(BigInt(snapshot.opening_total), currency, locale)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(snapshot.status)}>
                      {statusLabel(snapshot.status, locale)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Link
                      href={`./previsions/instantanes/${snapshot.id}`}
                      className="text-sm underline underline-offset-4"
                    >
                      {t.cashflow.snapshotVsActual}
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </DataTable>
        )}
      </section>
    </>
  );
}
