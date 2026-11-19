import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  allocatePaymentAction,
  deletePaymentAction,
  deleteRefundAction,
  postAllocationEntryAction,
  postPaymentEntryAction,
  postRefundEntryAction,
  refundPaymentAction,
} from "@/lib/actions/sales";
import { formatMoney } from "@/lib/format";
import type { Dictionary, SalesDocumentsPage, SalesPaymentsPage } from "./types";

/** Règlements clients : affectations aux factures, remboursements et actes
 * comptables (règlement, transfert d'affectation). */
export function SalesPaymentsTable({
  companyId,
  payments,
  documents,
  t,
  manage,
  canPost,
}: {
  companyId: string;
  payments: SalesPaymentsPage;
  documents: SalesDocumentsPage;
  t: Dictionary;
  manage: boolean;
  canPost: boolean;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t.sales.paymentDate}</TableHead>
          <TableHead>{t.sales.paymentMethod}</TableHead>
          <TableHead>{t.sales.totalLabel}</TableHead>
          <TableHead>{t.sales.unallocatedBadge}</TableHead>
          <TableHead>{t.sales.paymentsAllocations}</TableHead>
          <TableHead>{t.sales.paymentReference}</TableHead>
          <TableHead>{t.sales.postedColumn}</TableHead>
          <TableHead className="text-right">{t.common.actions}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {payments.items.map((payment) => (
          <TableRow key={payment.id}>
            <TableCell>{payment.paid_on}</TableCell>
            <TableCell>
              {(t.sales.methods as Record<string, string>)[payment.method] ??
                payment.method}
            </TableCell>
            <TableCell>{formatMoney(payment.amount, payment.currency)}</TableCell>
            <TableCell>
              {payment.unallocated > 0 ? (
                <Badge variant="secondary">
                  {t.sales.unallocatedBadge} {formatMoney(payment.unallocated, payment.currency)}
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
                  return target?.number != null ? `FAC-${target.number}` : "…";
                })
                .join(", ")}
            </TableCell>
            <TableCell>{payment.reference ?? "—"}</TableCell>
            <TableCell>
              {payment.entry_id != null ? (
                <Badge variant="outline">{t.sales.paymentPostedBadge}</Badge>
              ) : (
                "—"
              )}
            </TableCell>
            <TableCell className="text-right">
              {canPost && payment.entry_id == null && (
                <InlineAction
                  action={postPaymentEntryAction.bind(null, companyId, payment.id)}
                  confirm={t.sales.paymentConfirmPosting}
                  label={t.sales.paymentPost}
                  pendingLabel={t.common.pending}
                />
              )}
              {canPost &&
                payment.entry_id != null &&
                payment.allocations.some((allocation) => allocation.entry_id == null) && (
                  <InlineAction
                    action={postAllocationEntryAction.bind(null, companyId, payment.id)}
                    label={t.sales.allocationTransfer}
                    pendingLabel={t.common.pending}
                  />
                )}
              {manage && payment.unallocated > 0 && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs underline">
                    {t.sales.allocateAction}
                  </summary>
                  <ActionForm
                    action={allocatePaymentAction.bind(null, companyId, payment.id)}
                    className="mt-2 space-y-2"
                    submitLabel={t.sales.allocateAction}
                    pendingLabel={t.common.pending}
                  >
                    <SelectField
                      label={t.sales.paymentDoc}
                      name="document_id"
                      required
                      options={documents.items
                        .filter(
                          (document) =>
                            document.doc_kind === "invoice" &&
                            document.status === "ISSUED" &&
                            document.partner_id === payment.partner_id,
                        )
                        .map((document) => ({
                          value: document.id,
                          label: `FAC-${document.number} — ${t.sales.outstandingLabel} ${formatMoney(document.outstanding_ttc ?? 0, document.currency)}`,
                        }))}
                    />
                    <Field
                      label={t.sales.allocateTarget}
                      name="target"
                      type="number"
                      min="1"
                      step="1"
                      required
                    />
                    <p className="text-muted-foreground text-xs">{t.sales.allocateHint}</p>
                  </ActionForm>
                </details>
              )}
              {manage && payment.unallocated > 0 && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs underline">
                    {t.sales.refundAction}
                  </summary>
                  <ActionForm
                    action={refundPaymentAction.bind(null, companyId, payment.id)}
                    className="mt-2 space-y-2"
                    submitLabel={t.sales.refundAction}
                    pendingLabel={t.common.pending}
                  >
                    <Field
                      label={t.sales.refundAmount}
                      name="amount"
                      type="number"
                      min="1"
                      step="1"
                      required
                    />
                    <Field label={t.sales.paymentDate} name="refunded_on" type="date" required />
                    <p className="text-muted-foreground text-xs">{t.sales.refundTitle}</p>
                  </ActionForm>
                </details>
              )}
              {manage &&
                payment.refunds.map((refund) => (
                  <div key={refund.id} className="mt-1 text-xs">
                    <span className="text-muted-foreground">{t.sales.refundsTitle} :</span>{" "}
                    {formatMoney(refund.amount, refund.currency)} — {refund.refunded_on}
                    {canPost && refund.entry_id == null && (
                      <InlineAction
                        action={postRefundEntryAction.bind(null, companyId, refund.id)}
                        label={t.sales.refundPost}
                        pendingLabel={t.common.pending}
                      />
                    )}
                    {manage && refund.entry_id == null && (
                      <InlineAction
                        action={deleteRefundAction.bind(null, companyId, refund.id)}
                        label={t.common.remove}
                        pendingLabel={t.common.pending}
                      />
                    )}
                  </div>
                ))}
              {manage && (
                <InlineAction
                  action={deletePaymentAction.bind(null, companyId, payment.id)}
                  confirm={t.sales.confirmPaymentDelete}
                  label={t.common.remove}
                  pendingLabel={t.common.pending}
                />
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
