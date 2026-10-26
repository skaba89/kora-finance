import { describe, expect, it } from "vitest";

import {
  applyOutcome,
  counts,
  expiredSynced,
  isExpired,
  itemAmount,
  outsideOpenYears,
  type QueueItem,
  snapshotExpiry,
  toSync,
} from "./model";

const ACCOUNT = "11111111-1111-4111-8111-111111111111";
const NOW = new Date("2026-06-10T08:00:00Z");

function free(id: string, createdAt: string, status: QueueItem["status"] = "pending"): QueueItem {
  return {
    id,
    userId: "u",
    companyId: "c",
    createdAt,
    updatedAt: createdAt,
    status,
    kind: "free",
    payload: {
      journal_id: ACCOUNT,
      entry_date: "2026-06-09",
      label: "Achat",
      reference: null,
      lines: [
        { account_id: ACCOUNT, label: null, debit: "9007199254740993", credit: "0" },
        { account_id: ACCOUNT, label: null, debit: "0", credit: "9007199254740993" },
      ],
    },
  };
}

describe("données conservées sur l'appareil", () => {
  it("expirent après 7 jours", () => {
    const expiresAt = snapshotExpiry(NOW);
    expect(expiresAt).toBe("2026-06-17T08:00:00.000Z");
    expect(isExpired({ expiresAt }, new Date("2026-06-17T07:59:59Z"))).toBe(false);
    expect(isExpired({ expiresAt }, new Date("2026-06-17T08:00:00Z"))).toBe(true);
  });

  it("signalent une date hors des exercices ouverts", () => {
    const years = [{ start_date: "2026-01-01", end_date: "2026-12-31" }];
    expect(outsideOpenYears("2026-06-10", years)).toBe(false);
    expect(outsideOpenYears("2025-12-31", years)).toBe(true);
    expect(outsideOpenYears("2026-06-10", [])).toBe(true);
  });
});

describe("file d'attente", () => {
  it("envoie les saisies en attente dans l'ordre de saisie", () => {
    const items = [free("b", "2026-06-10T09:00:00Z"), free("a", "2026-06-10T08:00:00Z"), free("c", "2026-06-10T07:00:00Z", "rejected")];
    expect(toSync(items).map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("applique le résultat d'un envoi sans perdre la saisie en cas d'échec réseau", () => {
    const item = free("a", "2026-06-10T08:00:00Z");
    expect(applyOutcome(item, { status: "retry" }, NOW)).toBeNull();
    expect(applyOutcome(item, { status: "auth" }, NOW)).toBeNull();
    const rejected = applyOutcome(item, { status: "rejected", message: "Exercice clôturé", errors: [] }, NOW);
    expect(rejected).toMatchObject({ status: "rejected", message: "Exercice clôturé", payload: item.payload });
    const synced = applyOutcome(rejected!, { status: "synced", entryId: "e" }, NOW);
    expect(synced).toMatchObject({ status: "synced", entryId: "e", syncedAt: NOW.toISOString(), message: undefined });
  });

  it("oublie les saisies synchronisées depuis plus de 7 jours", () => {
    const old = { ...free("a", "2026-06-01T08:00:00Z", "synced"), syncedAt: "2026-06-03T08:00:00Z" };
    const recent = { ...free("b", "2026-06-09T08:00:00Z", "synced"), syncedAt: "2026-06-09T08:00:00Z" };
    expect(expiredSynced([old, recent, free("c", "2026-06-01T08:00:00Z")], NOW).map((i) => i.id)).toEqual(["a"]);
  });

  it("calcule les montants en BigInt, sans perte au-delà de 2^53", () => {
    expect(itemAmount(free("a", "2026-06-10T08:00:00Z"))).toBe(9007199254740993n);
  });

  it("compte les saisies par statut", () => {
    const items = [free("a", "x"), free("b", "x", "rejected"), free("c", "x", "synced"), free("d", "x")];
    expect(counts(items)).toEqual({ pending: 2, rejected: 1, synced: 1 });
  });
});
