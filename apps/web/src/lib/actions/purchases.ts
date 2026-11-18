"use server";

import { refresh } from "next/cache";

import { api } from "@/lib/api/server";
import { actionDictionary, failure, field } from "@/lib/actions/support";
import type { ActionState } from "./state";

type LineBody = {
  label: string;
  quantity: number;
  unit_price_ht: number;
  discount_bp: number;
  tax_rate_id?: string;
  tax_exempt_reason?: string;
};

/** Lit jusqu'à trois lignes du formulaire de création (quantités en unités,
 * converties en millièmes pour l'API : jamais de flottant). */
function parseLines(formData: FormData): LineBody[] {
  const lines: LineBody[] = [];
  for (let slot = 1; slot <= 3; slot += 1) {
    const label = field(formData, `label_${slot}`);
    if (!label) continue;
    const units = Number(field(formData, `qty_${slot}`) || "0");
    const price = Number(field(formData, `price_${slot}`) || "0");
    if (!Number.isFinite(units) || units <= 0 || !Number.isFinite(price) || price < 0) continue;
    const discountPercent = Number(field(formData, `discount_${slot}`) || "0");
    const line: LineBody = {
      label,
      quantity: Math.round(units * 1000),
      unit_price_ht: Math.round(price),
      discount_bp: Math.max(0, Math.min(10000, Math.round(discountPercent * 100))),
    };
    const mode = field(formData, `tax_mode_${slot}`);
    if (mode === "rate") {
      const rate = field(formData, `tax_rate_${slot}`);
      if (rate) line.tax_rate_id = rate;
      else line.tax_exempt_reason = "Taux manquant : à compléter";
    } else {
      line.tax_exempt_reason = field(formData, `tax_reason_${slot}`) || "Exonéré";
    }
    lines.push(line);
  }
  return lines;
}

/** Crée un brouillon d'achat (facture ou avoir fournisseur) : jamais numéroté à
 * la création. Le numéro imprimé par le fournisseur est conservé dans
 * `reference` (pièce justificative du classeur d'achats). */
export async function createPurchaseDocumentAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const kind = field(formData, "doc_kind");
  if (kind !== "supplier_invoice" && kind !== "supplier_credit_note") {
    return { status: "error", message: "Type de document inconnu." };
  }
  const lines = parseLines(formData);
  if (lines.length === 0) {
    const t = await actionDictionary();
    return { status: "error", message: t.purchases.lineRequired };
  }
  const partnerId = field(formData, "partner_id");
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/purchases",
    {
      params: { path: { company_id: companyId } },
      body: {
        doc_kind: kind,
        partner_id: partnerId,
        lines,
        due_on: field(formData, "due_on") || undefined,
        reference: field(formData, "reference") || undefined,
        notes: field(formData, "notes") || undefined,
        origin_document_id: field(formData, "origin_document_id") || undefined,
        reverses_document_id: field(formData, "reverses_document_id") || undefined,
      },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

/** Émission définitive d'une facture ou d'un avoir fournisseur : numérotation
 * sans trou (FACH/AVF), mentions du fournisseur figées. */
export async function issuePurchaseDocumentAction(
  companyId: string,
  documentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/purchases/{document_id}/issue",
    { params: { path: { company_id: companyId, document_id: documentId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.purchases.issued };
}

/** Annulation d'une facture fournisseur émise (numéro conservé, jamais
 * réutilisé). Refusée si elle porte des décaissements ou une écriture vivante. */
export async function cancelPurchaseInvoiceAction(
  companyId: string,
  documentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/purchases/{document_id}/cancel",
    { params: { path: { company_id: companyId, document_id: documentId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.purchases.cancelled };
}

/** Suppression d'un brouillon : aucun numéro n'a été consommé (pas de trou). */
export async function deletePurchaseDocumentAction(
  companyId: string,
  documentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).DELETE(
    "/api/v1/companies/{company_id}/purchases/{document_id}",
    { params: { path: { company_id: companyId, document_id: documentId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.purchases.deleted };
}

/** Enregistre un décaissement fournisseur sur une facture émise (lettrage
 * commercial des achats). Le montant est contrôlé côté serveur : jamais au-delà
 * du solde restant dû. */
export async function createPurchasePaymentAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const documentId = field(formData, "document_id");
  const amount = Number(field(formData, "amount") || "0");
  const method = field(formData, "method") || "BANK_TRANSFER";
  if (!documentId || !Number.isFinite(amount) || amount <= 0) {
    const t = await actionDictionary();
    return { status: "error", message: t.purchases.paymentAmountRequired };
  }
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/purchase-payments",
    {
      params: { path: { company_id: companyId } },
      body: {
        paid_on: field(formData, "paid_on") || new Date().toISOString().slice(0, 10),
        method: method as
          | "CASH"
          | "BANK_TRANSFER"
          | "MOBILE_MONEY"
          | "CHECK"
          | "CARD"
          | "OTHER",
        allocations: [{ document_id: documentId, amount: Math.round(amount) }],
        reference: field(formData, "reference") || undefined,
        notes: field(formData, "notes") || undefined,
      },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.purchases.paymentRecorded };
}

/** Supprime un décaissement (correction de saisie) : les soldes sont libérés.
 * Refusé tant que le règlement est comptabilisé (contre-passation d'abord). */
export async function deletePurchasePaymentAction(
  companyId: string,
  paymentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).DELETE(
    "/api/v1/companies/{company_id}/purchase-payments/{payment_id}",
    { params: { path: { company_id: companyId, payment_id: paymentId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.purchases.paymentDeleted };
}

/** Comptabilise une facture ou un avoir fournisseur émis : acte explicite du
 * comptable — crée et valide l'écriture du journal des achats, liée au
 * document. Refusé si le document est déjà comptabilisé (409) ; une erreur se
 * corrige par contre-passation au grand livre. */
export async function postPurchaseDocumentEntryAction(
  companyId: string,
  documentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/purchases/{document_id}/entry",
    { params: { path: { company_id: companyId, document_id: documentId } }, body: {} },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.purchases.posted };
}

/** Comptabilise un décaissement : crée et valide l'écriture du journal de
 * trésorerie (caisse, banque ou Mobile Money selon le mode), liée au
 * règlement. Refusé si le règlement est déjà comptabilisé (409). */
export async function postPurchasePaymentEntryAction(
  companyId: string,
  paymentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/purchase-payments/{payment_id}/entry",
    { params: { path: { company_id: companyId, payment_id: paymentId } }, body: {} },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.purchases.paymentPosted };
}
