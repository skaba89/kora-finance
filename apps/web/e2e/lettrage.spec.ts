import { expect, test } from "@playwright/test";

import { createCompany, postEntry, registerAndLogin } from "./helpers";

test("lettrage d'une facture client et de son règlement, puis délettrage", async ({ page }, testInfo) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Imprimerie de Kaloum SARL");
  await postEntry(page, companyId, {
    journal: "VT — Ventes",
    date: "2026-02-10",
    label: "Facture F-12 Hôtel Riviera",
    debit: "411",
    credit: "701",
    amount: "850000",
  });
  await postEntry(page, companyId, {
    journal: "BQ — Banque",
    date: "2026-03-02",
    label: "Règlement F-12",
    debit: "521",
    credit: "411",
    amount: "850000",
  });

  await page.goto(`/dossiers/${companyId}/lettrage?compte=411`);
  await page.getByRole("combobox", { name: "Densité du tableau" }).selectOption("compact");
  await page.getByRole("button", { name: "Afficher", exact: true }).click();
  await expect(page).toHaveURL(/densite=compact/);
  await expect(page.getByText("Solde non lettré : 0 GNF")).toBeVisible();
  const letter = page.getByRole("button", { name: "Lettrer la sélection" });
  await expect(letter).toBeDisabled();
  await page.getByRole("checkbox", { name: /Facture F-12/ }).check();
  await expect(page.getByText(/Écart : 850\s000 GNF D/)).toBeVisible();
  await expect(letter).toBeDisabled();
  await page.getByRole("checkbox", { name: /Règlement F-12/ }).check();
  await expect(letter).toBeEnabled();
  await testInfo.attach("lettrage-premium", { body: await page.screenshot(), contentType: "image/png" });
  await letter.click();

  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await page.goto(`/dossiers/${companyId}/lettrage?compte=411&statut=all`);
  const group = page.getByRole("region", { name: "Lettre A" });
  await expect(group).toContainText("Facture F-12 Hôtel Riviera");
  await expect(group).toContainText("Règlement F-12");

  page.once("dialog", (dialog) => void dialog.accept());
  await group.getByRole("button", { name: "Délettrer" }).click();
  await expect(page.getByRole("checkbox")).toHaveCount(2);
});

test("un compte qui n'est pas de tiers ne se lettre pas", async ({ page }) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Garage de Coyah SARL");
  await page.goto(`/dossiers/${companyId}/lettrage?compte=521`);
  await expect(page.getByRole("alert").filter({ hasText: "classe 4" })).toBeVisible();
});
