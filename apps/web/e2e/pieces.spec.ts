import { deflateSync } from "node:zlib";

import { expect, type Page, test } from "@playwright/test";

import { createCompany, fillLine, registerAndLogin } from "./helpers";

const PDF = Buffer.from("%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n");

function crc32(data: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc ^= byte;
    for (let k = 0; k < 8; k++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

/** Photo « lourde » (bruit aléatoire, incompressible) : PNG valide d'environ 1 Mo. */
function noisyPng(width: number, height: number): Buffer {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 2, 0, 0, 0], 8); // 8 bits, RVB
  const rows = Buffer.alloc((width * 3 + 1) * height);
  for (let i = 0; i < rows.length; i++) rows[i] = i % (width * 3 + 1) === 0 ? 0 : Math.floor(Math.random() * 256);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

async function attach(page: Page, name: string, mimeType: string, buffer: Buffer) {
  const section = page.getByRole("region", { name: "Pièces justificatives" });
  await section.getByLabel("Fichier").setInputFiles({ name, mimeType, buffer });
  await section.getByRole("button", { name: "Joindre" }).click();
}

test("pièces justificatives : envoi, consultation, retrait, conservation après validation", async ({ page }) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Imprimerie de Dixinn SARL");
  await page.goto(`/dossiers/${companyId}/ecritures/nouvelle`);
  await page.getByRole("combobox", { name: "Journal" }).selectOption({ label: "AC — Achats" });
  await page.getByLabel("Date").fill("2026-05-04");
  await page.getByRole("textbox", { name: "Libellé", exact: true }).fill("Achat de papier");
  await fillLine(page, 1, "601", "Débit", "2 300 000");
  await fillLine(page, 2, "401", "Crédit", "2 300 000");
  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Modifier le brouillon");

  const section = page.getByRole("region", { name: "Pièces justificatives" });
  await expect(section).toContainText("Aucune pièce jointe.");

  // PDF envoyé tel quel.
  await attach(page, "Facture papeterie.pdf", "application/pdf", PDF);
  await expect(section.getByRole("status")).toHaveText("Pièce ajoutée.");
  const pdfItem = section.getByRole("listitem").filter({ hasText: "Facture papeterie.pdf" });
  await expect(pdfItem).toBeVisible();

  // Photo lourde : réduite en JPEG dans le navigateur avant l'envoi.
  const photo = noisyPng(700, 500);
  expect(photo.length).toBeGreaterThan(1_000_000);
  await attach(page, "reçu.png", "image/png", photo);
  const photoItem = section.getByRole("listitem").filter({ hasText: "reçu.jpg" });
  await expect(photoItem).toBeVisible();
  const photoSize = await photoItem.getByText(/Ko|Mo/).textContent();
  expect(photoSize).not.toMatch(/Mo/);

  // Même fichier renvoyé (réessai) : pas de doublon.
  await attach(page, "copie.pdf", "application/pdf", PDF);
  await expect(section.getByRole("status")).toHaveText("Ce fichier est déjà joint à l'écriture.");
  await expect(section.getByRole("listitem")).toHaveCount(2);

  // Format refusé : vérifié sur le contenu, pas sur l'extension.
  await attach(page, "virus.pdf", "application/pdf", Buffer.from("<script>alert(1)</script>"));
  await expect(section.getByRole("alert")).toContainText("Format non accepté");

  // Consultation et téléchargement via le serveur web (BFF).
  const href = await pdfItem.getByRole("link", { name: /^Ouvrir/ }).getAttribute("href");
  const opened = await page.request.get(href ?? "");
  expect(opened.status()).toBe(200);
  expect(opened.headers()["content-type"]).toBe("application/pdf");
  expect(opened.headers()["content-disposition"]).toMatch(/^inline;/);
  expect(Buffer.compare(await opened.body(), PDF)).toBe(0);
  const downloading = page.waitForEvent("download");
  await pdfItem.getByRole("link", { name: /^Télécharger/ }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe("Facture papeterie.pdf");

  // Retrait sur un brouillon.
  page.once("dialog", (dialog) => void dialog.accept());
  await photoItem.getByRole("button", { name: "Retirer" }).click();
  await expect(photoItem).toHaveCount(0);

  // Après validation : la pièce est conservée, on peut encore en ajouter.
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Valider", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("AC n° 1 — Achat de papier");
  await expect(section).toContainText("ses pièces sont conservées");
  await expect(section.getByRole("button", { name: "Retirer" })).toHaveCount(0);
  await attach(page, "bon de livraison.pdf", "application/pdf", Buffer.concat([PDF, Buffer.from("BL-77")]));
  await expect(section.getByRole("listitem")).toHaveCount(2);
});
