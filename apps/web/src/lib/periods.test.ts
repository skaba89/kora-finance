import { describe, expect, it } from "vitest";

import { dateWithin, pickFiscalYear } from "./periods";

const years = [
  { id: "a", start_date: "2025-01-01", end_date: "2025-12-31", status: "CLOSED" },
  { id: "b", start_date: "2026-01-01", end_date: "2026-12-31", status: "OPEN" },
  { id: "c", start_date: "2027-01-01", end_date: "2027-12-31", status: "OPEN" },
];

describe("pickFiscalYear", () => {
  it("respecte l'exercice demandé", () => {
    expect(pickFiscalYear(years, "a", "2026-10-24")?.id).toBe("a");
  });
  it("prend l'exercice en cours, sinon le plus récent", () => {
    expect(pickFiscalYear(years, undefined, "2026-10-24")?.id).toBe("b");
    expect(pickFiscalYear(years, "inconnu", "2030-01-01")?.id).toBe("c");
    expect(pickFiscalYear([], undefined, "2026-10-24")).toBeUndefined();
  });
});

describe("dateWithin", () => {
  it("n'accepte qu'une date de l'exercice", () => {
    expect(dateWithin("2026-03-01", years[1]!)).toBe("2026-03-01");
    expect(dateWithin("2025-03-01", years[1]!)).toBeUndefined();
    expect(dateWithin("01/03/2026", years[1]!)).toBeUndefined();
  });
});
