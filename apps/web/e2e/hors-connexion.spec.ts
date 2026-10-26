import { type BrowserContext, expect, type Page, test } from "@playwright/test";

import { createCompany, fillLine, registerAndLogin } from "./helpers";

// Service worker, IndexedDB chiffrée et WebCrypto exigent un contexte sécurisé : la pile
// E2E est servie en http://web:3000, que Chromium traite ici comme sécurisée (HTTPS en
// production). Le drapeau n'est pris en compte que par le Chromium complet (canal
// « chromium »), pas par le shell headless utilisé par défaut.
const origin = new URL(process.env.E2E_BASE_URL ?? "http://localhost:3100").origin;
test.use({ channel: "chromium", launchOptions: { args: [`--unsafely-treat-insecure-origin-as-secure=${origin}`] } });

/** Prépare l'appareil pour le dossier et attend que la page hors connexion soit en cache. */
async function prepareDevice(page: Page, companyId: string) {
  await page.goto(`/dossiers/${companyId}/hors-connexion`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Saisie hors connexion");
  await expect(page.getByTestId("etat-appareil")).toHaveText(/pas encore prêt/);
  await page.getByRole("button", { name: "Préparer cet appareil" }).click();
  await expect(page.getByTestId("etat-appareil")).toHaveText(/Appareil prêt : données du .*, valables jusqu'au/);
  await page.waitForFunction(async () => {
    await navigator.serviceWorker.ready;
    return Boolean(await caches.match("/hors-connexion/saisie"));
  });
}

async function goOffline(context: BrowserContext, page: Page) {
  await context.setOffline(true);
  await page.goto("/hors-connexion/saisie");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Saisie hors connexion");
  await expect(page.getByRole("combobox", { name: "Dossier" })).toBeVisible();
}

function queued(page: Page, label: string) {
  return page.getByRole("list", { name: "Saisies faites hors connexion" }).getByRole("listitem").filter({ hasText: label });
}

test("saisie sans réseau, synchronisation en brouillons, correction d'un refus puis validation", async ({
  page,
  context,
}) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Épicerie de Kaloum SARL");
  await page.getByRole("link", { name: "Hors connexion" }).click();
  await prepareDevice(page, companyId);

  await goOffline(context, page);
  // Saisie libre.
  await page.getByLabel("Date").fill("2026-06-08");
  await page.getByLabel("Libellé", { exact: true }).fill("Achat de riz au marché");
  await fillLine(page, 1, "601", "Débit", "2 400 000");
  await fillLine(page, 2, "571", "Crédit", "2 400 000");
  await expect(page.getByTestId("ecart")).toHaveText("Équilibrée");
  await page.getByRole("button", { name: "Enregistrer sur l'appareil" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saisie enregistrée sur l'appareil" })).toBeVisible();
  await expect(queued(page, "Achat de riz au marché")).toContainText("En attente");
  // Le formulaire repart à vide pour la saisie suivante.
  await expect(page.getByLabel("Libellé", { exact: true })).toHaveValue("");

  // Saisie guidée : pas d'aperçu hors connexion, la TVA sera calculée par le serveur.
  await page.getByRole("combobox", { name: "Type de saisie" }).selectOption({ label: "Saisie guidée" });
  await page.getByRole("combobox", { name: "Opération" }).selectOption({ label: "J'ai vendu et j'ai été payé" });
  await expect(page.getByRole("button", { name: "Voir l'écriture" })).toHaveCount(0);
  await page.getByLabel("Date").fill("2026-06-09");
  await page.getByRole("textbox", { name: "Montant" }).fill("1 180 000");
  await page.getByRole("combobox", { name: "Nature de la recette" }).selectOption({ label: "Vente de marchandises (701)" });
  await page.getByRole("combobox", { name: "Encaissé sur" }).selectOption({ label: "571 — Caisse siège social" });
  await page.getByRole("checkbox", { name: /Le montant comprend de la TVA/ }).check();
  await page.getByRole("textbox", { name: "Libellé (facultatif)" }).fill("Ventes du samedi");
  await page.getByRole("button", { name: "Enregistrer sur l'appareil" }).click();
  await expect(queued(page, "Ventes du samedi")).toContainText("En attente");

  // Date hors exercice : signalée tout de suite, refusée par le serveur à la synchronisation.
  await page.getByRole("combobox", { name: "Type de saisie" }).selectOption({ label: "Saisie libre" });
  await page.getByLabel("Date").fill("2024-01-15");
  await page.getByLabel("Libellé", { exact: true }).fill("Transport de marchandises");
  await fillLine(page, 1, "601", "Débit", "300 000");
  await fillLine(page, 2, "571", "Crédit", "300 000");
  await page.getByRole("button", { name: "Enregistrer sur l'appareil" }).click();
  await expect(page.getByRole("status").filter({ hasText: "n'appartient à aucun exercice ouvert" })).toBeVisible();

  // Retour du réseau : toute page de Kora synchronise.
  await context.setOffline(false);
  await page.goto(`/dossiers/${companyId}/hors-connexion`);
  await expect(queued(page, "Achat de riz au marché")).toContainText("Brouillon créé");
  await expect(queued(page, "Ventes du samedi")).toContainText("Brouillon créé");
  const rejected = queued(page, "Transport de marchandises");
  await expect(rejected).toContainText("Refusée");
  await expect(rejected.getByRole("alert")).toContainText("Aucun exercice ne couvre le 15/01/2024");

  // Correction de la saisie refusée, puis nouvelle synchronisation.
  await rejected.getByRole("link", { name: "Corriger" }).click();
  await expect(page.getByText("Correction d'une saisie refusée")).toBeVisible();
  await expect(page.getByLabel("Libellé", { exact: true })).toHaveValue("Transport de marchandises");
  await page.getByLabel("Date").fill("2026-06-10");
  await page.getByRole("button", { name: "Enregistrer sur l'appareil" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saisie enregistrée sur l'appareil" })).toBeVisible();
  await page.goto(`/dossiers/${companyId}/hors-connexion`);
  await expect(queued(page, "Transport de marchandises")).toContainText("Brouillon créé");

  // Trois brouillons exactement : aucun doublon malgré plusieurs synchronisations.
  await page.goto(`/dossiers/${companyId}/ecritures`);
  for (const label of [/Achat de riz au marché/, /Transport de marchandises/, /Ventes du samedi/]) {
    await expect(page.getByRole("link", { name: label })).toHaveCount(1);
  }

  // Les brouillons se valident en ligne, comme les autres.
  await page.goto(`/dossiers/${companyId}/hors-connexion`);
  await queued(page, "Ventes du samedi").getByRole("link", { name: "Ouvrir le brouillon" }).click();
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Valider", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^CA n° 1 — Ventes du samedi/);
  await expect(page.getByRole("row").filter({ hasText: "4431" })).toContainText(/180\s000 GNF/);
});

test("la déconnexion prévient des saisies non synchronisées puis efface l'appareil", async ({ page, context }) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Boulangerie de Dixinn SARL");
  await prepareDevice(page, companyId);

  // Saisie hors exercice : elle restera refusée, donc non synchronisée.
  await goOffline(context, page);
  await page.getByLabel("Date").fill("2024-02-01");
  await page.getByLabel("Libellé", { exact: true }).fill("Farine de janvier");
  await fillLine(page, 1, "601", "Débit", "500 000");
  await fillLine(page, 2, "571", "Crédit", "500 000");
  await page.getByRole("button", { name: "Enregistrer sur l'appareil" }).click();
  await expect(queued(page, "Farine de janvier")).toContainText("En attente");
  await context.setOffline(false);

  await page.goto(`/dossiers/${companyId}/hors-connexion`);
  await expect(queued(page, "Farine de janvier")).toContainText("Refusée");
  await expect(page.getByRole("status").filter({ hasText: "saisie(s) hors connexion refusée(s)" })).toBeVisible();

  // Renoncer : la personne reste connectée, la saisie est conservée.
  page.once("dialog", (dialog) => {
    expect(dialog.message()).toContain("1 saisie(s) faite(s) hors connexion ne sont pas encore devenues des brouillons");
    void dialog.dismiss();
  });
  await page.getByRole("button", { name: "Se déconnecter" }).click();
  await expect(queued(page, "Farine de janvier")).toBeVisible();

  // Confirmer : déconnexion et effacement de tout ce que l'appareil conservait.
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Se déconnecter" }).click();
  await expect(page).toHaveURL(/\/connexion\?deconnecte=1/);
  await page.goto("/hors-connexion/saisie");
  await expect(page.getByRole("alert").filter({ hasText: "Aucun dossier n'est prêt sur cet appareil" })).toBeVisible();
});
