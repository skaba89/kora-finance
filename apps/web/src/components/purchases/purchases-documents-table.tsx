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
  cancelPurchaseInvoiceAction,
  deletePurchaseDocumentAction,
  issuePurchaseDocumentAction,
  postPurchaseDocumentEntryAction,
} from "@/lib/actions/purchases";
import { formatMoney } from "@/lib/format";
import { purchasesDisplayNumber, purchasesKindLabel, purchasesStatusTone, purchasesStatusLabel } from "./labels";
import type { Dictionary, PurchaseDocumentsPage } from "./types";

/** Liste des documents d'achat (factures et avoirs fournisseurs) : numéro
 * interne sans trou (FACH/AVF), statut, reste à payer et actions permises. */
export function PurchasesDocumentsTable({
  companyId,
  documents,
  t,
  manage,
  canPost,
}: {
  companyId: string;
  documents: PurchaseDocumentsPage;
  t: Dictionary;
  manage: boolean;
  canPost: boolean;
}) {
  return (
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
              {purchasesDisplayNumber(document.doc_kind, document.number)}
              {document.entry_id != null && (
                <span className="ml-2">
                  <Badge variant="outline">{t.purchases.postedBadge}</Badge>
                </span>
              )}
            </TableCell>
            <TableCell>{purchasesKindLabel(t.purchases, document.doc_kind)}</TableCell>
            <TableCell>
              <Badge variant={purchasesStatusTone(document.status)}>
                {purchasesStatusLabel(t.purchases, document.status)}
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
  );
}
