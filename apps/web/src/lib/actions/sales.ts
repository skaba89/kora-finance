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

/** Crée un brouillon (devis, facture ou avoir) : jamais numéroté à la création. */
export async function createDocumentAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const kind = field(formData, "doc_kind");
  if (kind !== "quote" && kind !== "invoice" && kind !== "credit_note") {
    return { status: "error", message: "Type de document inconnu." };
  }
  const lines = parseLines(formData);
  if (lines.length === 0) {
    const t = await actionDictionary();
    return { status: "error", message: t.sales.lineRequired };
  }
  const partnerId = field(formData, "partner_id");
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/sales",
    {
      params: { path: { company_id: companyId } },
      body: {
        doc_kind: kind,
        partner_id: partnerId,
        lines,
        due_on: field(formData, "due_on") || undefined,
        valid_until: field(formData, "valid_until") || undefined,
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

/** Émission définitive d'une facture ou d'un avoir : numérotation sans trou. */
export async function issueDocumentAction(
  companyId: string,
  documentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/sales/{document_id}/issue",
    { params: { path: { company_id: companyId, document_id: documentId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.sales.issued };
}

/** Envoi d'un devis : numérotation définitive à l'envoi. */
export async function sendQuoteAction(
  companyId: string,
  documentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/sales/{document_id}/send",
    { params: { path: { company_id: companyId, document_id: documentId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.sales.sent };
}

/** Acceptation ou refus d'un devis envoyé (le numéro est conservé). */
export async function decideQuoteAction(
  companyId: string,
  documentId: string,
  accepted: boolean,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/sales/{document_id}/decision",
    {
      params: { path: { company_id: companyId, document_id: documentId } },
      body: { accepted },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

/** Conversion d'un devis accepté en facture brouillon (numérotée à son émission). */
export async function convertQuoteAction(
  companyId: string,
  documentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/sales/{document_id}/convert",
    { params: { path: { company_id: companyId, document_id: documentId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.sales.converted };
}

/** Annulation d'une facture émise (numéro conservé, jamais réutilisé). */
export async function cancelInvoiceAction(
  companyId: string,
  documentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/sales/{document_id}/cancel",
    { params: { path: { company_id: companyId, document_id: documentId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.sales.cancelled };
}

/** Suppression d'un brouillon : aucun numéro n'a été consommé (pas de trou). */
export async function deleteDocumentAction(
  companyId: string,
  documentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).DELETE(
    "/api/v1/companies/{company_id}/sales/{document_id}",
    { params: { path: { company_id: companyId, document_id: documentId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.sales.deleted };
}

/** Enregistre un règlement client sur une facture émise (lettrage commercial 4C).
 * Le montant est contrôlé côté serveur : jamais au-delà du solde restant dû. */
export async function createPaymentAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const documentId = field(formData, "document_id");
  const amount = Number(field(formData, "amount") || "0");
  const method = field(formData, "method") || "CASH";
  if (!documentId || !Number.isFinite(amount) || amount <= 0) {
    const t = await actionDictionary();
    return { status: "error", message: t.sales.paymentAmountRequired };
  }
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/payments",
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
  return { status: "success", message: t.sales.paymentRecorded };
}

/** Supprime un règlement (correction de saisie) : les soldes sont libérés. */
export async function deletePaymentAction(
  companyId: string,
  paymentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).DELETE(
    "/api/v1/companies/{company_id}/payments/{payment_id}",
    { params: { path: { company_id: companyId, payment_id: paymentId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.sales.paymentDeleted };
}
