import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatDate } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";

type Year = { id: string; start_date: string; end_date: string };

/** Filtre de période des états (formulaire GET : fonctionne sans JavaScript).
 * `dateFrom` est optionnel : les états qui ne se lisent qu'à une date d'arrêté
 * (bilan, résultat, flux de trésorerie) n'exposent que le champ « au » et la
 * base de la période reste l'ouverture de l'exercice. */
export function PeriodFilter({
  years,
  yearId,
  dateFrom,
  dateTo,
  locale,
  labels,
  children,
}: {
  years: Year[];
  yearId: string;
  dateFrom?: string;
  dateTo: string;
  locale: Locale;
  labels: { fiscalYear: string; from: string; to: string; show: string };
  children?: ReactNode;
}) {
  return (
    <form method="get" className="mb-6 flex min-w-0 flex-wrap items-end gap-3 rounded-xl border bg-card p-4">
      <div className="flex min-w-0 max-w-full flex-col gap-1.5">
        <Label htmlFor="periode-exercice">{labels.fiscalYear}</Label>
        <select
          id="periode-exercice"
          name="exercice"
          defaultValue={yearId}
          className="border-input bg-background min-h-11 min-w-0 max-w-full rounded-lg border px-3 text-sm"
        >
          {years.map((year) => (
            <option key={year.id} value={year.id}>
              {formatDate(year.start_date, locale)} – {formatDate(year.end_date, locale)}
            </option>
          ))}
        </select>
      </div>
      {dateFrom != null ? (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="periode-du">{labels.from}</Label>
          <Input id="periode-du" name="du" type="date" defaultValue={dateFrom} className="min-h-11 w-auto max-w-full" />
        </div>
      ) : null}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="periode-au">{labels.to}</Label>
        <Input id="periode-au" name="au" type="date" defaultValue={dateTo} className="min-h-11 w-auto max-w-full" />
      </div>
      {children}
      <Button type="submit" className="min-h-11">
        {labels.show}
      </Button>
    </form>
  );
}
