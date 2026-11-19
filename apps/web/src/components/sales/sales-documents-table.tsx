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
  t,
  manage,
  canPost,
}: {
  companyId: string;
  documents: SalesDocumentsPage;
  t: Dictionary;
  manage: boolean;
  canPost: boolean;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t.sales.numberLabel}</TableHead>
          <TableHead>{t.sales.kindLabel}</TableHead>
          <TableHead>{t.sales.statusLabel}</TableHead>
          <TableHead>{t.sales.totalLabel}</TableHead>
          <TableHead>{t.sales.outstandingLabel}</TableHead>
          <TableHead>{t.sales.issuedLabel}</TableHead>
          <TableHead>{t.sales.postedColumn}</TableHead>
          <TableHead className="text-right">{t.common.actions}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {documents.items.map((document) => (
          <TableRow key={document.id}>
            <TableCell className="font-mono text-xs">
              {document.number == null
                ? "—"
                : `${salesDocPrefix(document.doc_kind)}-${document.number}`}
            </TableCell>
            <TableCell>{salesKindLabel(t.sales, document.doc_kind)}</TableCell>
            <TableCell>
              <Badge variant={salesStatusTone(document.status)}>
                {salesStatusLabel(t.sales, document.status)}
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
                  {(t.sales.paymentStatus as Record<string, string>)[document.payment_status]}
                  {" "}
                  {formatMoney(document.outstanding_ttc ?? 0, document.currency)}
                </Badge>
              ) : (
                "—"
              )}
            </TableCell>
            <TableCell>{document.issued_on ?? "—"}</TableCell>
            <TableCell>
              {document.entry_id != null ? (
                <Badge variant="outline">{t.sales.postedBadge}</Badge>
              ) : (
                "—"
              )}
            </TableCell>
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
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
