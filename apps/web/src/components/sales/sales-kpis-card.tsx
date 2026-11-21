import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Banknote, CalendarClock, CircleAlert, Percent } from "lucide-react";
import { KpiCard } from "@/components/kpi-card";
import { DataTable } from "@/components/data-table";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatMoney } from "@/lib/format";
import type { Dictionary, SalesKpis } from "./types";

const POURCENT = 100;

/** Indicateurs de recouvrement (lot B-4) : encours, part échue, DSO en jours
 * de ventes, taux de recouvrement et top débiteurs — calculés en lecture depuis
 * les mêmes soldes que la balance âgée 4C (aucun statut dérivé stocké). */
export function SalesKpisCard({
  kpis,
  currency,
  t,
}: {
  kpis: SalesKpis;
  currency: string;
  t: Dictionary;
}) {
  const top = kpis.top_debtors;
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.sales.kpisTitle}</CardTitle>
        <p className="text-muted-foreground text-sm">{t.sales.kpisSubtitle}</p>
      </CardHeader>
      <CardContent>
        <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard primary icon={Banknote} label={t.sales.kpisOutstanding} value={formatMoney(kpis.outstanding_ttc, currency)} />
          <KpiCard icon={CircleAlert} label={t.sales.kpisOverdueShare} value={formatMoney(kpis.overdue_ttc, currency)} hint={`${(kpis.overdue_share_bp / 100).toFixed(1)} %`} />
          <KpiCard icon={CalendarClock} label={t.sales.kpisDso} value={`${kpis.dso_days} j`} hint={`${kpis.lookback_days} ${t.sales.kpisWindow}`} />
          <KpiCard icon={Percent} label={t.sales.kpisRecovery} value={`${(kpis.recovery_rate_bp / POURCENT).toFixed(1)} %`} hint={`${formatMoney(kpis.collected_ttc, currency)} / ${formatMoney(kpis.billed_ttc, currency)}`} />
        </div>
        <p className="text-muted-foreground mt-3 text-xs">{t.sales.kpisLateAverage}</p>
        {top.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-sm font-medium">{t.sales.kpisTopDebtors}</p>
            <DataTable label={t.sales.kpisTopDebtors}>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.sales.reminderPartner}</TableHead>
                  <TableHead className="text-right">{t.sales.agingTotal}</TableHead>
                  <TableHead className="text-right">{t.sales.reminderLate}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {top.map((debtor) => (
                  <TableRow key={debtor.partner_id}>
                    <TableCell>{debtor.partner_name}</TableCell>
                    <TableCell className="text-right">
                      {formatMoney(debtor.outstanding_ttc, currency)}
                    </TableCell>
                    <TableCell className="text-right">{debtor.max_days_late} j</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </DataTable>
          </div>
        )}
        <p className="text-muted-foreground mt-4 text-xs">{t.sales.kpisNotice}</p>
      </CardContent>
    </Card>
  );
}
