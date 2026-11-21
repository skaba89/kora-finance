import { expect, test } from "@playwright/test";

import { createCompany, registerAndLogin, uniqueEmail } from "./helpers";

test("créer une facture depuis l'accueil et consulter le recouvrement", async ({ page }, testInfo) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Commerce de Madina");
  const base = `/dossiers/${companyId}`;

  await page.getByRole("link", { name: "Créer une facture" }).click();
  await page.getByRole("link", { name: "Ouvrir la fiche tiers" }).click();
  await page.getByRole("textbox", { name: "Nom / raison sociale" }).fill("Atelier du Kaloum");
  await page.getByRole("checkbox", { name: "Client", exact: true }).check();
  await page.getByRole("button", { name: "Enregistrer", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: "Atelier du Kaloum" })).toBeVisible();

  await page.goto(base);
  await page.getByRole("link", { name: "Créer une facture" }).click();
  await expect(page.getByRole("combobox", { name: "Type", exact: true })).toHaveValue("invoice");
  await page.getByRole("combobox", { name: "Client", exact: true }).selectOption({ label: "Atelier du Kaloum" });
  const firstLine = page.getByRole("group", { name: "Ligne 1", exact: true });
  await firstLine.getByLabel("Désignation").fill("Prestation");
  await firstLine.getByLabel("Quantité").fill("1");
  await firstLine.getByLabel("Prix unitaire HT (unités)").fill("850000");
  await page.getByRole("button", { name: "Créer le brouillon" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Modifications enregistrées." })).toBeVisible();

  const sections = page.getByRole("navigation", { name: "Ventes", exact: true });
  await sections.getByRole("link", { name: "Documents" }).click();
  const row = page.getByRole("row").filter({ hasText: "Atelier du Kaloum" });
  await expect(row).toContainText("Brouillon");
  await expect(row).toContainText(/850\s000 GNF/);
  await expect(page.getByRole("combobox", { name: "Taille de page" })).toHaveValue("100");
  await page.getByRole("combobox", { name: "Taille de page" }).selectOption("25");
  await page.getByRole("combobox", { name: "Densité du tableau" }).selectOption("compact");
  await page.getByRole("button", { name: "Filtrer", exact: true }).click();
  await expect(page).toHaveURL(/taille=25/);
  await expect(page).toHaveURL(/densite=compact/);
  await expect(row).toContainText(/850\s000 GNF/);
  await testInfo.attach("ventes-premium", { body: await page.screenshot(), contentType: "image/png" });
  await page.getByRole("link", { name: "Réinitialiser les filtres" }).click();
  await expect(page.getByRole("combobox", { name: "Taille de page" })).toHaveValue("100");
  await expect(page.getByRole("combobox", { name: "Densité du tableau" })).toHaveValue("comfortable");
  await sections.getByRole("link", { name: "Recouvrement" }).click();
  await expect(page).toHaveURL(/vue=recouvrement$/);
  await expect(page.getByText("Relances de factures échues", { exact: true })).toBeVisible();
  await testInfo.attach("recouvrement-premium", { body: await page.screenshot(), contentType: "image/png" });
  await page.reload();
  await expect(sections.getByRole("link", { name: "Recouvrement" })).toHaveAttribute("aria-current", "page");
  await sections.getByRole("link", { name: "Encaissements" }).click();
  await expect(page.getByText("Règlements encaissés", { exact: true })).toBeVisible();
});

test("un lecteur consulte les ventes et le lien de création revient aux documents", async ({ page, browser, baseURL }) => {
  const readerContext = await browser.newContext({ baseURL });
  try {
    const reader = await readerContext.newPage();
    const email = await registerAndLogin(reader, uniqueEmail("lecteur"), "Lecteur Madina");
    await registerAndLogin(page);
    const id = await createCompany(page, "Dossier du lecteur");
    await page.goto(`/dossiers/${id}/parametres/utilisateurs`);
    const add = page.locator("form").filter({ has: page.getByRole("button", { name: "Ajouter", exact: true }) });
    await add.getByLabel("Email").fill(email);
    await add.getByRole("combobox").selectOption("PME_LECTEUR");
    await add.getByRole("button", { name: "Ajouter" }).click();
    await expect(page.getByRole("cell", { name: /Lecteur Madina/ })).toBeVisible();

    await reader.goto(`/dossiers/${id}/ventes?vue=nouveau`);
    const nav = reader.getByRole("navigation", { name: "Ventes", exact: true });
    await expect(nav.getByRole("link", { name: "Documents" })).toHaveAttribute("aria-current", "page");
    await expect(reader.getByRole("link", { name: "Créer une facture" })).toHaveCount(0);
    await expect(reader.getByRole("button", { name: "Créer le brouillon" })).toHaveCount(0);
  } finally {
    await readerContext.close();
  }
});
