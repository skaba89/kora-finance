import { describe, expect, it } from "vitest";

import { formatDate, formatMoney, formatRate } from "./format";

// Intl insère des espaces insécables : on les normalise pour comparer.
const plain = (s: string) => s.replace(/[  ]/g, " ");

describe("formatMoney", () => {
  it("affiche les GNF sans décimales", () => {
    expect(plain(formatMoney(1_500_000, "GNF"))).toBe("1 500 000 GNF");
  });
  it("gère les montants négatifs", () => {
    expect(plain(formatMoney(-25_000, "GNF"))).toBe("-25 000 GNF");
  });
  it("garde le signe des montants inférieurs à une unité (devises à décimales)", () => {
    expect(plain(formatMoney(-50, "EUR"))).toBe("-0,50 EUR");
  });
  it("accepte les très grands montants sans perte de précision", () => {
    expect(plain(formatMoney(12_345_678_901_234_567n, "GNF"))).toBe(
      "12 345 678 901 234 567 GNF",
    );
  });
});

describe("formatDate", () => {
  it("affiche les dates au format français sans décalage de fuseau", () => {
    expect(formatDate("2026-01-01")).toBe("01/01/2026");
    expect(formatDate("2026-12-31", "en")).toBe("31/12/2026");
  });
});

describe("formatRate", () => {
  it("convertit les points de base en pourcentage", () => {
    expect(plain(formatRate(1800))).toBe("18 %");
    expect(plain(formatRate(1850))).toBe("18,5 %");
  });
});
