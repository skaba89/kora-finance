import type { Metadata } from "next";
import Link from "next/link";

import { ForecastChart } from "@/components/cashflow/forecast-chart";
import { ExportLinks } from "@/components/ledger/export-links";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  HORIZONS,
  SCENARIOS,
  statusLabel,
  statusTone,
  type ForecastHorizon,
  type ForecastScenario,
} from "@/lib/cashflow";
import { getCashflowForecast, getCashflowSettings, getCashflowSnapshots } from "@/lib/dal";
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

  const horizon = parseHorizon(one(query.horizon));
  const scenario = parseScenario(one(query.scenario));

  const [forecast, settings, snapshots] = await Promise.all([
    getCashflowForecast(companyId, { horizon, scenario }),
    getCashflowSettings(companyId),
    getCashflowSnapshots(companyId),
  ]);

  const tone = statusTone(forecast.status);

  return (
    <>
      <PageHeader title={t.cashflow.title} subtitle={t.cashflow.subtitle} />

      <div className="flex flex-wrap items-center gap-2">
        {HORIZONS.map((value) => (
          <Link
            key={value}
            href={`?horizon=${value}&scenario=${scenario}`}
            className={value === horizon ? "underline" : "text-muted-foreground"}
          >
            {interpolate(t.cashflow.horizonDays, { n: value })}
          </Link>
        ))}
        <span className="mx-2 text-muted-foreground">·</span>
        {SCENARIOS.map((value) => (
          <Link
            key={value}
            href={`?horizon=${horizon}&scenario=${value}`}
            className={value === scenario ? "underline" : "text-muted-foreground"}
          >
            {t.cashflow[SCENARIO_KEYS[value]]}
          </Link>
        ))}
      </div>

      {forecast.insufficient_data && (
        <Alert>
          <AlertDescription>{t.cashflow.insufficientData}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-4">
        <Badge variant={tone}>{statusLabel(forecast.status, locale)}</Badge>
        <span>
          {t.cashflow.openingTotal} :{" "}
          <strong>{formatMoney(forecast.opening_total, company.currency, locale)}</strong>
        </span>
        <span>
          {t.cashflow.lowestBalance} :{" "}
          <strong>{formatMoney(forecast.lowest_balance, company.currency, locale)}</strong>{" "}
          ({forecast.lowest_balance_date})
        </span>
        <span>
          {t.cashflow.firstCritical} :{" "}
          <strong>{forecast.first_critical_date ?? t.cashflow.noCritical}</strong>
        </span>
      </div>

      <ForecastChart
        forecast={forecast}
        currency={company.currency}
        locale={locale}
        labels={{
          balance: t.cashflow.chartBalance,
          inflow: t.cashflow.chartInflow,
          outflow: t.cashflow.chartOutflow,
          week: t.cashflow.chartWeek,
          table: t.cashflow.chartTable,
        }}
      />

      <ExportLinks
        base={`/api/v1/companies/${companyId}/cashflow/forecast/export`}
        params={{ format: ["pdf", "xlsx"], horizon: String(horizon), scenario }}
        labels={{ pdf: t.cashflow.exportPdf, xlsx: t.cashflow.exportXlsx }}
      />

      <section aria-label={t.cashflow.accounts}>
        <h2 className="text-lg font-semibold">{t.cashflow.accounts}</h2>
        <Table>
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
                  {formatMoney(account.opening, company.currency, locale)}
                </TableCell>
                <TableCell className="text-right">
                  {formatMoney(account.committed_net, company.currency, locale)}
                </TableCell>
                {[30, 60, 90]
                  .filter((mark) => mark <= forecast.horizon_days)
                  .map((mark) => (
                    <TableCell key={mark} className="text-right">
                      {account.balances_at_marks[mark] !== undefined
                        ? formatMoney(account.balances_at_marks[mark], company.currency, locale)
                        : "—"}
                    </TableCell>
                  ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      <details>
        <summary className="cursor-pointer text-lg font-semibold">
          {t.cashflow.dailyTable} —{" "}
          {interpolate(t.cashflow.dailySummary, { n: forecast.days.length })}
        </summary>
        <Table>
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
                <TableCell className="text-right">{day.committed_inflow}</TableCell>
                <TableCell className="text-right">{day.committed_outflow}</TableCell>
                <TableCell className="text-right">{day.estimated_inflow}</TableCell>
                <TableCell className="text-right">{day.estimated_outflow}</TableCell>
                <TableCell className="text-right">{day.balance}</TableCell>
                <TableCell>
                  <Badge variant={statusTone(day.status)}>{statusLabel(day.status, locale)}</Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </details>

      <details>
        <summary className="cursor-pointer text-lg font-semibold">
          {t.cashflow.assumptions}
        </summary>
        <p>
          {interpolate(t.cashflow.assumptionsScenario, {
            inflow: String((forecast.assumptions as Record<string, any>).inflow_coefficient?.numerator ?? 100) + "/" + String((forecast.assumptions as Record<string, any>).inflow_coefficient?.denominator ?? 100),
            outflow: String((forecast.assumptions as Record<string, any>).outflow_coefficient?.numerator ?? 100) + "/" + String((forecast.assumptions as Record<string, any>).outflow_coefficient?.denominator ?? 100),
            delay: String((forecast.assumptions as Record<string, any>).inflow_delay_days ?? 0),
            advance: String((forecast.assumptions as Record<string, any>).outflow_advance_days ?? 0),
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

      <section aria-label={t.cashflow.snapshots}>
        <h2 className="text-lg font-semibold">{t.cashflow.snapshots}</h2>
        {snapshots.length === 0 ? (
          <p className="text-muted-foreground">{t.cashflow.snapshotsEmpty}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.cashflow.snapshotAt}</TableHead>
                <TableHead>{t.cashflow.date}</TableHead>
                <TableHead>{t.cashflow.scenario}</TableHead>
                <TableHead className="text-right">{t.cashflow.balance}</TableHead>
                <TableHead>{t.cashflow.status}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {snapshots.map((snapshot) => (
                <TableRow key={snapshot.id}>
                  <TableCell>{snapshot.generated_at}</TableCell>
                  <TableCell>{snapshot.as_of}</TableCell>
                  <TableCell>{t.cashflow[SCENARIO_KEYS[snapshot.scenario]]}</TableCell>
                  <TableCell className="text-right">
                    {formatMoney(snapshot.opening_total, company.currency, locale)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusTone(snapshot.status)}>
                      {statusLabel(snapshot.status, locale)}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </>
  );
}
