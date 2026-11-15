import type { Metadata } from "next";

import { Download } from "lucide-react";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  cancelInvoiceAction,
  convertQuoteAction,
  createDocumentAction,
  decideQuoteAction,
  deleteDocumentAction,
  issueDocumentAction,
  sendQuoteAction,
} from "@/lib/actions/sales";
import { can, getCompany, getPartners, getSalesDocuments, getTaxRates } from "@/lib/dal";
import { formatMoney } from "@/lib/format";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.sales.title };
}

const KINDS = ["quote", "invoice", "credit_note"] as const;
const STATUSES = ["DRAFT", "SENT", "ACCEPTED", "REJECTED", "ISSUED", "CANCELLED"] as const;

/** Page ventes (4B) : devis, factures et avoirs à numérotation sans trou. Créer un
 * brouillon n'écrit rien en comptabilité ; le numéro est attribué à l'émission
 * (facture/avoir) ou à l'envoi (devis) et n'est jamais réutilisé. */
export default async function SalesPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/ventes">) {
  const { companyId } = await params;
  const { kind, statut } = await searchParams;
  const kindParam =
    typeof kind === "string" && KINDS.includes(kind as (typeof KINDS)[number])
      ? (kind as (typeof KINDS)[number])
      : undefined;
  const statusParam =
    typeof statut === "string" && STATUSES.includes(statut as (typeof STATUSES)[number])
      ? (statut as (typeof STATUSES)[number])
      : undefined;
  const [{ t }, company, documents, partners, taxRates] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getSalesDocuments(companyId, { kind: kindParam, status: statusParam, limit: 100, offset: 0 }),
    getPartners(companyId, { active: true, limit: 200, offset: 0 }),
    getTaxRates(companyId),
  ]);
  const manage = can(company, "sales:manage");
  const activeRates = taxRates.filter((rate) => {
    const today = new Date().toISOString().slice(0, 10);
    return rate.valid_from <= today && (!rate.valid_to || rate.valid_to >= today);
  });
  const rateOptions = activeRates.map((rate) => ({
    value: rate.id,
    label: `${rate.label} (${rate.rate_basis_points / 100} %)`,
  }));

  const kindLabel = (value: string) =>
    value === "quote"
      ? t.sales.kinds.quote
      : value === "credit_note"
        ? t.sales.kinds.creditNote
        : t.sales.kinds.invoice;
  const statusLabel = (value: string) =>
    (t.sales.statuses as Record<string, string>)[value] ?? value;
  const statusTone = (value: string) =>
    value === "ISSUED" || value === "ACCEPTED"
      ? "default"
      : value === "CANCELLED" || value === "REJECTED"
        ? "destructive"
        : value === "DRAFT"
          ? "secondary"
          : "outline";

  return (
    <>
      <PageHeader title={t.sales.title} subtitle={t.sales.subtitle} />
      <p className="text-muted-foreground -mt-4 mb-4 text-xs">{t.sales.noPostingNotice}</p>

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
            {STATUSES.map((status: string) => (
              <option key={status} value={status}>
                {statusLabel(status)}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" variant="outline" size="sm">
          {t.sales.apply}
        </Button>
      </form>

      <Card>
        <CardHeader>
          <CardTitle>{t.sales.listTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          {documents.items.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t.sales.empty}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.sales.numberLabel}</TableHead>
                  <TableHead>{t.sales.kindLabel}</TableHead>
                  <TableHead>{t.sales.statusLabel}</TableHead>
                  <TableHead>{t.sales.totalLabel}</TableHead>
                  <TableHead>{t.sales.issuedLabel}</TableHead>
                  <TableHead className="text-right">{t.common.actions}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.items.map((document) => (
                  <TableRow key={document.id}>
                    <TableCell className="font-mono text-xs">
                      {document.number == null
                        ? "—"
                        : `${document.doc_kind === "quote" ? "DEV" : document.doc_kind === "credit_note" ? "AV" : "FAC"}-${document.number}`}
                    </TableCell>
                    <TableCell>{kindLabel(document.doc_kind)}</TableCell>
                    <TableCell>
                      <Badge variant={statusTone(document.status)}>
                        {statusLabel(document.status)}
                      </Badge>
                    </TableCell>
                    <TableCell>{formatMoney(document.total_ttc, document.currency)}</TableCell>
                    <TableCell>{document.issued_on ?? "—"}</TableCell>
                    <TableCell className="space-x-2 text-right">
                      {document.number != null && (
                        <Button asChild variant="outline" size="sm">
                          <a
                            href={`/dossiers/${companyId}/ventes/${document.id}/pdf`}
                            download
                          >
                            <Download aria-hidden className="size-4" />
                            {t.sales.pdf}
                          </a>
                        </Button>
                      )}
                      {manage && document.status === "DRAFT" && document.doc_kind === "quote" && (
                        <InlineAction
                          action={sendQuoteAction.bind(null, companyId, document.id)}
                          confirm={t.sales.confirmNumbering}
                          label={t.sales.send}
                          pendingLabel={t.common.pending}
                        />
                      )}
                      {manage && document.status === "DRAFT" && document.doc_kind !== "quote" && (
                        <InlineAction
                          action={issueDocumentAction.bind(null, companyId, document.id)}
                          confirm={t.sales.confirmNumbering}
                          label={t.sales.issue}
                          pendingLabel={t.common.pending}
                        />
                      )}
                      {manage && document.status === "SENT" && (
                        <>
                          <InlineAction
                            action={decideQuoteAction.bind(null, companyId, document.id, true)}
                            label={t.sales.accept}
                            pendingLabel={t.common.pending}
                          />
                          <InlineAction
                            action={decideQuoteAction.bind(null, companyId, document.id, false)}
                            confirm={t.sales.confirmDecision}
                            label={t.sales.reject}
                            pendingLabel={t.common.pending}
                          />
                        </>
                      )}
                      {manage && document.status === "ACCEPTED" && (
                        <InlineAction
                          action={convertQuoteAction.bind(null, companyId, document.id)}
                          label={t.sales.convert}
                          pendingLabel={t.common.pending}
                        />
                      )}
                      {manage && document.status === "DRAFT" && (
                        <InlineAction
                          action={deleteDocumentAction.bind(null, companyId, document.id)}
                          confirm={t.sales.confirmGeneric}
                          label={t.common.remove}
                          pendingLabel={t.common.pending}
                        />
                      )}
                      {manage && document.status === "ISSUED" && document.doc_kind === "invoice" && (
                        <InlineAction
                          action={cancelInvoiceAction.bind(null, companyId, document.id)}
                          confirm={t.sales.confirmCancel}
                          label={t.sales.cancel}
                          pendingLabel={t.common.pending}
                        />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {manage && (
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
      )}
    </>
  );
}
