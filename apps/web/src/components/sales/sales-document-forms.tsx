import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createDocumentAction, sendDocumentEmailAction } from "@/lib/actions/sales";
import { formatMoney } from "@/lib/format";
import { salesDocPrefix, salesKindLabel } from "./labels";
import type { Dictionary, PartnersPage, SalesDocumentsPage } from "./types";

/** Envoi du document par email (lien signé, note optionnelle). */
export function SalesEmailFormCard({
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
        <CardTitle>{t.sales.emailTitle}</CardTitle>
        <p className="text-muted-foreground text-sm">{t.sales.emailPageHint}</p>
      </CardHeader>
      <CardContent>
        <ActionForm
          action={sendDocumentEmailAction.bind(null, companyId)}
          className="space-y-4"
          submitLabel={t.sales.emailSend}
          pendingLabel={t.common.pending}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <SelectField
              label={t.sales.emailDoc}
              name="document_id"
              required
              options={[
                { value: "", label: t.sales.emailDocPlaceholder },
                ...documents.items
                  .filter(
                    (document) =>
                      document.number != null && document.status !== "CANCELLED",
                  )
                  .map((document) => ({
                    value: document.id,
                    label: `${salesDocPrefix(document.doc_kind)}-${document.number} — ${salesKindLabel(t.sales, document.doc_kind)} · ${formatMoney(document.total_ttc, document.currency)}`,
                  })),
              ]}
            />
            <Field
              label={t.sales.emailTo}
              name="to"
              type="email"
              placeholder={t.sales.emailToPlaceholder}
            />
            <Field label={t.sales.emailNote} name="note" />
          </div>
          <p className="text-muted-foreground text-xs">{t.sales.emailHint}</p>
        </ActionForm>
      </CardContent>
    </Card>
  );
}

/** Création d'un brouillon (devis, facture, avoir) : 3 lignes maximum avec
 * remise et TVA (taux ou exonération motivée). Aucune écriture à la création. */
export function SalesCreateDocumentCard({
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
        <CardTitle>{t.sales.createTitle}</CardTitle>
      </CardHeader>
      <CardContent>
        <ActionForm
          action={createDocumentAction.bind(null, companyId)}
          className="space-y-4"
          submitLabel={t.sales.create}
          pendingLabel={t.common.pending}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <SelectField
              label={t.sales.kindLabel}
              name="doc_kind"
              required
              options={[
                { value: "invoice", label: t.sales.kinds.invoice },
                { value: "quote", label: t.sales.kinds.quote },
                { value: "credit_note", label: t.sales.kinds.creditNote },
              ]}
            />
            <SelectField
              label={t.sales.partnerLabel}
              name="partner_id"
              required
              options={[
                { value: "", label: t.sales.partnerPlaceholder },
                ...partners.items.map((partner) => ({
                  value: partner.id,
                  label: partner.name,
                })),
              ]}
            />
            <Field label={t.sales.notes} name="notes" />
          </div>
          {[1, 2, 3].map((slot) => (
            <fieldset key={slot} className="grid gap-3 rounded-md border p-3 sm:grid-cols-6">
              <legend className="text-muted-foreground px-1 text-xs">
                {t.sales.lineTitle} {slot}
              </legend>
              <div className="sm:col-span-2">
                <Field label={t.sales.lineLabel} name={`label_${slot}`} />
              </div>
              <Field
                label={t.sales.lineQty}
                name={`qty_${slot}`}
                type="number"
                step="0.001"
                min="0.001"
              />
              <Field label={t.sales.linePrice} name={`price_${slot}`} type="number" min="0" />
              <Field
                label={t.sales.lineDiscount}
                name={`discount_${slot}`}
                type="number"
                min="0"
                max="100"
                step="0.01"
              />
              <SelectField
                label={t.sales.lineTax}
                name={`tax_mode_${slot}`}
                options={[
                  { value: "rate", label: t.sales.lineTaxRate },
                  { value: "exempt", label: t.sales.lineTaxExempt },
                ]}
              />
              <div className="sm:col-span-2">
                <SelectField
                  label={t.sales.lineTaxRateChoice}
                  name={`tax_rate_${slot}`}
                  options={[
                    { value: "", label: t.sales.lineTaxNone },
                    ...rateOptions,
                  ]}
                />
              </div>
              <div className="sm:col-span-3">
                <Field label={t.sales.lineTaxReason} name={`tax_reason_${slot}`} />
              </div>
            </fieldset>
          ))}
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t.sales.dueOn} name="due_on" type="date" />
            <Field label={t.sales.validUntil} name="valid_until" type="date" />
          </div>
          <p className="text-muted-foreground text-xs">{t.sales.createHint}</p>
          <p className="text-muted-foreground text-xs">{t.sales.mentionsNotice}</p>
        </ActionForm>
      </CardContent>
    </Card>
  );
}
