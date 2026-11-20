import { Download } from "lucide-react";

import { InlineAction } from "@/components/forms/inline-action";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  decideQuoteAction,
  deleteDocumentAction,
  issueDocumentAction,
  postDocumentEntryAction,
  sendQuoteAction,
} from "@/lib/actions/sales";
import { formatMoney } from "@/lib/format";
import { salesDocPrefix, salesKindLabel, salesStatusTone, salesStatusLabel } from "./labels";
import type { Dictionary, SalesDocumentsPage } from "./types";

/** Liste des documents de vente (devis, factures, avoirs) : numérotation sans
 * trou visible (DEV/FAC/AV), statut, reste à régler, comptabilisation et
 * actions permises par rôle. */
export function SalesDocumentsTable({
  companyId,
  documents,
  partnerNames,
  t,
  manage,
  canPost,
}: {
  companyId: string;
  documents: SalesDocumentsPage;
  partnerNames: Map<string, string>;
  t: Dictionary;
  manage: boolean;
  canPost: boolean;
}) {
  return (
    <Table className="max-md:block">
      <TableHeader className="max-md:sr-only">
        <TableRow>
          <TableHead>{t.sales.partnerLabel}</TableHead>
          <TableHead>{t.sales.statusLabel}</TableHead>
          <TableHead className="text-right">{t.sales.totalLabel}</TableHead>
          <TableHead className="text-right">{t.sales.outstandingLabel}</TableHead>
          <TableHead>{t.sales.dueOn}</TableHead>
          <TableHead className="text-right">{t.common.actions}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody className="max-md:block">
        {documents.items.map((document) => (
          <TableRow key={document.id} className="max-md:grid max-md:grid-cols-2 max-md:gap-x-2 max-md:py-3">
            <TableCell className="min-w-0 whitespace-normal max-md:col-span-2">
              <span className="block font-medium wrap-anywhere">
                {partnerNames.get(document.partner_id) ?? `${t.sales.partnerReference} · ${document.partner_id}`}
              </span>
              <span className="text-muted-foreground text-xs">
                {salesKindLabel(t.sales, document.doc_kind)}
                {document.number != null && ` · ${salesDocPrefix(document.doc_kind)}-${document.number}`}
              </span>
              {document.issued_on && <span className="text-muted-foreground block text-xs">{t.sales.issuedLabel} {document.issued_on}</span>}
            </TableCell>
            <TableCell className="whitespace-normal max-md:col-span-2">
              <Badge variant={salesStatusTone(document.status)}>{salesStatusLabel(t.sales, document.status)}</Badge>
              {document.entry_id != null && <Badge variant="outline">{t.sales.postedBadge}</Badge>}
            </TableCell>
            <TableCell className="text-right whitespace-normal max-md:text-left">
              <span className="text-muted-foreground block text-xs md:hidden">{t.sales.totalLabel}</span>
              {formatMoney(document.total_ttc, document.currency)}
            </TableCell>
            <TableCell className="text-right whitespace-normal">
              <span className="text-muted-foreground block text-xs md:hidden">{t.sales.outstandingLabel}</span>
              {document.outstanding_ttc == null ? "—" : formatMoney(document.outstanding_ttc, document.currency)}
              {document.payment_status && <span className="text-muted-foreground block text-xs">
                {(t.sales.paymentStatus as Record<string, string>)[document.payment_status]}
              </span>}
            </TableCell>
            <TableCell className="max-md:col-span-2">
              <span className="text-muted-foreground mr-1 text-xs md:hidden">{t.sales.dueOn}</span>
              {document.due_on ?? "—"}
            </TableCell>
            <TableCell className="whitespace-normal max-md:col-span-2">
              <div className="flex flex-wrap items-center gap-2 md:justify-end">
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
                {canPost &&
                  document.status === "ISSUED" &&
                  document.entry_id == null && (
                    <InlineAction
                      action={postDocumentEntryAction.bind(null, companyId, document.id)}
                      confirm={t.sales.confirmPosting}
                      label={t.sales.postEntry}
                      pendingLabel={t.common.pending}
                    />
                  )}
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
