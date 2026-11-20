import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
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
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-muted-foreground text-sm">{t.sales.kpisOutstanding}</dt>
            <dd className="text-lg font-medium">{formatMoney(kpis.outstanding_ttc, currency)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-sm">{t.sales.kpisOverdueShare}</dt>
            <dd className="text-lg font-medium">
              {formatMoney(kpis.overdue_ttc, currency)} ({(kpis.overdue_share_bp / 100).toFixed(1)} %)
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-sm">{t.sales.kpisDso}</dt>
            <dd className="text-lg font-medium">
              {kpis.dso_days} j
              <span className="text-muted-foreground text-sm">
                {" "}
                ({kpis.lookback_days} {t.sales.kpisWindow})
              </span>
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-sm">{t.sales.kpisRecovery}</dt>
            <dd className="text-lg font-medium">
              {(kpis.recovery_rate_bp / POURCENT).toFixed(1)} %
              <span className="text-muted-foreground text-sm">
                {" "}
                ({formatMoney(kpis.collected_ttc, currency)} / {formatMoney(kpis.billed_ttc, currency)})
              </span>
            </dd>
          </div>
        </dl>
        <p className="text-muted-foreground mt-3 text-xs">{t.sales.kpisLateAverage}</p>
        {top.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-sm font-medium">{t.sales.kpisTopDebtors}</p>
            <Table>
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
            </Table>
          </div>
        )}
        <p className="text-muted-foreground mt-4 text-xs">{t.sales.kpisNotice}</p>
      </CardContent>
    </Card>
  );
}
