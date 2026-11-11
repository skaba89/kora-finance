import { expect, type Page, test } from "@playwright/test";

import { createCompany, registerAndLogin } from "./helpers";

const CSV_RELEVE =
  "Date;Libellé;Débit;Crédit\r\n01/03/2026;Virement client SOTRACOM;;1500000\r\n";

/** Accepte toutes les boîtes de confirmation (window.confirm des actions en ligne). */
function acceptDialogs(page: Page) {
  page.on("dialog", (dialog) => void dialog.accept());
}

test("rapprochement bancaire : proposition assistée, confirmation humaine, réversible", async ({
  page,
}) => {
  acceptDialogs(page);
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Sotracom SARL");
  await page.goto(`/dossiers/${companyId}/tresorerie`);
  await expect(page.getByRole("heading", { name: "Trésorerie" })).toBeVisible();

  // --- Compte financier banque (liée au 521) ---
  const accountForm = page.locator("form").filter({ has: page.getByLabel("Nom du compte") });
  await accountForm.getByLabel("Nom du compte").fill("BCRG principal");
  await accountForm.getByLabel("Type de mouvement").selectOption({ label: "Banque" });
  await accountForm
    .getByLabel("Compte comptable lié")
    .selectOption({ label: "521 — Banques locales" });
  await accountForm.getByRole("button", { name: "Créer" }).click();
  await expect(page.getByRole("cell", { name: "BCRG principal" })).toBeVisible();

  // --- Mouvement correspondant : dépôt du 01/03/2026, 1 500 000 GNF ---
  // (les deux formulaires de la page partagent l'id « kind » : on cible le premier
  // select du formulaire de mouvement, le type y est la première colonne)
  const movementForm = page
    .locator("form")
    .filter({ has: page.getByLabel("Montant (GNF)", { exact: true }) });
  await movementForm.locator("select").first().selectOption({ label: "Dépôt" });
  await movementForm.getByLabel("Montant (GNF)", { exact: true }).fill("1500000");
  await movementForm.getByLabel("Date", { exact: true }).fill("2026-03-01");
  await movementForm.getByLabel("Libellé", { exact: true }).fill("Virement client SOTRACOM");
  await movementForm
    .getByLabel("Compte de contrepartie")
    .selectOption({ label: "101 — Capital social" });
  await movementForm.getByRole("button", { name: "Mouvement", exact: true }).click();
  // La colonne libellé est masquée sur mobile : on vérifie le montant, toujours visible.
  await expect(page.getByRole("cell", { name: "1 500 000 GNF" }).first()).toBeVisible();

  // --- Import du relevé bancaire contenant l'opération ---
  await page.setInputFiles("#statement-file", {
    name: "releve-bcrg-03.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(CSV_RELEVE, "utf8"),
  });
  await page.getByRole("button", { name: "Importer" }).click();
  await expect(page.getByText("Relevé importé : 1 lignes")).toBeVisible();

  // --- Ouvrir les lignes du relevé ---
  await page.getByRole("link", { name: "Voir les lignes" }).click();
  const ligne = page.getByRole("row").filter({ hasText: "Virement client SOTRACOM" });
  await expect(ligne).toBeVisible();
  await expect(ligne.getByText("À rapprocher")).toBeVisible();

  // --- Propositions : le moteur propose, l'humain confirme ---
  await ligne.getByRole("link", { name: "Rapprocher" }).click();
  const panneau = page.getByRole("region", { name: /Candidats proposés pour la ligne n°1/ });
  await expect(panneau).toBeVisible();
  const candidat = panneau.getByRole("row").filter({ hasText: "Virement client SOTRACOM" });
  await expect(candidat).toBeVisible();

  await candidat.getByRole("button", { name: "Confirmer" }).click();
  // La ligne passe en MATCHED, le panneau disparaît (la ligne n'est plus à rapprocher).
  await expect(ligne.getByText("Rapprochée")).toBeVisible();
  await expect(panneau).not.toBeVisible();

  // --- Réversibilité : le dé-rapprochement remet la ligne en attente ---
  await ligne.getByRole("button", { name: "Retirer" }).click();
  await expect(ligne.getByText("À rapprocher")).toBeVisible();
  await ligne.getByRole("link", { name: "Rapprocher" }).click();
  const panneauRetour = page.getByRole("region", { name: /Candidats proposés pour la ligne n°1/ });
  await expect(
    panneauRetour.getByRole("row").filter({ hasText: "Virement client SOTRACOM" }),
  ).toBeVisible();
});
