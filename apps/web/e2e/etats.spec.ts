import { expect, test } from "@playwright/test";

import { createCompany, postEntry, registerAndLogin } from "./helpers";

test("balance générale et grand livre après deux écritures", async ({ page, isMobile }) => {
  // Tableau sur grand écran, une fiche par compte ou mouvement sur téléphone.
  const item = isMobile ? "listitem" : "row";
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Boutique de Dixinn SARL");
  await postEntry(page, companyId, {
    journal: "AN — À-nouveaux",
    date: "2026-01-01",
    label: "Apport en capital",
    debit: "521",
    credit: "101",
    amount: "5000000",
  });
  await postEntry(page, companyId, {
    journal: "AC — Achats",
    date: "2026-02-10",
    label: "Achat de marchandises",
    debit: "601",
    credit: "521",
    amount: "750000",
  });

  await page.getByRole("link", { name: "Balance", exact: true }).click();
  await expect(page.getByText("Balance équilibrée")).toBeVisible();
  const bank = page.getByRole(item).filter({ hasText: "521" }).first();
  await expect(bank).toContainText("5 000 000 GNF");
  await expect(bank).toContainText("4 250 000 GNF");
  if (isMobile) {
    await expect(page.getByRole(item).filter({ hasText: "Total général" })).toContainText("5 000 000 GNF");
  } else {
    // Ouverture 5 000 000 / 5 000 000, mouvements 750 000 / 750 000, clôture 5 000 000 / 5 000 000.
    // Séparateurs de milliers : espaces fines insécables (fr-FR), d'où \s.
    await expect(page.getByRole(item).filter({ hasText: "Total général" })).toHaveText(
      /^Total général(5\s000\s000\sGNF){2}(750\s000\sGNF){2}(5\s000\s000\sGNF){2}$/,
    );
  }

  await bank.getByRole("link", { name: /521/ }).click();
  await expect(page).toHaveURL(/grand-livre\?compte=521/);
  await expect(page.getByRole(item).filter({ hasText: "Solde d'ouverture" })).toContainText("5 000 000 GNF D");
  await expect(page.getByRole(item).filter({ hasText: "Achat de marchandises" })).toContainText("4 250 000 GNF D");
  await expect(page.getByRole(item).filter({ hasText: "Solde de clôture" })).toContainText("4 250 000 GNF D");
});
