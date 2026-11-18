import type { Metadata } from "next";

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
  cancelPurchaseInvoiceAction,
  createPurchaseDocumentAction,
  createPurchasePaymentAction,
  deletePurchaseDocumentAction,
  deletePurchasePaymentAction,
  issuePurchaseDocumentAction,
  postPurchaseDocumentEntryAction,
  postPurchasePaymentEntryAction,
} from "@/lib/actions/purchases";
import {
  can,
  getCompany,
  getPartners,
  getPayablesAging,
  getPurchaseDocuments,
  getPurchasePayments,
  getTaxRates,
} from "@/lib/dal";
import { formatMoney } from "@/lib/format";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.purchases.title };
}

const STATUSES = ["DRAFT", "ISSUED", "CANCELLED"] as const;

/** Page achats (4F) : factures et avoirs fournisseurs à numérotation interne
 * sans trou (FACH/AVF), décaissements lettrés et échéancier fournisseurs.
 * Enregistrer un document n'écrit rien en comptabilité ; la comptabilisation
 * est un acte explicite du comptable : elle crée l'écriture validée du journal
 * des achats et la lie au document ou au décaissement. */
export default async function PurchasesPage({
  params,
  searchParams,
}: {
  params: Promise<{ lang: string; companyId: string }>;
  searchParams: Promise<{ kind?: string; statut?: string }>;
}) {
  const [{ companyId }, { kind, statut }] = await Promise.all([params, searchParams]);
  const kindParam =
    kind === "supplier_invoice" || kind === "supplier_credit_note" ? kind : undefined;
  const statusParam = STATUSES.find((value) => value === statut);
  const [{ t }, company, documents, partners, taxRates, payments, aging] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getPurchaseDocuments(companyId, {
      kind: kindParam,
      status: statusParam,
      limit: 50,
      offset: 0,
    }),
    getPartners(companyId, { limit: 200, offset: 0 }),
    getTaxRates(companyId),
    getPurchasePayments(companyId, { limit: 50, offset: 0 }),
    getPayablesAging(companyId),
  ]);

  const manage = can(company, "purchases:manage");
  const canPost = can(company, "entries:post");
  const today = new Date().toISOString().slice(0, 10);
  const rateOptions = taxRates
    .filter((rate) => {
      const validTo = rate.valid_to ?? null;
      return rate.valid_from <= today && (validTo == null || validTo >= today);
    })
    .map((rate) => ({ value: rate.id, label: `${rate.label} (${rate.rate_basis_points / 100} %)` }));

  const kindLabel = (value: string) =>
    value === "supplier_credit_note"
      ? t.purchases.kinds.supplierCreditNote
      : t.purchases.kinds.supplierInvoice;
  const statusLabel = (value: string) =>
    (t.purchases.statuses as Record<string, string>)[value] ?? value;
  const statusTone = (value: string) =>
    value === "CANCELLED" ? "destructive" : value === "DRAFT" ? "secondary" : "default";
  const displayNumber = (kind: string, number: number | null) =>
    number == null ? "—" : `${kind === "supplier_credit_note" ? "AVF" : "FACH"}-${number}`;

  return (
    <>
      <PageHeader title={t.purchases.title} subtitle={t.purchases.subtitle} />
      <p className="text-muted-foreground -mt-4 mb-4 text-xs">{t.purchases.noPostingNotice}</p>

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
            {STATUSES.map((status: string) => (
              <option key={status} value={status}>
                {statusLabel(status)}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" variant="outline" size="sm">
          {t.purchases.apply}
        </Button>
      </form>

      <Card>
        <CardHeader>
          <CardTitle>{t.purchases.listTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          {documents.items.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t.purchases.empty}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.purchases.numberLabel}</TableHead>
                  <TableHead>{t.purchases.kindLabel}</TableHead>
                  <TableHead>{t.purchases.statusLabel}</TableHead>
                  <TableHead>{t.purchases.totalLabel}</TableHead>
                  <TableHead>{t.purchases.outstandingLabel}</TableHead>
                  <TableHead>{t.purchases.issuedLabel}</TableHead>
                  <TableHead>{t.purchases.referenceLabel}</TableHead>
                  <TableHead className="text-right">{t.common.actions}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.items.map((document) => (
                  <TableRow key={document.id}>
                    <TableCell className="font-mono text-xs">
                      {displayNumber(document.doc_kind, document.number)}
                      {document.entry_id != null && (
                        <span className="ml-2">
                          <Badge variant="outline">{t.purchases.postedBadge}</Badge>
                        </span>
                      )}
                    </TableCell>
                    <TableCell>{kindLabel(document.doc_kind)}</TableCell>
                    <TableCell>
                      <Badge variant={statusTone(document.status)}>
                        {statusLabel(document.status)}
                      </Badge>
                    </TableCell>
                    <TableCell>{formatMoney(document.total_ttc, document.currency)}</TableCell>
                    <TableCell>
                      {document.payment_status != null ? (
                        <Badge
                          variant={
                            document.payment_status === "paid"
                              ? "outline"
                              : document.payment_status === "partial"
                                ? "secondary"
                                : "default"
                          }
                        >
                          {(t.purchases.paymentStatus as Record<string, string>)[
                            document.payment_status
                          ]}{" "}
                          {formatMoney(document.outstanding_ttc ?? 0, document.currency)}
                        </Badge>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>{document.issued_on ?? "—"}</TableCell>
                    <TableCell className="font-mono text-xs">{document.reference ?? "—"}</TableCell>
                    <TableCell className="space-x-2 text-right">
                      {manage && document.status === "DRAFT" && (
                        <InlineAction
                          action={issuePurchaseDocumentAction.bind(null, companyId, document.id)}
                          confirm={t.purchases.confirmNumbering}
                          label={t.purchases.issue}
                          pendingLabel={t.common.pending}
                        />
                      )}
                      {manage && document.status === "DRAFT" && (
                        <InlineAction
                          action={deletePurchaseDocumentAction.bind(null, companyId, document.id)}
                          confirm={t.purchases.confirmGeneric}
                          label={t.common.remove}
                          pendingLabel={t.common.pending}
                        />
                      )}
                      {manage &&
                        document.status === "ISSUED" &&
                        document.doc_kind === "supplier_invoice" && (
                          <InlineAction
                            action={cancelPurchaseInvoiceAction.bind(null, companyId, document.id)}
                            confirm={t.purchases.confirmCancel}
                            label={t.purchases.cancel}
                            pendingLabel={t.common.pending}
                          />
                        )}
                      {canPost && document.status === "ISSUED" && document.entry_id == null && (
                        <InlineAction
                          action={postPurchaseDocumentEntryAction.bind(null, companyId, document.id)}
                          confirm={t.purchases.confirmPost}
                          label={t.purchases.postButton}
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
            <CardTitle>{t.purchases.paymentFormTitle}</CardTitle>
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
                <SelectField
                  label={t.purchases.paymentMethod}
                  name="method"
                  options={(
                    [
                      "BANK_TRANSFER",
                      "MOBILE_MONEY",
                      "CASH",
                      "CHECK",
                      "CARD",
                      "OTHER",
                    ] as const
                  ).map((method) => ({
                    value: method,
                    label: (t.purchases.methods as Record<string, string>)[method] ?? method,
                  }))}
                />
                <Field label={t.purchases.paymentReference} name="reference" />
              </div>
              <p className="text-muted-foreground text-xs">{t.purchases.paymentHint}</p>
            </ActionForm>
          </CardContent>
        </Card>
      )}

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>{t.purchases.paymentsTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          {payments.items.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t.purchases.paymentsEmpty}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.purchases.paymentDate}</TableHead>
                  <TableHead>{t.purchases.paymentMethod}</TableHead>
                  <TableHead>{t.purchases.totalLabel}</TableHead>
                  <TableHead>{t.purchases.paymentsAllocations}</TableHead>
                  <TableHead>{t.purchases.paymentReference}</TableHead>
                  <TableHead className="text-right">{t.common.actions}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {payments.items.map((payment) => (
                  <TableRow key={payment.id}>
                    <TableCell>{payment.paid_on}</TableCell>
                    <TableCell>
                      {(t.purchases.methods as Record<string, string>)[payment.method] ??
                        payment.method}
                    </TableCell>
                    <TableCell>{formatMoney(payment.amount, payment.currency)}</TableCell>
                    <TableCell>
                      {payment.allocations
                        .map((allocation) => {
                          const target = documents.items.find(
                            (document) => document.id === allocation.document_id,
                          );
                          return target?.number != null ? `FACH-${target.number}` : "…";
                        })
                        .join(", ")}
                    </TableCell>
                    <TableCell>{payment.reference ?? "—"}</TableCell>
                    <TableCell className="space-x-2 text-right">
                      {canPost && payment.entry_id == null && (
                        <InlineAction
                          action={postPurchasePaymentEntryAction.bind(null, companyId, payment.id)}
                          confirm={t.purchases.confirmPost}
                          label={t.purchases.postButton}
                          pendingLabel={t.common.pending}
                        />
                      )}
                      {manage && (
                        <InlineAction
                          action={deletePurchasePaymentAction.bind(null, companyId, payment.id)}
                          confirm={t.purchases.confirmPaymentDelete}
                          label={t.common.remove}
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

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>{t.purchases.agingTitle}</CardTitle>
          <p className="text-muted-foreground text-sm">
            {t.purchases.agingAsOf} {aging.as_of} —{" "}
            {formatMoney(aging.grand_total_ttc, company.company.currency)}
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
                {(["not_due", "d1_30", "d31_60", "d61_90", "d90_plus"] as const).map((bucket) => {
                  const line = aging.buckets[bucket];
                  if (!line || line.count === 0) return null;
                  return (
                    <TableRow key={bucket}>
                      <TableCell>
                        {(t.purchases.agingBucket as Record<string, string>)[bucket]}
                      </TableCell>
                      <TableCell>{line.count}</TableCell>
                      <TableCell className="text-right">
                        {formatMoney(line.total_ttc, company.company.currency)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {manage && (
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
      )}
    </>
  );
}
