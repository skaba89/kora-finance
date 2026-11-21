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
}, testInfo) => {
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
  await expect(page.getByRole("link", { name: "BCRG principal" })).toHaveAttribute("aria-current", "page");

  // --- Mouvement correspondant : dépôt du 01/03/2026, 1 500 000 GNF ---
  const movementForm = page
    .locator("form")
    .filter({ has: page.getByRole("button", { name: "Mouvement", exact: true }) });
  await movementForm.getByLabel("Type de mouvement").selectOption({ label: "Dépôt" });
  await movementForm.getByLabel("Montant (GNF)", { exact: true }).fill("1500000");
  await movementForm.getByLabel("Date", { exact: true }).fill("2026-03-01");
  await movementForm.getByLabel("Libellé", { exact: true }).fill("Virement client SOTRACOM");
  await movementForm
    .getByLabel("Compte de contrepartie")
    .selectOption({ label: "101 — Capital social" });
  await movementForm.getByRole("button", { name: "Mouvement", exact: true }).click();
  await expect(page.getByRole("cell", { name: "1 500 000 GNF" }).first()).toBeVisible();
  await expect(page.getByRole("table", { name: "Mouvements", exact: true }).getByText("Virement client SOTRACOM", { exact: true }).filter({ visible: true })).toBeVisible();

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
  const ligne = page.getByRole("table", { name: "releve-bcrg-03.csv" }).getByRole("row").filter({ hasText: "Virement client SOTRACOM" });
  await expect(ligne).toBeVisible();
  await expect(ligne.getByText("À rapprocher")).toBeVisible();
  await testInfo.attach("rapprochement-avant", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });

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
  await testInfo.attach("rapprochement-confirme", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });

  // --- Réversibilité : le dé-rapprochement remet la ligne en attente ---
  await ligne.getByRole("button", { name: "Retirer" }).click();
  await expect(ligne.getByText("À rapprocher")).toBeVisible();
  await ligne.getByRole("link", { name: "Rapprocher" }).click();
  const panneauRetour = page.getByRole("region", { name: /Candidats proposés pour la ligne n°1/ });
  await expect(
    panneauRetour.getByRole("row").filter({ hasText: "Virement client SOTRACOM" }),
  ).toBeVisible();
});
