import { describe, expect, it } from "vitest";

import { exportHref, exportQuery, isExportKind } from "./exports";

const FY = "0b7c4c4e-8a6e-4f0e-9a51-3f6f1f2d9c11";

describe("exports", () => {
  it("construit puis relit un lien de téléchargement", () => {
    const href = exportHref("c1", "balance", "pdf", { fiscalYearId: FY, dateFrom: "2026-03-01" });
    expect(href).toBe(`/dossiers/c1/exports/balance?format=pdf&exercice=${FY}&du=2026-03-01`);
    const params = new URL(href, "https://kora.test").searchParams;
    expect(exportQuery(params)).toEqual({ format: "pdf", fiscal_year_id: FY, date_from: "2026-03-01" });
  });

  it("refuse format, exercice ou type inconnus et ignore les paramètres invalides", () => {
    expect(exportQuery(new URLSearchParams({ format: "csv", exercice: FY }))).toBeNull();
    expect(exportQuery(new URLSearchParams({ format: "pdf", exercice: "x" }))).toBeNull();
    expect(exportQuery(new URLSearchParams({ format: "xlsx", exercice: FY, du: "01/03/2026", compte_id: "1" }))).toEqual(
      { format: "xlsx", fiscal_year_id: FY },
    );
    expect(isExportKind("balance")).toBe(true);
    expect(isExportKind("toString")).toBe(false);
  });
});
