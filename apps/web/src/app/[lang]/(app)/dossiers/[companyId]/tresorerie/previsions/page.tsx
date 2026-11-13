import type { Metadata } from "next";
import Link from "next/link";
import { Download, Lock } from "lucide-react";

import { ForecastChart } from "@/components/cashflow/forecast-chart";
import { InlineAction } from "@/components/forms/inline-action";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
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
          <strong>{formatMoney(BigInt(forecast.opening_total), currency, locale)}</strong>
        </span>
        <span>
          {t.cashflow.lowestBalance} :{" "}
          <strong>{formatMoney(BigInt(forecast.lowest_balance), currency, locale)}</strong>{" "}
          ({forecast.lowest_balance_date})
        </span>
        <span>
          {t.cashflow.firstCritical} :{" "}
          <strong>{forecast.first_critical_date ?? t.cashflow.noCritical}</strong>
        </span>
      </div>

      <ForecastChart
        forecast={forecast}
        currency={currency}
        locale={locale}
        labels={{
          balance: t.cashflow.chartBalance,
          inflow: t.cashflow.chartInflow,
          outflow: t.cashflow.chartOutflow,
          week: t.cashflow.chartWeek,
          table: t.cashflow.chartTable,
        }}
      />

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
                  <Badge variant={statusVariant(day.status)}>{statusLabel(day.status, locale)}</Badge>
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
          </Table>
        )}
      </section>
    </>
  );
}
