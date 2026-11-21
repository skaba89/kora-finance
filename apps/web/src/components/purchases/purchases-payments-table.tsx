import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/data-table";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  allocatePurchasePaymentAction,
  deletePurchasePaymentAction,
  deletePurchaseRefundAction,
  postPurchaseAllocationEntryAction,
  postPurchasePaymentEntryAction,
  postPurchaseRefundEntryAction,
  refundPurchasePaymentAction,
} from "@/lib/actions/purchases";
import { formatMoney } from "@/lib/format";
import type { Dictionary, PurchaseDocumentsPage, PurchasePaymentsPage } from "./types";

/** Décaissements fournisseurs : affectations aux factures, remboursements et
 * actes comptables (décaissement, transfert d'affectation). */
export function PurchasesPaymentsTable({
  companyId,
  payments,
  documents,
  t,
  manage,
  canPost,
}: {
  companyId: string;
  payments: PurchasePaymentsPage;
  documents: PurchaseDocumentsPage;
  t: Dictionary;
  manage: boolean;
  canPost: boolean;
}) {
  return (
    <DataTable label={t.purchases.paymentsTitle}>
      <TableHeader>
        <TableRow>
          <TableHead>{t.purchases.paymentDate}</TableHead>
          <TableHead>{t.purchases.paymentMethod}</TableHead>
          <TableHead className="text-right">{t.purchases.totalLabel}</TableHead>
          <TableHead className="text-right">{t.purchases.unallocatedBadge}</TableHead>
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
            <TableCell className="text-right font-medium tabular-nums">{formatMoney(payment.amount, payment.currency)}</TableCell>
            <TableCell className="text-right">
              {payment.unallocated > 0 ? (
                <Badge variant="secondary">
                  {t.purchases.unallocatedBadge}{" "}
                  {formatMoney(payment.unallocated, payment.currency)}
                </Badge>
              ) : (
                "—"
              )}
            </TableCell>
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
              {canPost &&
                payment.entry_id != null &&
                payment.allocations.some((allocation) => allocation.entry_id == null) && (
                  <InlineAction
                    action={postPurchaseAllocationEntryAction.bind(null, companyId, payment.id)}
                    label={t.purchases.allocationTransfer}
                    pendingLabel={t.common.pending}
                  />
                )}
              {manage && payment.unallocated > 0 && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs underline">
                    {t.purchases.allocateAction}
                  </summary>
                  <ActionForm
                    action={allocatePurchasePaymentAction.bind(null, companyId, payment.id)}
                    className="mt-2 space-y-2"
                    submitLabel={t.purchases.allocateAction}
                    pendingLabel={t.common.pending}
                  >
                    <SelectField
                      label={t.purchases.paymentDoc}
                      name="document_id"
                      required
                      options={documents.items
                        .filter(
                          (document) =>
                            document.doc_kind === "supplier_invoice" &&
                            document.status === "ISSUED" &&
                            document.partner_id === payment.partner_id,
                        )
                        .map((document) => ({
                          value: document.id,
                          label: `FACH-${document.number} — ${t.purchases.outstandingLabel} ${formatMoney(document.outstanding_ttc ?? 0, document.currency)}`,
                        }))}
                    />
                    <Field
                      label={t.purchases.allocateTarget}
                      name="target"
                      type="number"
                      min="1"
                      step="1"
                      required
                    />
                    <p className="text-muted-foreground text-xs">{t.purchases.allocateHint}</p>
                  </ActionForm>
                </details>
              )}
              {manage && payment.unallocated > 0 && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs underline">
                    {t.purchases.refundAction}
                  </summary>
                  <ActionForm
                    action={refundPurchasePaymentAction.bind(null, companyId, payment.id)}
                    className="mt-2 space-y-2"
                    submitLabel={t.purchases.refundAction}
                    pendingLabel={t.common.pending}
                  >
                    <Field
                      label={t.purchases.refundAmount}
                      name="amount"
                      type="number"
                      min="1"
                      step="1"
                      required
                    />
                    <Field
                      label={t.purchases.paymentDate}
                      name="refunded_on"
                      type="date"
                      required
                    />
                    <p className="text-muted-foreground text-xs">{t.purchases.refundTitle}</p>
                  </ActionForm>
                </details>
              )}
              {manage &&
                payment.refunds.map((refund) => (
                  <div key={refund.id} className="mt-1 text-xs">
                    <span className="text-muted-foreground">{t.purchases.refundsTitle} :</span>{" "}
                    {formatMoney(refund.amount, refund.currency)} — {refund.refunded_on}
                    {canPost && refund.entry_id == null && (
                      <InlineAction
                        action={postPurchaseRefundEntryAction.bind(null, companyId, refund.id)}
                        label={t.purchases.refundPost}
                        pendingLabel={t.common.pending}
                      />
                    )}
                    {manage && refund.entry_id == null && (
                      <InlineAction
                        action={deletePurchaseRefundAction.bind(null, companyId, refund.id)}
                        label={t.common.remove}
                        pendingLabel={t.common.pending}
                      />
                    )}
                  </div>
                ))}
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
    </DataTable>
  );
}
