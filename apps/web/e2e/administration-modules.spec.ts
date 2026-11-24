import { expect, test } from "@playwright/test";

import { createCompany, registerAndLogin, uniqueEmail } from "./helpers";

test("un dirigeant ordinaire ne peut pas administrer les modules plateforme", async ({ page }) => {
  await registerAndLogin(page, uniqueEmail("modules"));
  const companyId = await createCompany(page, "Recette modules SARL");

  // Le dirigeant possède ses droits métier mais pas les droits plateforme.
  await expect(page.getByRole("link", { name: "Administration", exact: true })).toHaveCount(0);
  await page.goto("/administration");
  await expect(page.getByRole("heading", { name: "Page introuvable" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Administration Kora Finance" })).toHaveCount(0);
  await page.goto("/administration/modules");
  await expect(page.getByRole("heading", { name: "Page introuvable" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Administration des modules" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Désactiver", exact: true })).toHaveCount(0);

  await page.goto("/administration/licences");
  await expect(page.getByRole("heading", { name: "Page introuvable" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Licences commerciales" })).toHaveCount(0);

  // Le refus plateforme ne retire pas les permissions dans son propre dossier.
  await page.goto(`/dossiers/${companyId}`);
  await expect(page.getByRole("heading", { level: 1, name: "Recette modules SARL" })).toBeVisible();
});
