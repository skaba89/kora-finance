import type { SalesDict } from "./types";

/** Constantes et libellés partagés de la page ventes. Les fonctions prennent
 * le dictionnaire en argument : elles restent utilisables depuis un composant
 * serveur comme client sans dépendre de `server-only`. */

export const SALES_KINDS = ["quote", "invoice", "credit_note"] as const;
export type SalesKind = (typeof SALES_KINDS)[number];

export const SALES_STATUSES = [
  "DRAFT",
  "SENT",
  "ACCEPTED",
  "REJECTED",
  "ISSUED",
  "CANCELLED",
] as const;
export type SalesStatus = (typeof SALES_STATUSES)[number];

/** Méthodes de règlement dans l'ordre de présentation côté ventes. */
export const SALES_PAYMENT_METHODS = [
  "MOBILE_MONEY",
  "CASH",
  "BANK_TRANSFER",
  "CHECK",
  "CARD",
  "OTHER",
] as const;

export function salesKindLabel(t: SalesDict, value: string) {
  return value === "quote"
    ? t.kinds.quote
    : value === "credit_note"
      ? t.kinds.creditNote
      : t.kinds.invoice;
}

export function salesStatusLabel(t: SalesDict, value: string) {
  return (t.statuses as Record<string, string>)[value] ?? value;
}

export type BadgeTone = "default" | "destructive" | "secondary" | "outline";

export function salesStatusTone(value: string): BadgeTone {
  return value === "ISSUED" || value === "ACCEPTED"
    ? "default"
    : value === "CANCELLED" || value === "REJECTED"
      ? "destructive"
      : value === "DRAFT"
        ? "secondary"
        : "outline";
}

/** Préfixe d'affichage du numéro (DEV / FAC / AV) — numérotation sans trou. */
export function salesDocPrefix(kind: string) {
  return kind === "quote" ? "DEV" : kind === "credit_note" ? "AV" : "FAC";
}

/** Taux de TVA actifs à la date du jour, prêts pour un menu de sélection. */
export function activeRateOptions(
  rates: { id: string; label: string; rate_basis_points: number; valid_from: string; valid_to: string | null }[],
) {
  const today = new Date().toISOString().slice(0, 10);
  return rates
    .filter((rate) => rate.valid_from <= today && (!rate.valid_to || rate.valid_to >= today))
    .map((rate) => ({
      value: rate.id,
      label: `${rate.label} (${rate.rate_basis_points / 100} %)`,
    }));
}
