import { expect, test } from "@playwright/test";

import { createCompany, postEntry, registerAndLogin } from "./helpers";

test("bilan équilibré et compte de résultat", async ({ page, isMobile }) => {
  const item = isMobile ? "listitem" : "row";
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Savonnerie de Boké SARL");
  await postEntry(page, companyId, {
    journal: "AN — À-nouveaux",
    date: "2026-01-01",
    label: "Apport en capital",
    debit: "521",
    credit: "101",
    amount: "3000000",
  });
  await postEntry(page, companyId, {
    journal: "VT — Ventes",
    date: "2026-02-15",
    label: "Ventes de savon",
    debit: "571",
    credit: "701",
    amount: "1200000",
  });

  await page.getByRole("link", { name: "États financiers" }).click();
  await expect(page.getByText("Bilan équilibré")).toBeVisible();
  await expect(page.getByText(/à valider par un expert-comptable guinéen/)).toBeVisible();
  const assets = page.getByRole("region", { name: "Actif" });
  await expect(assets.getByRole(item).filter({ hasText: "TOTAL GÉNÉRAL" })).toContainText("4 200 000 GNF");
  const liabilities = page.getByRole("region", { name: "Passif" });
  await expect(liabilities.getByRole(item).filter({ hasText: "Résultat net de l'exercice" })).toContainText(
    "1 200 000 GNF",
  );

  await page.getByRole("link", { name: "Compte de résultat" }).click();
  const income = page.getByRole("region", { name: "Compte de résultat" });
  await expect(income.getByRole(item).filter({ hasText: "CHIFFRE D'AFFAIRES" })).toContainText("1 200 000 GNF");
  await expect(income.getByRole(item).filter({ hasText: "RÉSULTAT NET" })).toContainText("1 200 000 GNF");
});
