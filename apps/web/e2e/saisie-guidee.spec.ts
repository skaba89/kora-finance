import { expect, test } from "@playwright/test";

import { createCompany, registerAndLogin } from "./helpers";

test("saisie guidée : vente encaissée avec TVA, aperçu puis validation", async ({ page }) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Boutique de Madina SARL");
  await page.getByRole("link", { name: "Saisie guidée" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Saisie guidée");
  await page.getByRole("link", { name: /J'ai vendu et j'ai été payé/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("J'ai vendu et j'ai été payé");

  await page.getByLabel("Date").fill("2026-06-10");
  await page.getByRole("textbox", { name: "Montant" }).fill("1 180 000");
  await page.getByRole("combobox", { name: "Nature de la recette" }).selectOption({ label: "Vente de marchandises (701)" });
  await page.getByRole("combobox", { name: "Encaissé sur" }).selectOption({ label: "571 — Caisse siège social" });
  await page.getByRole("checkbox", { name: /Le montant comprend de la TVA \(18 %\)/ }).check();

  await page.getByRole("button", { name: "Voir l'écriture" }).click();
  const preview = page.getByRole("region", { name: "Écriture qui sera enregistrée" });
  await expect(preview).toContainText("Journal CA — Caisse · Vente encaissée — Vente de marchandises");
  await expect(preview.getByRole("note")).toContainText("n'a pas encore été vérifié auprès de la DGI");
  await expect(preview.getByRole("row").filter({ hasText: "571" })).toContainText(/1\s180\s000 GNF/);
  await expect(preview.getByRole("row").filter({ hasText: "701" })).toContainText(/1\s000\s000 GNF/);
  await expect(preview.getByRole("row").filter({ hasText: "4431" })).toContainText(/180\s000 GNF/);
  // L'aperçu ne vide pas le formulaire.
  await expect(page.getByRole("textbox", { name: "Montant" })).toHaveValue("1 180 000");

  await page.getByRole("button", { name: "Enregistrer et valider" }).click();
  await expect(page).toHaveURL(new RegExp(`/dossiers/${companyId}/ecritures/[0-9a-f-]{36}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("CA n° 1 — Vente encaissée — Vente de marchandises");
  await expect(page.getByRole("row").filter({ hasText: "Totaux" })).toContainText(/1\s180\s000 GNF/);
});

test("saisie guidée : facture fournisseur en brouillon et choix incohérent refusé", async ({ page }) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Atelier de Coyah SARL");

  await page.goto(`/dossiers/${companyId}/saisie-guidee?operation=FACTURE_FOURNISSEUR`);
  await page.getByLabel("Date").fill("2026-06-12");
  await page.getByRole("textbox", { name: "Montant" }).fill("3000000");
  await page.getByRole("combobox", { name: "Nature de la dépense" }).selectOption({ label: "Loyer et charges locatives (622)" });
  await expect(page.getByRole("combobox", { name: "Compte fournisseur" })).toHaveValue(/[0-9a-f-]{36}/);
  await page.getByRole("textbox", { name: "N° de facture" }).fill("LOYER-06");
  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Modifier le brouillon");

  await page.goto(`/dossiers/${companyId}/saisie-guidee?operation=VIREMENT_INTERNE`);
  await page.getByLabel("Date").fill("2026-06-12");
  await page.getByRole("textbox", { name: "Montant" }).fill("500000");
  await page.getByRole("combobox", { name: "Depuis" }).selectOption({ label: "571 — Caisse siège social" });
  await page.getByRole("combobox", { name: "Vers" }).selectOption({ label: "571 — Caisse siège social" });
  await page.getByRole("button", { name: "Voir l'écriture" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "doivent être différents" })).toBeVisible();

  await page.getByRole("combobox", { name: "Vers" }).selectOption({ label: "521 — Banques locales" });
  await page.getByRole("button", { name: "Voir l'écriture" }).click();
  await expect(page.getByRole("region", { name: "Écriture qui sera enregistrée" })).toContainText("Journal CA — Caisse");
});
