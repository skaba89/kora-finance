import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { createCompany, postEntry, registerAndLogin } from "./helpers";

test("téléchargement de la balance en PDF et des états financiers en Excel", async ({ page }) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Café de Labé SARL");
  await postEntry(page, companyId, {
    journal: "VT — Ventes",
    date: "2026-02-15",
    label: "Ventes de café",
    debit: "571",
    credit: "701",
    amount: "450000",
  });

  await page.goto(`/dossiers/${companyId}/balance`);
  const balanceExport = page.getByRole("group", { name: "Exporter" });
  const pdfDownload = page.waitForEvent("download");
  await balanceExport.getByRole("link", { name: "PDF" }).click();
  const pdf = await pdfDownload;
  expect(pdf.suggestedFilename()).toMatch(/^balance-cafe-de-labe-sarl-20260101-20261231\.pdf$/);
  const pdfContent = await readFile((await pdf.path())!);
  expect(pdfContent.subarray(0, 5).toString()).toBe("%PDF-");

  await page.goto(`/dossiers/${companyId}/etats-financiers`);
  const xlsxDownload = page.waitForEvent("download");
  await page.getByRole("group", { name: "Exporter" }).getByRole("link", { name: "Excel" }).click();
  const xlsx = await xlsxDownload;
  expect(xlsx.suggestedFilename()).toMatch(/^etats-financiers-.*\.xlsx$/);
  const xlsxContent = await readFile((await xlsx.path())!);
  expect(xlsxContent.subarray(0, 2).toString()).toBe("PK"); // archive OOXML
});

test("une demande d'export invalide est refusée proprement", async ({ page }) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Atelier de Mamou SARL");
  const response = await page.request.get(`/dossiers/${companyId}/exports/balance?format=csv`);
  expect(response.status()).toBe(400);
});
