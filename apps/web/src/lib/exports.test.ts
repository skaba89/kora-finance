import { describe, expect, it } from "vitest";

import { agingExportHref, exportHref, exportQuery, isExportKind, previsionsExportHref } from "./exports";

const FY = "0b7c4c4e-8a6e-4f0e-9a51-3f6f1f2d9c11";

describe("exports", () => {
  it("construit puis relit un lien de téléchargement", () => {
    const href = exportHref("c1", "balance", "pdf", { fiscalYearId: FY, dateFrom: "2026-03-01" });
    expect(href).toBe(`/dossiers/c1/exports/balance?format=pdf&exercice=${FY}&du=2026-03-01`);
    const params = new URL(href, "https://kora.test").searchParams;
    expect(exportQuery("balance", params)).toEqual({ format: "pdf", fiscal_year_id: FY, date_from: "2026-03-01" });
  });

  it("refuse format, exercice ou type inconnus et ignore les paramètres invalides", () => {
    expect(exportQuery("balance", new URLSearchParams({ format: "csv", exercice: FY }))).toBeNull();
    expect(exportQuery("balance", new URLSearchParams({ format: "pdf", exercice: "x" }))).toBeNull();
    expect(
      exportQuery("balance", new URLSearchParams({ format: "xlsx", exercice: FY, du: "01/03/2026", compte_id: "1" })),
    ).toEqual({ format: "xlsx", fiscal_year_id: FY });
    expect(isExportKind("balance")).toBe(true);
    expect(isExportKind("toString")).toBe(false);
  });
});

describe("exports prévisions de trésorerie (Phase 3E)", () => {
  it("construit puis relit un lien prévisions", () => {
    const href = previsionsExportHref("c1", "xlsx", 60, "PRUDENT");
    expect(href).toBe("/dossiers/c1/exports/previsions-tresorerie?format=xlsx&horizon=60&scenario=PRUDENT");
    const params = new URL(href, "https://kora.test").searchParams;
    expect(exportQuery("previsions-tresorerie", params)).toEqual({
      format: "xlsx",
      horizon: 60,
      scenario: "PRUDENT",
    });
    expect(isExportKind("previsions-tresorerie")).toBe(true);
  });

  it("refuse horizon, scénario ou format hors liste blanche", () => {
    const base = { format: "pdf", horizon: "90", scenario: "NEUTRE" } as Record<string, string>;
    expect(exportQuery("previsions-tresorerie", new URLSearchParams({ ...base, horizon: "45" }))).toBeNull();
    expect(exportQuery("previsions-tresorerie", new URLSearchParams({ ...base, scenario: "MAGIQUE" }))).toBeNull();
    expect(exportQuery("previsions-tresorerie", new URLSearchParams({ ...base, format: "csv" }))).toBeNull();
    // Les paramètres d'exercice ne s'appliquent pas à la prévision : ignorés, non reconnus.
    expect(exportQuery("previsions-tresorerie", new URLSearchParams({ format: "pdf", exercice: FY }))).toBeNull();
  });
});

describe("exports balance âgée clients (lot B-4)", () => {
  it("construit puis relit un lien balance âgée (situation du jour ou datée)", () => {
    const href = agingExportHref("c1", "pdf");
    expect(href).toBe("/dossiers/c1/exports/balance-agee?format=pdf");
    let params = new URL(href, "https://kora.test").searchParams;
    expect(exportQuery("balance-agee", params)).toEqual({ format: "pdf" });
    params = new URL(agingExportHref("c1", "xlsx", "2026-03-01"), "https://kora.test").searchParams;
    expect(exportQuery("balance-agee", params)).toEqual({ format: "xlsx", as_of: "2026-03-01" });
    expect(isExportKind("balance-agee")).toBe(true);
  });

  it("refuse un format hors liste et ignore les paramètres d'exercice", () => {
    expect(
      exportQuery("balance-agee", new URLSearchParams({ format: "csv" })),
    ).toBeNull();
    expect(
      exportQuery("balance-agee", new URLSearchParams({ format: "pdf", exercice: FY })),
    ).toEqual({ format: "pdf" });
    // Date invalide : ignorée, la situation reste « au jour présent ».
    expect(
      exportQuery("balance-agee", new URLSearchParams({ format: "pdf", au_jour: "01/03/2026" })),
    ).toEqual({ format: "pdf" });
  });
});
