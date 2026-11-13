import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { type ForecastScenario, statusLabel, statusVariant } from "@/lib/cashflow";
import { getCashflowSnapshot, getCashflowVsActual, getCompany } from "@/lib/dal";
import { formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.cashflow.snapshotVsActual };
}

const SCENARIO_KEYS: Record<
  ForecastScenario,
  "scenarioOptimiste" | "scenarioNeutre" | "scenarioPrudent"
> = {
  OPTIMISTE: "scenarioOptimiste",
  NEUTRE: "scenarioNeutre",
  PRUDENT: "scenarioPrudent",
};

/**
 * Détail d'un instantané figé et comparaison au réalisé (écritures validées
 * postérieures) — Phase 3E. Le prévisionnel reste inchangé : c'est la base
 * de la comparaison, jamais réécrite.
 */
export default async function SnapshotPage({
  params,
}: PageProps<
  "/[lang]/dossiers/[companyId]/tresorerie/previsions/instantanes/[snapshotId]"
>) {
  const { companyId, snapshotId } = await params;
  const [{ t, locale }, company, snapshot, vsActual] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getCashflowSnapshot(companyId, snapshotId),
    getCashflowVsActual(companyId, snapshotId),
  ]);
  // getCompany interrompt le rendu (404) si le dossier est inaccessible ; les
  // routes cashflow 404 également hors isolation (read() gère les deux cas).
  const { currency } = company.company;

  const hasActual = vsActual.days.some((day) => day.actual_net !== "0");

  return (
    <>
      <PageHeader
        title={interpolate(t.cashflow.vsSnapshotOf, {
          date: snapshot.as_of,
          scenario: t.cashflow[SCENARIO_KEYS[snapshot.scenario]],
        })}
        subtitle={t.cashflow.snapshotVsActual}
      />

      <div className="flex flex-wrap items-center gap-4">
        <Badge variant={statusVariant(snapshot.status)}>
          {statusLabel(snapshot.status, locale)}
        </Badge>
        <span>
          {t.cashflow.openingTotal} :{" "}
          <strong>{formatMoney(BigInt(snapshot.opening_total), currency, locale)}</strong>
        </span>
        <span>
          {t.cashflow.lowestBalance} :{" "}
          <strong>{formatMoney(BigInt(snapshot.lowest_balance), currency, locale)}</strong>{" "}
          ({snapshot.lowest_balance_date})
        </span>
        <span>
          {t.cashflow.firstCritical} :{" "}
          <strong>{snapshot.first_critical_date ?? t.cashflow.noCritical}</strong>
        </span>
      </div>

      <p>{interpolate(t.cashflow.vsComparedThrough, { date: vsActual.compared_through })}</p>

      {hasActual ? (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.cashflow.date}</TableHead>
                <TableHead className="text-right">{t.cashflow.vsForecast}</TableHead>
                <TableHead className="text-right">{t.cashflow.vsActualCol}</TableHead>
                <TableHead className="text-right">{t.cashflow.vsVariance}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {vsActual.days.map((day) => (
                <TableRow key={day.flow_date}>
                  <TableCell>{day.flow_date}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(BigInt(day.forecast_net), currency, locale)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(BigInt(day.actual_net), currency, locale)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(BigInt(day.variance), currency, locale)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
            <TableFooter>
              <TableRow>
                <TableCell className="font-medium">{t.cashflow.vsTotals}</TableCell>
                <TableCell className="text-right font-medium tabular-nums">
                  {formatMoney(BigInt(vsActual.forecast_total_net), currency, locale)}
                </TableCell>
                <TableCell className="text-right font-medium tabular-nums">
                  {formatMoney(BigInt(vsActual.actual_total_net), currency, locale)}
                </TableCell>
                <TableCell className="text-right font-medium tabular-nums">
                  {formatMoney(BigInt(vsActual.variance), currency, locale)}
                </TableCell>
              </TableRow>
            </TableFooter>
          </Table>

          {vsActual.top_deviations.length > 0 ? (
            <section aria-label={t.cashflow.vsTopDeviations}>
              <h2 className="text-lg font-semibold">{t.cashflow.vsTopDeviations}</h2>
              <ul>
                {vsActual.top_deviations.map((day) => (
                  <li key={day.flow_date}>
                    {day.flow_date} —{" "}
                    {formatMoney(BigInt(day.variance), currency, locale)}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : (
        <p className="text-muted-foreground">{t.cashflow.vsNoActual}</p>
      )}

      <Link href=".." className="text-sm underline underline-offset-4">
        {t.cashflow.backToForecast}
      </Link>
    </>
  );
}
