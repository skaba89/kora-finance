import { describe, expect, it } from "vitest";

import {
  aggregateWeekly,
  barHeight,
  statusLabel,
  statusTone,
  weekKey,
  type DailyProjection,
} from "./cashflow";

function day(flow_date: string, balance: string, inflow = "0", outflow = "0"): DailyProjection {
  return {
    flow_date,
    inflow,
    outflow,
    balance,
    status: "SAIN",
    committed_inflow: "0",
    committed_outflow: "0",
    estimated_inflow: inflow,
    estimated_outflow: outflow,
  };
}

describe("weekKey", () => {
  it("renvoie le lundi de la semaine ISO", () => {
    // Mercredi 12/11/2026 → lundi 09/11/2026.
    expect(weekKey("2026-11-12")).toBe("2026-11-09");
    // Dimanche 15/11/2026 → toujours lundi 09/11/2026.
    expect(weekKey("2026-11-15")).toBe("2026-11-09");
    // Lundi 16/11/2026 → nouvelle semaine.
    expect(weekKey("2026-11-16")).toBe("2026-11-16");
  });
});

describe("aggregateWeekly", () => {
  it("somme les flux et garde le solde de fin de semaine", () => {
    const weeks = aggregateWeekly([
      day("2026-11-09", "1000", "300", "100"),
      day("2026-11-10", "1200", "400", "200"),
      day("2026-11-16", "1500", "500", "200"),
    ]);
    expect(weeks).toHaveLength(2);
    expect(weeks[0].inflow).toBe(700n);
    expect(weeks[0].outflow).toBe(300n);
    expect(weeks[0].end_balance).toBe(1200n);
    expect(weeks[1].end_balance).toBe(1500n);
  });

  it("reste à zéro sans journée", () => {
    expect(aggregateWeekly([])).toEqual([]);
  });
});

describe("statuts", () => {
  it("associe le bon ton visuel", () => {
    expect(statusTone("SAIN")).toBe("positive");
    expect(statusTone("SOUS_SURVEILLANCE")).toBe("warning");
    expect(statusTone("CRITIQUE")).toBe("destructive");
  });

  it("libellés par locale", () => {
    expect(statusLabel("CRITIQUE", "fr")).toBe("Critique");
    expect(statusLabel("CRITIQUE", "en")).toBe("Critical");
  });
});

describe("barHeight", () => {
  it("proportion entière, aucun flottant", () => {
    expect(barHeight(50n, 100n, 40)).toBe(20);
    expect(barHeight(1n, 3n, 30)).toBe(10); // 30/3 exact
    expect(barHeight(1n, 3n, 40)).toBe(13); // 13,33… tronqué : jamais de flottant
  });

  it("gère le maximum nul et les montants nuls", () => {
    expect(barHeight(0n, 0n, 40)).toBe(0);
    expect(barHeight(0n, 100n, 40)).toBe(0);
  });
});
