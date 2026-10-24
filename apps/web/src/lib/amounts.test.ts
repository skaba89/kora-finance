import { describe, expect, it } from "vitest";

import { amountInputValue, parseAmount, sumAmounts } from "./amounts";

describe("parseAmount", () => {
  it("lit un montant GNF avec ou sans séparateurs", () => {
    expect(parseAmount("1 500 000", 0)).toBe("1500000");
    expect(parseAmount("1 500 000", 0)).toBe("1500000");
    expect(parseAmount("007", 0)).toBe("7");
    expect(parseAmount("", 0)).toBe("0");
  });

  it("refuse les décimales en GNF et toute saisie non numérique", () => {
    expect(parseAmount("12,5", 0)).toBeNull();
    expect(parseAmount("-100", 0)).toBeNull();
    expect(parseAmount("1e6", 0)).toBeNull();
    expect(parseAmount("abc", 0)).toBeNull();
  });

  it("gère les devises à décimales sans flottant", () => {
    expect(parseAmount("12,5", 2)).toBe("1250");
    expect(parseAmount("0.07", 2)).toBe("7");
    expect(parseAmount("12,345", 2)).toBeNull();
  });

  it("refuse les montants démesurés", () => {
    expect(parseAmount("9".repeat(19), 0)).toBeNull();
  });
});

describe("amountInputValue", () => {
  it("restitue la saisie", () => {
    expect(amountInputValue("1500000", 0)).toBe("1500000");
    expect(amountInputValue("0", 0)).toBe("");
    expect(amountInputValue("7", 2)).toBe("0,07");
  });
});

describe("sumAmounts", () => {
  it("additionne au-delà de la précision des nombres JavaScript", () => {
    expect(sumAmounts(["9007199254740993", "1"])).toBe(9007199254740994n);
  });
});
