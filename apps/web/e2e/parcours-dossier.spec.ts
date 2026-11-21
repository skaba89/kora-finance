import { expect, test } from "@playwright/test";

import { createCompany, registerAndLogin } from "./helpers";

test("inscription, création d'un dossier et paramétrage comptable", async ({ page }, testInfo) => {
  await registerAndLogin(page);
  await expect(page.getByText("Vous n'avez encore aucun dossier.")).toBeVisible();

  await createCompany(page, "Boulangerie de Kaloum SARL");
  const setup = page.getByRole("list").filter({ hasText: "Créer un exercice comptable" });
  await expect(setup).toContainText("Vérifier les taux de taxes auprès de la DGI — 2 taux à vérifier");

  // Plan comptable SYSCOHADA préchargé et recherche.
  await page.getByRole("link", { name: "Plan comptable" }).click();
  await expect(page.getByText("1–50 sur 520")).toBeVisible();
  await page.getByRole("combobox", { name: "Taille de page" }).selectOption("25");
  await page.getByRole("combobox", { name: "Densité du tableau" }).selectOption("compact");
  await page.getByRole("button", { name: "Rechercher" }).click();
  await expect(page.getByText("1–25 sur 520")).toBeVisible();
  await page.getByRole("link", { name: "Suivant", exact: true }).click();
  await expect(page.getByText("26–50 sur 520")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Densité du tableau" })).toHaveValue("compact");
  await testInfo.attach("plan-comptable-premium", { body: await page.screenshot(), contentType: "image/png" });
  await page.getByRole("textbox", { name: "Rechercher", exact: true }).fill("téléphone portable");
  await page.getByRole("button", { name: "Rechercher" }).click();
  await expect(page.getByRole("cell", { name: "552", exact: true })).toBeVisible();

  // Sous-compte Mobile Money.
  await page.getByLabel("Numéro").fill("5521");
  await page.getByLabel("Libellé").fill("Orange Money – compte principal");
  await page.getByRole("button", { name: "Créer", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Modifications enregistrées." })).toBeVisible();
  await page.getByRole("textbox", { name: "Rechercher", exact: true }).fill("5521");
  await page.getByRole("button", { name: "Rechercher" }).click();
  await expect(page.getByRole("cell", { name: "Orange Money – compte principal" })).toBeVisible();

  // Confirmation du taux de TVA après vérification auprès de la DGI.
  await page.getByRole("link", { name: "Taxes" }).click();
  const tvaRow = page.getByRole("row").filter({ hasText: "TVA_NORMAL" });
  await expect(tvaRow).toContainText("18 %");
  await tvaRow.getByRole("button", { name: "Confirmer ce taux" }).click();
  await expect(tvaRow.getByText("Vérifié")).toBeVisible();

  // Exercice suivant, puis refus d'un chevauchement.
  await page.getByRole("link", { name: "Exercices" }).click();
  await page.getByLabel("Début").fill("2027-01-01");
  await page.getByLabel("Fin").fill("2027-12-31");
  await page.getByRole("button", { name: "Ajouter" }).click();
  await expect(page.getByRole("region", { name: /^01\/01\/2027/ })).toBeVisible();
  await page.getByLabel("Début").fill("2027-06-01");
  await page.getByLabel("Fin").fill("2028-05-31");
  await page.getByRole("button", { name: "Ajouter" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "chevauche" })).toBeVisible();

  // Journal d'audit : toutes ces actions sont tracées et la chaîne est intègre.
  await page.getByRole("link", { name: "Journal d'audit" }).click();
  await expect(page.getByRole("cell", { name: "Création d'un compte" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Confirmation d'un taux de taxe" })).toBeVisible();
  await page.getByRole("button", { name: "Vérifier l'intégrité" }).click();
  await expect(page.getByRole("status")).toContainText("Chaîne intègre");

  // Déconnexion.
  await page.getByRole("button", { name: "Se déconnecter" }).click();
  await expect(page).toHaveURL(/\/connexion\?deconnecte=1/);
  await page.goto("/dossiers");
  await expect(page).toHaveURL(/\/connexion/);
});

test("un comptable invité n'a pas les droits du dirigeant", async ({ browser }) => {
  const owner = await browser.newPage();
  const accountant = await browser.newPage({ storageState: undefined });
  await registerAndLogin(owner);
  const companyId = await createCompany(owner, "Transports Fria SA");

  const accountantEmail = await registerAndLogin(accountant, undefined, "Kadiatou Camara");
  await owner.goto(`/dossiers/${companyId}/parametres/utilisateurs`);
  await owner.getByLabel("Email").fill(accountantEmail);
  await owner.getByRole("button", { name: "Ajouter" }).click();
  // Le nom reste accessible même lorsque la colonne email est masquée.
  await expect(owner.getByRole("cell", { name: "Kadiatou Camara" })).toBeVisible();

  await accountant.goto(`/dossiers/${companyId}/parametres/entreprise`);
  // Lecture seule : pas de formulaire de modification de la fiche.
  await expect(accountant.locator("dl").getByText("Transports Fria SA")).toBeVisible();
  await expect(accountant.getByRole("button", { name: "Enregistrer" })).toHaveCount(0);
  // Gestion des utilisateurs en lecture seule : la liste est visible, sans actions.
  await expect(accountant.getByRole("link", { name: "Utilisateurs" })).toBeVisible();
  await accountant.goto(`/dossiers/${companyId}/parametres/utilisateurs`);
  await expect(accountant.getByRole("button", { name: "Retirer" })).toHaveCount(0);
});
