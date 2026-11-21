import { Button } from "@/components/ui/button";
import { interpolate } from "@/lib/i18n/interpolate";
import { PAGE_SIZES, type TableDensity } from "@/lib/table-preferences";
import { SALES_STATUSES, salesStatusLabel } from "./labels";
import type { Dictionary } from "./types";

/** Filtres de la liste des documents de vente (kind + statut), soumis en GET :
 * l'état de la liste reste partageable par URL. */
export function SalesFilters({
  t,
  kindParam,
  statusParam,
  size,
  density,
  resetHref,
}: {
  t: Dictionary;
  kindParam?: string;
  statusParam?: string;
  size: number;
  density: TableDensity;
  resetHref: string;
}) {
  return (
    <form key={JSON.stringify([kindParam, statusParam, size, density])} method="get" className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border bg-card p-4 text-sm">
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">{t.common.filter}</span>
        <select
          name="kind"
          defaultValue={kindParam ?? ""}
          aria-label={t.common.filter}
          className="border-input bg-background min-h-11 max-w-full rounded-lg border px-3 text-sm"
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
          className="border-input bg-background min-h-11 max-w-full rounded-lg border px-3 text-sm"
        >
          <option value="">{t.sales.filterAll}</option>
          {SALES_STATUSES.map((status: string) => (
            <option key={status} value={status}>
              {salesStatusLabel(t.sales, status)}
            </option>
          ))}
        </select>
      </label>
      <select name="taille" aria-label={t.table.pageSize} defaultValue={String(size)} className="border-input bg-background min-h-11 max-w-full rounded-lg border px-3 text-sm">
        {PAGE_SIZES.map(value => <option key={value} value={value}>{interpolate(t.table.rowsPerPage, { count: value })}</option>)}
      </select>
      <select name="densite" aria-label={t.table.density} defaultValue={density} className="border-input bg-background min-h-11 rounded-lg border px-3 text-sm">
        <option value="comfortable">{t.table.comfortable}</option>
        <option value="compact">{t.table.compact}</option>
      </select>
      <Button type="submit" className="min-h-11">
        {t.sales.apply}
      </Button>
      <Button asChild variant="ghost" className="min-h-11 whitespace-normal"><a href={resetHref}>{t.table.reset}</a></Button>
    </form>
  );
}
