import { Button } from "@/components/ui/button";
import { PURCHASE_STATUSES, purchasesStatusLabel } from "./labels";
import type { Dictionary } from "./types";

/** Filtres de la liste des documents d'achat (kind + statut), soumis en GET :
 * l'état de la liste reste partageable par URL. */
export function PurchasesFilters({
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
          <option value="">{t.purchases.filterAll}</option>
          <option value="supplier_invoice">{t.purchases.kinds.supplierInvoice}</option>
          <option value="supplier_credit_note">{t.purchases.kinds.supplierCreditNote}</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">{t.common.filter}</span>
        <select
          name="statut"
          defaultValue={statusParam ?? ""}
          aria-label={t.common.filter}
          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
        >
          <option value="">{t.purchases.filterAll}</option>
          {PURCHASE_STATUSES.map((status: string) => (
            <option key={status} value={status}>
              {purchasesStatusLabel(t.purchases, status)}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" variant="outline" size="sm">
        {t.purchases.apply}
      </Button>
    </form>
  );
}
