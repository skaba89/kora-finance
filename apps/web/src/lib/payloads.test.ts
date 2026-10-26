import { describe, expect, it } from "vitest";

import { guidedBody, parseEntry, parseEntryJson, parseGuided } from "./payloads";

const ACCOUNT = "11111111-1111-4111-8111-111111111111";
const JOURNAL = "22222222-2222-4222-8222-222222222222";

const entry = {
  journal_id: JOURNAL,
  entry_date: "2026-06-10",
  label: "Achat de fournitures",
  reference: null,
  lines: [
    { account_id: ACCOUNT, label: null, debit: "150000", credit: "0" },
    { account_id: ACCOUNT, label: "Caisse", debit: "0", credit: "150000" },
  ],
};

describe("parseEntry", () => {
  it("accepte une écriture bien formée", () => {
    expect(parseEntry(entry)).toEqual(entry);
    expect(parseEntryJson(JSON.stringify(entry))).toEqual(entry);
  });

  it("refuse montants non entiers, identifiants invalides et JSON illisible", () => {
    expect(parseEntry({ ...entry, lines: [{ ...entry.lines[0], debit: "1500.5" }] })).toBeNull();
    expect(parseEntry({ ...entry, lines: [{ ...entry.lines[0], debit: "-5" }] })).toBeNull();
    expect(parseEntry({ ...entry, journal_id: "OD" })).toBeNull();
    expect(parseEntry({ ...entry, entry_date: "10/06/2026" })).toBeNull();
    expect(parseEntry({ ...entry, lines: ["x"] })).toBeNull();
    expect(parseEntryJson("{")).toBeNull();
    expect(parseEntry(null)).toBeNull();
  });
});

function form(values: Record<string, string>) {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) data.set(key, value);
  return data;
}

describe("guidedBody", () => {
  it("convertit le montant en unités mineures et ignore les identifiants invalides", () => {
    const result = guidedBody(
      form({ amount: "1 180 000", entry_date: "2026-06-10", nature_account_id: ACCOUNT, treasury_account_id: "x", vat_included: "on", label: "  " }),
      "VENTE_COMPTANT",
      0,
    );
    expect(result).toEqual({
      body: {
        operation: "VENTE_COMPTANT",
        entry_date: "2026-06-10",
        amount: "1180000",
        label: null,
        reference: null,
        nature_account_id: ACCOUNT,
        treasury_account_id: null,
        target_treasury_account_id: null,
        party_account_id: null,
        vat_included: true,
      },
    });
  });

  it("refuse un montant nul ou invalide et une date absente", () => {
    expect(guidedBody(form({ amount: "0", entry_date: "2026-06-10" }), "VENTE_COMPTANT", 0)).toEqual({ error: "amount" });
    expect(guidedBody(form({ amount: "12,5", entry_date: "2026-06-10" }), "VENTE_COMPTANT", 0)).toEqual({ error: "amount" });
    expect(guidedBody(form({ amount: "100" }), "VENTE_COMPTANT", 0)).toEqual({ error: "date" });
  });
});

describe("parseGuided", () => {
  const body = {
    operation: "ACHAT_COMPTANT",
    entry_date: "2026-06-10",
    amount: "50000",
    label: null,
    reference: "F-12",
    nature_account_id: ACCOUNT,
    treasury_account_id: ACCOUNT,
    target_treasury_account_id: null,
    party_account_id: null,
    vat_included: false,
  };

  it("revérifie une saisie guidée conservée sur l'appareil", () => {
    expect(parseGuided(body)).toEqual(body);
  });

  it("refuse opération inconnue, montant nul, identifiant ou texte invalide", () => {
    expect(parseGuided({ ...body, operation: "DON" })).toBeNull();
    expect(parseGuided({ ...body, amount: "0" })).toBeNull();
    expect(parseGuided({ ...body, party_account_id: "401" })).toBeNull();
    expect(parseGuided({ ...body, reference: "x".repeat(61) })).toBeNull();
    expect(parseGuided({ ...body, vat_included: "on" })).toBeNull();
  });
});
