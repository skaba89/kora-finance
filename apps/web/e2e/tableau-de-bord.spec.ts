import { expect, test } from "@playwright/test";

import { createCompany, registerAndLogin } from "./helpers";

test("tableau de bord : raccourcis, indicateurs après une vente et une dépense, accueil direct", async ({ page }, testInfo) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Superette de Taouyah SARL");

  // Dossier neuf : aucune donnée inventée, des raccourcis pour commencer.
  await expect(page.getByText("Aucune écriture pour l'instant")).toBeVisible();
  await expect(page.getByText(/La saisie des écritures.*arrivent avec les prochaines étapes/)).toHaveCount(0);
  const today = new Date().toISOString().slice(0, 10);

  await page.getByRole("link", { name: "J'ai vendu et j'ai été payé" }).click();
  await page.getByLabel("Date").fill(today);
  await page.getByRole("textbox", { name: "Montant" }).fill("1 180 000");
  await page.getByRole("combobox", { name: "Nature de la recette" }).selectOption({ label: "Vente de marchandises (701)" });
  await page.getByRole("combobox", { name: "Encaissé sur" }).selectOption({ label: "571 — Caisse siège social" });
  await page.getByRole("checkbox", { name: /Le montant comprend de la TVA/ }).check();
  await page.getByRole("button", { name: "Enregistrer et valider" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^CA n° 1/);

  await page.goto(`/dossiers/${companyId}`);
  await page.getByRole("link", { name: "J'ai payé une dépense" }).click();
  await page.getByLabel("Date").fill(today);
  await page.getByRole("textbox", { name: "Montant" }).fill("200000");
  await page.getByRole("combobox", { name: "Nature de la dépense" }).selectOption({ label: "Loyer et charges locatives (622)" });
  await page.getByRole("combobox", { name: "Payé depuis" }).selectOption({ label: "571 — Caisse siège social" });
  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Modifier le brouillon");

  await page.goto(`/dossiers/${companyId}`);
  const tiles = page.getByRole("region", { name: "Tableau de bord" });
  // Le brouillon n'entre dans aucun indicateur : il est seulement signalé.
  await expect(tiles.getByText("Trésorerie disponible").locator("..")).toContainText(/1\s180\s000 GNF/);
  await expect(tiles.getByText("Chiffre d'affaires — Ce mois-ci").locator("..")).toContainText(/1\s000\s000 GNF/);
  await expect(tiles.getByText("Charges — Ce mois-ci").locator("..")).toContainText(/0 GNF/);
  await expect(page.getByRole("status").filter({ hasText: "1 brouillon(s) à relire et valider." })).toBeVisible();
  await expect(page.getByRole("img", { name: "Chiffre d'affaires et charges par mois" })).toBeVisible();
  await page.getByText("Voir les chiffres").click();
  await expect(page.getByRole("row").filter({ hasText: "1 000 000" }).first()).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "Caisse siège social" })).toContainText(/1\s180\s000 GNF/);

  // Les six résolutions cibles sont réparties entre Chromium et Pixel 5.
  const widths = testInfo.project.name === "mobile" ? [360, 390, 768] : [1024, 1440, 1920];
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    await expect(tiles.getByText("Trésorerie disponible")).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
    await testInfo.attach(`dashboard-${width}`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
  }

  // Un seul dossier : l'accueil mène directement à son tableau de bord.
  await page.goto("/dossiers");
  await expect(page).toHaveURL(new RegExp(`/dossiers/${companyId}$`));
  await page.getByRole("link", { name: "Changer de dossier" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes dossiers" })).toBeVisible();
});
