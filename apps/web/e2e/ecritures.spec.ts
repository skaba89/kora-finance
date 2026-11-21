import { expect, test } from "@playwright/test";

import { createCompany, fillLine, registerAndLogin } from "./helpers";

test("saisie d'une écriture équilibrée, validation numérotée puis contre-passation", async ({ page }, testInfo) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Pharmacie de Matam SARL");

  await page.getByRole("link", { name: "Écritures", exact: true }).click();
  await expect(page.getByText("Aucune écriture pour ces critères.")).toBeVisible();
  await page.getByRole("link", { name: "Nouvelle écriture" }).click();
  // Next 16 garde la liste (masquée) dans le DOM : sélecteurs par rôle, qui ignorent
  // les éléments masqués.
  await expect(page).toHaveURL(/\/ecritures\/nouvelle$/);

  await page.getByRole("combobox", { name: "Journal" }).selectOption({ label: "VT — Ventes" });
  await page.getByLabel("Date").fill("2026-03-15");
  await page.getByLabel("Libellé", { exact: true }).fill("Ventes comptant du jour");
  await page.getByLabel("Pièce").fill("Z-0315");
  await fillLine(page, 1, "571", "Débit", "1 500 000");
  await fillLine(page, 2, "701", "Crédit", "1 400 000");
  await expect(page.getByTestId("ecart")).toHaveText("100 000 GNF");
  await fillLine(page, 2, "701", "Crédit", "1 500 000");
  await expect(page.getByTestId("ecart")).toHaveText("Équilibrée");

  await page.getByRole("button", { name: "Enregistrer et valider" }).click();
  await expect(page).toHaveURL(new RegExp(`/dossiers/${companyId}/ecritures/[0-9a-f-]{36}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("VT n° 1 — Ventes comptant du jour");
  await expect(page.getByRole("row").filter({ hasText: "Totaux" })).toContainText("1 500 000 GNF");

  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByLabel("Date de la contre-passation").fill("2026-03-16");
  await page.getByRole("button", { name: "Contre-passer" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^VT n° 2 — Contre-passation VT n° 1/);
  await expect(page.getByRole("link", { name: "Contre-passation de l'écriture VT n° 1" })).toBeVisible();

  await page.getByRole("link", { name: "Retour aux écritures" }).click();
  await expect(page.getByRole("link", { name: /Ventes comptant du jour/ })).toHaveCount(2);

  const filters = page.getByRole("search", { name: "Écritures" });
  await filters.getByRole("textbox", { name: "Rechercher", exact: true }).fill("Ventes comptant du jour");
  await filters.getByRole("combobox", { name: "Statut" }).selectOption("POSTED");
  await filters.getByRole("combobox", { name: "Exercices" }).selectOption({ index: 1 });
  await filters.getByRole("combobox", { name: "Taille de page" }).selectOption("25");
  await filters.getByRole("combobox", { name: "Densité du tableau" }).selectOption("compact");
  await filters.getByRole("button", { name: "Filtrer" }).click();
  await expect(page).toHaveURL(/densite=compact/);
  await expect(page.getByRole("link", { name: /Ventes comptant du jour/ })).toHaveCount(2);
  await expect(page.getByRole("table", { name: "Écritures" }).getByRole("columnheader", { name: "Date" })).toHaveAttribute("aria-sort", "descending");
  await expect(page.getByRole("navigation", { name: "Pagination" })).toContainText("1–2 sur 2");
  await testInfo.attach("ecritures-premium", { body: await page.screenshot(), contentType: "image/png" });
  await filters.getByRole("link", { name: "Réinitialiser les filtres" }).click();
  await expect(page).toHaveURL(new RegExp(`/dossiers/${companyId}/ecritures$`));
  await expect(filters.getByRole("combobox", { name: "Taille de page" })).toHaveValue("50");
  await expect(filters.getByRole("combobox", { name: "Densité du tableau" })).toHaveValue("comfortable");
  await expect(filters.getByRole("combobox", { name: "Exercices" })).toHaveValue("");
  await expect(filters.getByRole("combobox", { name: "Statut" })).toHaveValue("");
  await expect(filters.getByRole("textbox", { name: "Rechercher", exact: true })).toHaveValue("");
  await filters.getByRole("combobox", { name: "Taille de page" }).selectOption("100");
  await filters.getByRole("link", { name: "Réinitialiser les filtres" }).click();
  await expect(filters.getByRole("combobox", { name: "Taille de page" })).toHaveValue("50");
});

test("un brouillon déséquilibré s'enregistre mais ne se valide pas", async ({ page }) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Quincaillerie de Kindia SARL");
  await page.goto(`/dossiers/${companyId}/ecritures/nouvelle`);
  await page.getByLabel("Libellé", { exact: true }).fill("Achat de ciment");
  await page.getByLabel("Date").fill("2026-04-02");
  await fillLine(page, 1, "601", "Débit", "800000");
  await fillLine(page, 2, "401", "Crédit", "750000");

  await page.getByRole("button", { name: "Enregistrer et valider" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "déséquilibrée" })).toBeVisible();

  // Le brouillon a bien été enregistré : on le corrige puis on le valide.
  await fillLine(page, 2, "401", "Crédit", "800000");
  await page.getByRole("button", { name: "Enregistrer et valider" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("OD n° 1 — Achat de ciment");

  await page.goto(`/dossiers/${companyId}/ecritures`);
  await expect(page.getByRole("link", { name: "Achat de ciment" })).toHaveCount(1);
});
