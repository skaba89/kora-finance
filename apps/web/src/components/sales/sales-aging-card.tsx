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
import type { Dictionary, SalesAging } from "./types";

const AGING_BUCKETS = ["not_due", "d1_30", "d31_60", "d61_90", "d90_plus"] as const;

/** Balance âgée clients par ancienneté de créance, à la date de calcul. */
export function SalesAgingCard({
  aging,
  currency,
  t,
}: {
  aging: SalesAging;
  currency: string;
  t: Dictionary;
}) {
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.sales.agingTitle}</CardTitle>
        <p className="text-muted-foreground text-sm">
          {t.sales.agingAsOf} {aging.as_of} — {formatMoney(aging.grand_total_ttc, currency)}
        </p>
      </CardHeader>
      <CardContent>
        {aging.grand_total_ttc === 0 ? (
          <p className="text-muted-foreground text-sm">{t.sales.agingEmpty}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.sales.agingTitle}</TableHead>
                <TableHead>{t.sales.agingCount}</TableHead>
                <TableHead className="text-right">{t.sales.agingTotal}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {AGING_BUCKETS.map((bucket) => {
                const line = aging.buckets[bucket];
                if (!line || line.count === 0) return null;
                return (
                  <TableRow key={bucket}>
                    <TableCell>
                      {(t.sales.agingBucket as Record<string, string>)[bucket]}
                    </TableCell>
                    <TableCell>{line.count}</TableCell>
                    <TableCell className="text-right">
                      {formatMoney(line.total_ttc, currency)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
