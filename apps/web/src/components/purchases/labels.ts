import type { Dictionary } from "./types";

export type PurchaseDict = Dictionary["purchases"];

/** Constantes et libellés partagés de la page achats. */

export const PURCHASE_KINDS = ["supplier_invoice", "supplier_credit_note"] as const;
export type PurchaseKind = (typeof PURCHASE_KINDS)[number];

export const PURCHASE_STATUSES = ["DRAFT", "ISSUED", "CANCELLED"] as const;
export type PurchaseStatus = (typeof PURCHASE_STATUSES)[number];

/** Méthodes de décaissement dans l'ordre de présentation côté achats. */
export const PURCHASE_PAYMENT_METHODS = [
  "BANK_TRANSFER",
  "MOBILE_MONEY",
  "CASH",
  "CHECK",
  "CARD",
  "OTHER",
] as const;

export function purchasesKindLabel(t: PurchaseDict, value: string) {
  return value === "supplier_credit_note"
    ? t.kinds.supplierCreditNote
    : t.kinds.supplierInvoice;
}

export function purchasesStatusLabel(t: PurchaseDict, value: string) {
  return (t.statuses as Record<string, string>)[value] ?? value;
}

export type BadgeTone = "default" | "destructive" | "secondary" | "outline";

export function purchasesStatusTone(value: string): BadgeTone {
  return value === "CANCELLED" ? "destructive" : value === "DRAFT" ? "secondary" : "default";
}

/** Préfixe d'affichage du numéro interne fournisseur (FACH / AVF). */
export function purchasesDocPrefix(kind: string) {
  return kind === "supplier_credit_note" ? "AVF" : "FACH";
}

/** Numéro complet affiché (FACH-12, AVF-3) ou tiret si non numéroté. */
export function purchasesDisplayNumber(kind: string, number: number | null) {
  return number == null ? "—" : `${purchasesDocPrefix(kind)}-${number}`;
}

/** Taux de TVA actifs à la date du jour, prêts pour un menu de sélection. */
export function activeRateOptions(
  rates: { id: string; label: string; rate_basis_points: number; valid_from: string; valid_to: string | null }[],
) {
  const today = new Date().toISOString().slice(0, 10);
  return rates
    .filter((rate) => rate.valid_from <= today && (rate.valid_to == null || rate.valid_to >= today))
    .map((rate) => ({ value: rate.id, label: `${rate.label} (${rate.rate_basis_points / 100} %)` }));
}
