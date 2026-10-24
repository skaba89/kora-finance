import { expect, test } from "@playwright/test";

import { createCompany, postEntry, registerAndLogin } from "./helpers";

test("verrouillage, clôture avec à-nouveaux, puis réouverture", async ({ page }) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Menuiserie de Kankan SARL");
  await postEntry(page, companyId, {
    journal: "VT — Ventes",
    date: "2026-03-10",
    label: "Vente de meubles",
    debit: "571",
    credit: "701",
    amount: "900000",
  });
  await page.goto(`/dossiers/${companyId}/parametres/exercices`);
  const year2026 = page.getByRole("region", { name: /^01\/01\/2026/ });

  // Verrouillage du premier trimestre.
  await year2026.getByLabel("Verrouiller jusqu'au").fill("2026-03-31");
  await year2026.getByRole("button", { name: "Verrouiller" }).click();
  await expect(year2026.getByText("Verrouillé jusqu'au 31/03/2026")).toBeVisible();

  // Clôture impossible tant que l'exercice suivant n'existe pas.
  await expect(year2026.getByText(/Créez d'abord l'exercice suivant/)).toBeVisible();
  await expect(year2026.getByText(/900\s000 GNF/)).toBeVisible();
  await page.getByLabel("Début").fill("2027-01-01");
  await page.getByLabel("Fin").fill("2027-12-31");
  await page.getByRole("button", { name: "Ajouter" }).click();

  page.once("dialog", (dialog) => void dialog.accept());
  await year2026.getByRole("button", { name: "Clôturer l'exercice" }).click();
  await expect(year2026.getByText(/Clôturé le/)).toBeVisible();

  // Les à-nouveaux portent la caisse et le bénéfice dans 2027.
  await page.goto(`/dossiers/${companyId}/balance`);
  await page.getByLabel("Exercice").selectOption({ label: "01/01/2027 – 31/12/2027" });
  await page.getByRole("button", { name: "Afficher" }).click();
  await expect(page.getByText("Balance équilibrée")).toBeVisible();
  const profit = page
    .locator("tr, li")
    .filter({ hasText: "Résultat net : bénéfice" })
    .filter({ visible: true });
  await expect(profit).toContainText("900 000 GNF");

  // Réouverture.
  await page.goto(`/dossiers/${companyId}/parametres/exercices`);
  page.once("dialog", (dialog) => void dialog.accept());
  await year2026.getByRole("button", { name: "Rouvrir l'exercice" }).click();
  await expect(year2026.getByText("Verrouillé jusqu'au 31/03/2026")).toBeVisible();
});
