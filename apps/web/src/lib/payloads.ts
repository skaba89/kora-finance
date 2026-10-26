import { parseAmount } from "@/lib/amounts";
import type { components } from "@/lib/api/schema";

/**
 * Corps envoyés à l'API pour créer une écriture, préparés par les formulaires (en ligne
 * ou hors connexion) et revérifiés côté serveur avant l'appel (l'API revérifie aussi).
 * Module sans dépendance serveur : utilisé par les Server Actions et par le navigateur.
 */

export type EntryIn = components["schemas"]["EntryIn"];
export type GuidedIn = components["schemas"]["GuidedIn"];
export type Operation = components["schemas"]["Operation"];

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DIGITS = /^(0|[1-9][0-9]{0,17})$/;

export const OPERATIONS: readonly Operation[] = [
  "VENTE_COMPTANT",
  "FACTURE_CLIENT",
  "ENCAISSEMENT_CLIENT",
  "ACHAT_COMPTANT",
  "FACTURE_FOURNISSEUR",
  "PAIEMENT_FOURNISSEUR",
  "VIREMENT_INTERNE",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Écriture libre (objet déjà décodé) ; null si la forme est invalide. */
export function parseEntry(value: unknown): EntryIn | null {
  if (!isRecord(value)) return null;
  const v = value;
  if (typeof v.journal_id !== "string" || !UUID.test(v.journal_id)) return null;
  if (typeof v.entry_date !== "string" || !DATE.test(v.entry_date)) return null;
  if (typeof v.label !== "string") return null;
  if (v.reference !== null && typeof v.reference !== "string") return null;
  if (!Array.isArray(v.lines)) return null;
  const lines = [];
  for (const line of v.lines as unknown[]) {
    if (!isRecord(line)) return null;
    const l = line;
    if (typeof l.account_id !== "string" || !UUID.test(l.account_id)) return null;
    if (typeof l.debit !== "string" || !DIGITS.test(l.debit)) return null;
    if (typeof l.credit !== "string" || !DIGITS.test(l.credit)) return null;
    if (l.label !== null && typeof l.label !== "string") return null;
    lines.push({ account_id: l.account_id, debit: l.debit, credit: l.credit, label: l.label });
  }
  return { journal_id: v.journal_id, entry_date: v.entry_date, label: v.label, reference: v.reference, lines };
}

/** Écriture libre transmise en JSON par l'éditeur. */
export function parseEntryJson(raw: string): EntryIn | null {
  try {
    return parseEntry(JSON.parse(raw));
  } catch {
    return null;
  }
}

function text(value: FormDataEntryValue | null): string {
  return typeof value === "string" ? value.trim() : "";
}

function optionalUuid(value: FormDataEntryValue | null): string | null {
  const v = text(value);
  return UUID.test(v) ? v : null;
}

export type GuidedBodyResult = { body: GuidedIn } | { error: "amount" | "date" };

/** Saisie guidée : formulaire → corps de l'API (montant converti en unités mineures). */
export function guidedBody(formData: FormData, operation: Operation, decimals: number): GuidedBodyResult {
  const amount = parseAmount(text(formData.get("amount")), decimals);
  if (amount === null || amount === "0") return { error: "amount" };
  const entryDate = text(formData.get("entry_date"));
  if (!DATE.test(entryDate)) return { error: "date" };
  return {
    body: {
      operation,
      entry_date: entryDate,
      amount,
      label: text(formData.get("label")) || null,
      reference: text(formData.get("reference")) || null,
      nature_account_id: optionalUuid(formData.get("nature_account_id")),
      treasury_account_id: optionalUuid(formData.get("treasury_account_id")),
      target_treasury_account_id: optionalUuid(formData.get("target_treasury_account_id")),
      party_account_id: optionalUuid(formData.get("party_account_id")),
      vat_included: formData.get("vat_included") === "on",
    },
  };
}

function uuidOrNull(value: unknown): value is string | null | undefined {
  return value === null || value === undefined || (typeof value === "string" && UUID.test(value));
}

function stringOrNull(value: unknown, max: number): value is string | null | undefined {
  return value === null || value === undefined || (typeof value === "string" && value.length <= max);
}

/** Saisie guidée conservée hors connexion : revérifiée avant l'envoi. */
export function parseGuided(value: unknown): GuidedIn | null {
  if (!isRecord(value)) return null;
  const v = value;
  if (typeof v.operation !== "string" || !OPERATIONS.includes(v.operation as Operation)) return null;
  if (typeof v.entry_date !== "string" || !DATE.test(v.entry_date)) return null;
  if (typeof v.amount !== "string" || !DIGITS.test(v.amount) || v.amount === "0") return null;
  if (typeof v.vat_included !== "boolean") return null;
  if (!stringOrNull(v.label, 200) || !stringOrNull(v.reference, 60)) return null;
  const ids = [v.nature_account_id, v.treasury_account_id, v.target_treasury_account_id, v.party_account_id];
  if (!ids.every(uuidOrNull)) return null;
  return {
    operation: v.operation as Operation,
    entry_date: v.entry_date,
    amount: v.amount,
    label: v.label ?? null,
    reference: v.reference ?? null,
    nature_account_id: (v.nature_account_id as string | null | undefined) ?? null,
    treasury_account_id: (v.treasury_account_id as string | null | undefined) ?? null,
    target_treasury_account_id: (v.target_treasury_account_id as string | null | undefined) ?? null,
    party_account_id: (v.party_account_id as string | null | undefined) ?? null,
    vat_included: v.vat_included,
  };
}
