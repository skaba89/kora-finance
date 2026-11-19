import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { createPurchaseDocumentAction } from "@/lib/actions/purchases";
import { formatMoney } from "@/lib/format";
import type { Dictionary, PartnersPage, PayablesAging } from "./types";

const AGING_BUCKETS = ["not_due", "d1_30", "d31_60", "d61_90", "d90_plus"] as const;

/** Échéancier fournisseurs par ancienneté de dette, à la date de calcul. */
export function PurchasesAgingCard({
  aging,
  currency,
  t,
}: {
  aging: PayablesAging;
  currency: string;
  t: Dictionary;
}) {
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.purchases.agingTitle}</CardTitle>
        <p className="text-muted-foreground text-sm">
          {t.purchases.agingAsOf} {aging.as_of} —{" "}
          {formatMoney(aging.grand_total_ttc, currency)}
        </p>
      </CardHeader>
      <CardContent>
        {aging.grand_total_ttc === 0 ? (
          <p className="text-muted-foreground text-sm">{t.purchases.agingEmpty}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.purchases.agingTitle}</TableHead>
                <TableHead>{t.purchases.agingCount}</TableHead>
                <TableHead className="text-right">{t.purchases.agingTotal}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {AGING_BUCKETS.map((bucket) => {
                const line = aging.buckets[bucket];
                if (!line || line.count === 0) return null;
                return (
                  <TableRow key={bucket}>
                    <TableCell>
                      {(t.purchases.agingBucket as Record<string, string>)[bucket]}
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

/** Création d'un brouillon fournisseur (facture, avoir) : 3 lignes maximum
 * avec remise et TVA (taux ou exonération motivée). Aucune écriture à la
 * création. */
export function PurchasesCreateDocumentCard({
  companyId,
  partners,
  rateOptions,
  t,
}: {
  companyId: string;
  partners: PartnersPage;
  rateOptions: { value: string; label: string }[];
  t: Dictionary;
}) {
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.purchases.createTitle}</CardTitle>
      </CardHeader>
      <CardContent>
        <ActionForm
          action={createPurchaseDocumentAction.bind(null, companyId)}
          className="space-y-4"
          submitLabel={t.purchases.create}
          pendingLabel={t.common.pending}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <SelectField
              label={t.purchases.kindLabel}
              name="doc_kind"
              required
              options={[
                { value: "supplier_invoice", label: t.purchases.kinds.supplierInvoice },
                {
                  value: "supplier_credit_note",
                  label: t.purchases.kinds.supplierCreditNote,
                },
              ]}
            />
            <SelectField
              label={t.purchases.partnerLabel}
              name="partner_id"
              required
              options={[
                { value: "", label: t.purchases.partnerPlaceholder },
                ...partners.items.map((partner) => ({
                  value: partner.id,
                  label: partner.name,
                })),
              ]}
            />
            <Field label={t.purchases.reference} name="reference" />
          </div>
          {[1, 2, 3].map((slot) => (
            <fieldset key={slot} className="grid gap-3 rounded-md border p-3 sm:grid-cols-6">
              <legend className="text-muted-foreground px-1 text-xs">
                {t.purchases.lineTitle} {slot}
              </legend>
              <div className="sm:col-span-2">
                <Field label={t.purchases.lineLabel} name={`label_${slot}`} />
              </div>
              <Field
                label={t.purchases.lineQty}
                name={`qty_${slot}`}
                type="number"
                step="0.001"
                min="0.001"
              />
              <Field
                label={t.purchases.linePrice}
                name={`price_${slot}`}
                type="number"
                min="0"
              />
              <Field
                label={t.purchases.lineDiscount}
                name={`discount_${slot}`}
                type="number"
                min="0"
                max="100"
                step="0.01"
              />
              <SelectField
                label={t.purchases.lineTax}
                name={`tax_mode_${slot}`}
                options={[
                  { value: "rate", label: t.purchases.lineTaxRate },
                  { value: "exempt", label: t.purchases.lineTaxExempt },
                ]}
              />
              <div className="sm:col-span-2">
                <SelectField
                  label={t.purchases.lineTaxRateChoice}
                  name={`tax_rate_${slot}`}
                  options={[
                    { value: "", label: t.purchases.lineTaxNone },
                    ...rateOptions,
                  ]}
                />
              </div>
              <div className="sm:col-span-3">
                <Field label={t.purchases.lineTaxReason} name={`tax_reason_${slot}`} />
              </div>
            </fieldset>
          ))}
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t.purchases.dueOn} name="due_on" type="date" />
            <Field label={t.purchases.notes} name="notes" />
          </div>
          <p className="text-muted-foreground text-xs">{t.purchases.createHint}</p>
          <p className="text-muted-foreground text-xs">{t.purchases.mentionsNotice}</p>
        </ActionForm>
      </CardContent>
    </Card>
  );
}
