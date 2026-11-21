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
import { cn } from "@/lib/utils";
import type { TableDensity } from "@/lib/table-preferences";
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
  density,
  partnerNames,
}: {
  companyId: string;
  documents: PurchaseDocumentsPage;
  t: Dictionary;
  manage: boolean;
  canPost: boolean;
  density: TableDensity;
  partnerNames: Map<string, string>;
}) {
  return (
    <Table aria-label={t.purchases.listTitle} containerProps={{ role: "region", "aria-label": t.purchases.listTitle, tabIndex: 0, className: "rounded-xl border bg-card md:max-h-[65vh] md:overflow-auto" }} className={cn("max-md:block [&_td]:px-3", density === "compact" ? "[&_td]:py-1.5" : "[&_td]:py-3")}>
      <TableHeader className="max-md:sr-only md:sticky md:top-0 md:z-10 [&_th]:bg-muted">
        <TableRow>
          <TableHead>{t.purchases.numberLabel}</TableHead>
          <TableHead>{t.purchases.kindLabel}</TableHead>
          <TableHead>{t.purchases.statusLabel}</TableHead>
          <TableHead className="text-right">{t.purchases.totalLabel}</TableHead>
          <TableHead className="text-right">{t.purchases.outstandingLabel}</TableHead>
          <TableHead>{t.purchases.issuedLabel}</TableHead>
          <TableHead>{t.purchases.referenceLabel}</TableHead>
          <TableHead className="text-right">{t.common.actions}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody className="max-md:block">
        {documents.items.map((document) => (
          <TableRow key={document.id} className="max-md:grid max-md:grid-cols-2 max-md:gap-x-2 max-md:py-3">
            <TableCell className="min-w-0 whitespace-normal max-md:col-span-2">
              <span className="block font-medium wrap-anywhere">{partnerNames.get(document.partner_id) ?? `${t.purchases.partnerLabel} · ${document.partner_id}`}</span>
              <span className="font-mono text-xs">
              {purchasesDisplayNumber(document.doc_kind, document.number)}
              </span>
              {document.entry_id != null && (
                <span className="ml-2">
                  <Badge variant="outline">{t.purchases.postedBadge}</Badge>
                </span>
              )}
            </TableCell>
            <TableCell className="whitespace-normal">{purchasesKindLabel(t.purchases, document.doc_kind)}</TableCell>
            <TableCell className="whitespace-normal">
              <Badge variant={purchasesStatusTone(document.status)}>
                {purchasesStatusLabel(t.purchases, document.status)}
              </Badge>
            </TableCell>
            <TableCell className="text-right whitespace-normal font-medium tabular-nums max-md:text-left"><span className="text-muted-foreground block text-xs md:hidden">{t.purchases.totalLabel}</span>{formatMoney(document.total_ttc, document.currency)}</TableCell>
            <TableCell className="text-right whitespace-normal tabular-nums">
              <span className="text-muted-foreground block text-xs md:hidden">{t.purchases.outstandingLabel}</span>
              {document.payment_status != null ? (
                <Badge
                  className="max-w-full whitespace-normal wrap-anywhere"
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
            <TableCell><span className="text-muted-foreground block text-xs md:hidden">{t.purchases.issuedLabel}</span>{document.issued_on ?? "—"}</TableCell>
            <TableCell className="font-mono whitespace-normal wrap-anywhere text-xs"><span className="text-muted-foreground block font-sans text-xs md:hidden">{t.purchases.referenceLabel}</span>{document.reference ?? "—"}</TableCell>
            <TableCell className="whitespace-normal max-md:col-span-2"><div className="flex flex-wrap items-center gap-2 md:justify-end">
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
            </div></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
