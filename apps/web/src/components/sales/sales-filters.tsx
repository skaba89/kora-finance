import { Button } from "@/components/ui/button";
import { SALES_STATUSES, salesStatusLabel } from "./labels";
import type { Dictionary } from "./types";

/** Filtres de la liste des documents de vente (kind + statut), soumis en GET :
 * l'état de la liste reste partageable par URL. */
export function SalesFilters({
  t,
  kindParam,
  statusParam,
}: {
  t: Dictionary;
  kindParam?: string;
  statusParam?: string;
}) {
  return (
    <form method="get" className="mb-4 flex flex-wrap items-end gap-3 text-sm">
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">{t.common.filter}</span>
        <select
          name="kind"
          defaultValue={kindParam ?? ""}
          aria-label={t.common.filter}
          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
        >
          <option value="">{t.sales.filterAll}</option>
          <option value="quote">{t.sales.kinds.quote}</option>
          <option value="invoice">{t.sales.kinds.invoice}</option>
          <option value="credit_note">{t.sales.kinds.creditNote}</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">{t.sales.filterStatus}</span>
        <select
          name="statut"
          defaultValue={statusParam ?? ""}
          aria-label={t.sales.filterStatus}
          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
        >
          <option value="">{t.sales.filterAll}</option>
          {SALES_STATUSES.map((status: string) => (
            <option key={status} value={status}>
              {salesStatusLabel(t.sales, status)}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" variant="outline" size="sm">
        {t.sales.apply}
      </Button>
    </form>
  );
}
