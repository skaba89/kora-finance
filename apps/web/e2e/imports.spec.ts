import { expect, test } from "@playwright/test";
import { createCompany, registerAndLogin } from "./helpers";

test("précontrôle d'import équilibré et anomalie sans création d'écriture", async ({ page }) => {
  test.setTimeout(90_000);
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Import comptable Guinée");
  await page.goto(`/dossiers/${companyId}/ecritures`);
  await page.getByRole("link", { name: "Importer des écritures" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Importer des écritures");
  const header = "journal;ecriture;date;compte;libelle;debit;credit\n";
  const first = "VT;1;2026-03-15;571;Vente;1500000;0\n";
  const file = page.getByLabel("Fichier comptable (10 Mio maximum)");
  const submit = page.getByRole("button", { name: "Déposer et précontrôler" });
  await file.setInputFiles({ name: "desequilibre.csv", mimeType: "text/csv", buffer: Buffer.from(header + first) });
  await submit.click();
  await expect(page.getByRole("heading", { name: "Anomalies détectées — corrigez le fichier" })).toBeVisible();
  await expect(page.getByText("unbalanced_entry", { exact: true })).toBeVisible();
  await file.setInputFiles({ name: "equilibre.csv", mimeType: "text/csv", buffer: Buffer.from(header + first + "VT;1;2026-03-15;701;Vente;0;1500000\n") });
  await submit.click();
  await expect(page.getByRole("heading", { name: "Précontrôle réussi — aucune écriture créée" })).toBeVisible();
  await expect(page.getByText(/1\s500\s000 GNF/)).toHaveCount(2);
  await page.goto(`/dossiers/${companyId}/ecritures`);
  await expect(page.getByText("Aucune écriture pour ces critères.")).toBeVisible();
});

test("revue paginée du rapport conservé au-delà de 200 anomalies", async ({ page }) => {
  test.setTimeout(120_000);
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Import volumineux Guinée");
  await page.goto(`/dossiers/${companyId}/ecritures/importer`);
  const header = "journal;ecriture;date;compte;libelle;debit;credit\n";
  const body = Array.from(
    { length: 210 },
    (_, i) => `VT;${i + 1};2026-03-15;571;Vente;1000;0\n`,
  ).join("");
  const file = page.getByLabel("Fichier comptable (10 Mio maximum)");
  await file.setInputFiles({ name: "volume.csv", mimeType: "text/csv", buffer: Buffer.from(header + body) });
  const submit = page.getByRole("button", { name: "Déposer et précontrôler" });
  await submit.click();
  await expect(page.getByRole("heading", { name: "Anomalies détectées — corrigez le fichier" })).toBeVisible();
  await expect(page.getByText(/Seules les 200 premières anomalies/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "200", exact: true })).toBeVisible();
  const more = page.getByRole("button", { name: /Afficher plus d.anomalies \(10\)/ });
  await more.click();
  await expect(page.getByRole("cell", { name: "211", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Afficher plus d.anomalies/ })).toHaveCount(0);
});

test("confirmation d'un import : brouillons créés dans le journal, jamais validés", async ({ page }) => {
  test.setTimeout(120_000);
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Import confirmé Guinée");
  await page.goto(`/dossiers/${companyId}/ecritures/importer`);
  const header = "journal;ecriture;date;compte;libelle;debit;credit\n";
  const lignes =
    "VT;AC-2026-101;2026-03-15;571;Vente comptant;1500000;0\n" +
    "VT;AC-2026-101;2026-03-15;701;Vente comptant;0;1500000\n" +
    "VT;AC-2026-102;2026-03-20;571;Vente crédit;3000000;0\n" +
    "VT;AC-2026-102;2026-03-20;411;Vente crédit;0;3000000\n";
  const file = page.getByLabel("Fichier comptable (10 Mio maximum)");
  const submit = page.getByRole("button", { name: "Déposer et précontrôler" });
  await file.setInputFiles({ name: "ventes.csv", mimeType: "text/csv", buffer: Buffer.from(header + lignes) });
  await submit.click();
  await expect(page.getByRole("heading", { name: "Précontrôle réussi — aucune écriture créée" })).toBeVisible();
  // Le bouton n'apparaît que pour un précontrôle vert ; rien n'est validé automatiquement.
  const confirmer = page.getByRole("button", { name: "Comptabiliser en brouillons" });
  await expect(confirmer).toBeVisible();
  await expect(page.getByText(/Aucune écriture n.est validée automatiquement/)).toBeVisible();
  await confirmer.click();
  await expect(page.getByRole("heading", { name: "Import comptabilisé en brouillons" })).toBeVisible();
  await expect(page.getByText(/Confirmé le/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Comptabiliser en brouillons" })).toHaveCount(0);
  // Les brouillons figurent dans le journal ; rien n'a été validé automatiquement.
  await page.getByRole("link", { name: "Voir les écritures" }).click();
  await expect(page.getByText("Vente comptant")).toHaveCount(1);
  await expect(page.getByText("Vente crédit")).toHaveCount(1);
  await page.goto(`/dossiers/${companyId}/ecritures?statut=DRAFT`);
  await expect(page.getByText("Vente comptant")).toHaveCount(1);
  await page.goto(`/dossiers/${companyId}/ecritures?statut=POSTED`);
  await expect(page.getByText("Aucune écriture pour ces critères.")).toBeVisible();
});
