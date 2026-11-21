import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createAdvanceAction, createPurchasePaymentAction } from "@/lib/actions/purchases";
import { formatMoney } from "@/lib/format";
import { PURCHASE_PAYMENT_METHODS } from "./labels";
import type { Dictionary, PartnersPage, PurchaseDocumentsPage } from "./types";

function MethodSelect({ t }: { t: Dictionary }) {
  return (
    <SelectField
      label={t.purchases.paymentMethod}
      name="method"
      options={PURCHASE_PAYMENT_METHODS.map((method) => ({
        value: method,
        label: (t.purchases.methods as Record<string, string>)[method] ?? method,
      }))}
    />
  );
}

/** Enregistrement d'un décaissement fournisseur sur une facture émise restant
 * due. */
export function PurchasesPaymentFormCard({
  companyId,
  documents,
  t,
}: {
  companyId: string;
  documents: PurchaseDocumentsPage;
  t: Dictionary;
}) {
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.purchases.paymentFormTitle}</CardTitle>
        <p className="text-muted-foreground text-sm">{t.purchases.paymentPageHint}</p>
      </CardHeader>
      <CardContent>
        <ActionForm
          action={createPurchasePaymentAction.bind(null, companyId)}
          className="space-y-4"
          submitLabel={t.purchases.paymentRecord}
          pendingLabel={t.common.pending}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <SelectField
              label={t.purchases.paymentDoc}
              name="document_id"
              required
              options={[
                { value: "", label: t.purchases.paymentDocPlaceholder },
                ...documents.items
                  .filter(
                    (document) =>
                      document.doc_kind === "supplier_invoice" &&
                      document.status === "ISSUED" &&
                      (document.outstanding_ttc ?? 0) > 0,
                  )
                  .map((document) => ({
                    value: document.id,
                    label: `FACH-${document.number} — ${t.purchases.outstandingLabel} ${formatMoney(document.outstanding_ttc ?? 0, document.currency)}`,
                  })),
              ]}
            />
            <Field
              label={t.purchases.paymentAmount}
              name="amount"
              type="number"
              min="1"
              step="1"
              required
            />
            <Field label={t.purchases.paymentDate} name="paid_on" type="date" required />
            <MethodSelect t={t} />
            <Field label={t.purchases.paymentReference} name="reference" />
          </div>
          <p className="text-muted-foreground text-xs">{t.purchases.paymentHint}</p>
        </ActionForm>
      </CardContent>
    </Card>
  );
}

/** Enregistrement d'une avance fournisseur (B-3) : décaissé avant réception,
 * lettré à la facture quand elle existe. */
export function PurchasesAdvanceFormCard({
  companyId,
  partners,
  t,
}: {
  companyId: string;
  partners: PartnersPage;
  t: Dictionary;
}) {
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.purchases.advanceTitle}</CardTitle>
      </CardHeader>
      <CardContent>
        <ActionForm
          action={createAdvanceAction.bind(null, companyId)}
          className="space-y-4"
          submitLabel={t.purchases.advanceRecord}
          pendingLabel={t.common.pending}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <SelectField
              label={t.purchases.advancePartner}
              name="partner_id"
              required
              options={[
                { value: "", label: t.purchases.advancePartner },
                ...partners.items
                  .filter((partner) => partner.is_supplier)
                  .map((partner) => ({ value: partner.id, label: partner.name })),
              ]}
            />
            <Field
              label={t.purchases.advanceAmount}
              name="amount"
              type="number"
              min="1"
              step="1"
              required
            />
            <Field label={t.purchases.paymentDate} name="paid_on" type="date" required />
            <MethodSelect t={t} />
            <Field label={t.purchases.paymentReference} name="reference" />
          </div>
          <p className="text-muted-foreground text-xs">{t.purchases.advanceHint}</p>
        </ActionForm>
      </CardContent>
    </Card>
  );
}
