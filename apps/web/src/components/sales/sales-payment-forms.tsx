import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createDepositAction, createPaymentAction } from "@/lib/actions/sales";
import { formatMoney } from "@/lib/format";
import { SALES_PAYMENT_METHODS } from "./labels";
import type { Dictionary, PartnersPage, SalesDocumentsPage } from "./types";

function MethodSelect({ t }: { t: Dictionary }) {
  return (
    <SelectField
      label={t.sales.paymentMethod}
      name="method"
      options={SALES_PAYMENT_METHODS.map((method) => ({
        value: method,
        label: (t.sales.methods as Record<string, string>)[method] ?? method,
      }))}
    />
  );
}

/** Enregistrement d'un règlement client sur une facture émise restant due. */
export function SalesPaymentFormCard({
  companyId,
  documents,
  t,
}: {
  companyId: string;
  documents: SalesDocumentsPage;
  t: Dictionary;
}) {
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.sales.paymentFormTitle}</CardTitle>
      </CardHeader>
      <CardContent>
        <ActionForm
          action={createPaymentAction.bind(null, companyId)}
          className="space-y-4"
          submitLabel={t.sales.paymentRecord}
          pendingLabel={t.common.pending}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <SelectField
              label={t.sales.paymentDoc}
              name="document_id"
              required
              options={[
                { value: "", label: t.sales.paymentDocPlaceholder },
                ...documents.items
                  .filter(
                    (document) =>
                      document.doc_kind === "invoice" &&
                      document.status === "ISSUED" &&
                      (document.outstanding_ttc ?? 0) > 0,
                  )
                  .map((document) => ({
                    value: document.id,
                    label: `FAC-${document.number} — ${t.sales.outstandingLabel} ${formatMoney(document.outstanding_ttc ?? 0, document.currency)}`,
                  })),
              ]}
            />
            <Field
              label={t.sales.paymentAmount}
              name="amount"
              type="number"
              min="1"
              step="1"
              required
            />
            <Field label={t.sales.paymentDate} name="paid_on" type="date" required />
            <MethodSelect t={t} />
            <Field label={t.sales.paymentReference} name="reference" />
          </div>
          <p className="text-muted-foreground text-xs">{t.sales.paymentHint}</p>
        </ActionForm>
      </CardContent>
    </Card>
  );
}

/** Enregistrement d'un acompte client (B-3) : encaissé avant émission, lettré
 * à la facture quand elle existe. */
export function SalesDepositFormCard({
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
        <CardTitle>{t.sales.acompteTitle}</CardTitle>
      </CardHeader>
      <CardContent>
        <ActionForm
          action={createDepositAction.bind(null, companyId)}
          className="space-y-4"
          submitLabel={t.sales.acompteRecord}
          pendingLabel={t.common.pending}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <SelectField
              label={t.sales.acomptePartner}
              name="partner_id"
              required
              options={[
                { value: "", label: t.sales.acomptePartner },
                ...partners.items
                  .filter((partner) => partner.is_client)
                  .map((partner) => ({ value: partner.id, label: partner.name })),
              ]}
            />
            <Field
              label={t.sales.acompteAmount}
              name="amount"
              type="number"
              min="1"
              step="1"
              required
            />
            <Field label={t.sales.paymentDate} name="paid_on" type="date" required />
            <MethodSelect t={t} />
            <Field label={t.sales.paymentReference} name="reference" />
          </div>
          <p className="text-muted-foreground text-xs">{t.sales.acompteHint}</p>
        </ActionForm>
      </CardContent>
    </Card>
  );
}
