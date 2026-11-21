import { Button } from "@/components/ui/button";
import { TableDensitySelect } from "@/components/table-density-select";
import { interpolate } from "@/lib/i18n/interpolate";
import { PAGE_SIZES, type TableDensity } from "@/lib/table-preferences";
import { PURCHASE_STATUSES, purchasesStatusLabel } from "./labels";
import type { Dictionary } from "./types";

/** Filtres de la liste des documents d'achat (kind + statut), soumis en GET :
 * l'état de la liste reste partageable par URL. */
export function PurchasesFilters({
  t,
  kindParam,
  statusParam,
  size, density, resetHref,
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
        <span className="text-muted-foreground text-xs">{t.purchases.kindLabel}</span>
        <select
          name="kind"
          defaultValue={kindParam ?? ""}
          aria-label={t.purchases.kindLabel}
          className="border-input bg-background min-h-11 max-w-full rounded-lg border px-3 text-sm"
        >
          <option value="">{t.purchases.filterAll}</option>
          <option value="supplier_invoice">{t.purchases.kinds.supplierInvoice}</option>
          <option value="supplier_credit_note">{t.purchases.kinds.supplierCreditNote}</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">{t.purchases.statusLabel}</span>
        <select
          name="statut"
          defaultValue={statusParam ?? ""}
          aria-label={t.purchases.statusLabel}
          className="border-input bg-background min-h-11 max-w-full rounded-lg border px-3 text-sm"
        >
          <option value="">{t.purchases.filterAll}</option>
          {PURCHASE_STATUSES.map((status: string) => (
            <option key={status} value={status}>
              {purchasesStatusLabel(t.purchases, status)}
            </option>
          ))}
        </select>
      </label>
      <select name="taille" aria-label={t.table.pageSize} defaultValue={String(size)} className="border-input bg-background min-h-11 rounded-lg border px-3 text-sm">
        {PAGE_SIZES.map(value => <option key={value} value={value}>{interpolate(t.table.rowsPerPage, { count: value })}</option>)}
      </select>
      <TableDensitySelect density={density} labels={t.table} />
      <Button type="submit" className="min-h-11">
        {t.purchases.apply}
      </Button>
      <Button asChild variant="ghost" className="min-h-11 whitespace-normal"><a href={resetHref}>{t.table.reset}</a></Button>
    </form>
  );
}
