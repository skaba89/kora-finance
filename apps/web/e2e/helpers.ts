import { createHmac, randomUUID } from "node:crypto";

import { expect, type Page } from "@playwright/test";

export const PASSWORD = "Mot-de-passe-E2E-2026";

export function uniqueEmail(prefix = "e2e") {
  return `${prefix}-${randomUUID().slice(0, 8)}@exemple.gn`;
}

export async function register(page: Page, email: string, fullName = "Aminata Sylla") {
  await page.goto("/inscription");
  await page.getByLabel("Nom complet").fill(fullName);
  await page.getByLabel("Adresse email").fill(email);
  await page.getByLabel("Mot de passe").fill(PASSWORD);
  await page.getByRole("button", { name: "Créer mon compte" }).click();
  await expect(page).toHaveURL(/\/connexion\?inscrit=1/);
}

export async function login(page: Page, email: string) {
  await page.goto("/connexion");
  await page.getByLabel("Adresse email").fill(email);
  await page.getByLabel("Mot de passe").fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
}

export async function registerAndLogin(page: Page, email = uniqueEmail(), fullName?: string) {
  await register(page, email, fullName);
  await login(page, email);
  await expect(page).toHaveURL(/\/dossiers$/);
  return email;
}

export async function createCompany(page: Page, name: string) {
  await page.goto("/dossiers/nouveau");
  await page.getByLabel("Raison sociale").fill(name);
  await page.getByRole("button", { name: "Créer" }).click();
  await expect(page).toHaveURL(/\/dossiers\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  return page.url().split("/").at(-1) as string;
}

/** Code TOTP (RFC 6238, SHA-1, 6 chiffres, pas de 30 s) pour un secret base32. */
export function totp(secret: string, timeMs = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secret.replace(/=+$/, "").toUpperCase()) {
    bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  }
  const key = Buffer.from(bits.match(/.{8}/g)!.map((byte) => Number.parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(timeMs / 1000 / 30)));
  const hmac = createHmac("sha1", key).update(counter).digest();
  const offset = hmac[hmac.length - 1]! & 0x0f;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return code.toString().padStart(6, "0");
}

/** Attend le début du prochain pas TOTP (un code ne peut servir qu'une fois). */
export async function waitForNextTotpStep() {
  const remaining = 30_000 - (Date.now() % 30_000);
  await new Promise((resolve) => setTimeout(resolve, remaining + 500));
}

const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:58025";

type MailpitSummary = { ID: string; Subject: string };

/**
 * Lien du dernier email reçu par `to` dont le sujet correspond, lu dans Mailpit (le
 * vrai email envoyé par le worker en SMTP). Attend qu'au moins `count` emails de ce
 * type soient arrivés (après un renvoi, seul le plus récent lien est valable).
 * Renvoie le chemin + la requête, à ouvrir sur l'URL de base des tests.
 */
export async function emailLink(to: string, subject: RegExp, count = 1): Promise<string> {
  const query = new URLSearchParams({ query: `to:"${to}"` });
  let found: MailpitSummary | undefined;
  await expect
    .poll(
      async () => {
        const response = await fetch(`${MAILPIT}/api/v1/search?${query}`);
        const { messages } = (await response.json()) as { messages: MailpitSummary[] };
        // Mailpit renvoie les messages du plus récent au plus ancien.
        const matching = messages.filter((m) => subject.test(m.Subject));
        found = matching[0];
        return matching.length;
      },
      { message: `email « ${subject} » pour ${to}`, timeout: 20_000 },
    )
    .toBeGreaterThanOrEqual(count);
  const message = (await (await fetch(`${MAILPIT}/api/v1/message/${found!.ID}`)).json()) as { Text: string };
  const url = message.Text.match(/https?:\/\/\S+\?jeton=[A-Za-z0-9_-]+/)?.[0];
  expect(url, "lien absent de l'email").toBeTruthy();
  const { pathname, search } = new URL(url!);
  return pathname + search;
}

/** Confirme l'adresse de l'utilisateur connecté via le lien reçu par email. */
export async function verifyEmail(page: Page, email: string, sent = 1) {
  await page.goto(await emailLink(email, /Confirmez votre adresse email/, sent));
  await page.getByRole("button", { name: "Confirmer mon adresse" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Adresse email confirmée" })).toBeVisible();
}

export async function fillLine(page: Page, n: number, account: string, side: "Débit" | "Crédit", amount: string) {
  const line = page.getByRole("listitem", { name: `Ligne ${n}` });
  await line.getByLabel("Compte").fill(account);
  await line.getByLabel(side).fill(amount);
}

/** Saisit et valide une écriture à deux lignes depuis l'écran de saisie. */
export async function postEntry(
  page: Page,
  companyId: string,
  entry: { journal: string; date: string; label: string; debit: string; credit: string; amount: string },
) {
  await page.goto(`/dossiers/${companyId}/ecritures/nouvelle`);
  await page.getByRole("combobox", { name: "Journal" }).selectOption({ label: entry.journal });
  await page.getByLabel("Date").fill(entry.date);
  await page.getByRole("textbox", { name: "Libellé", exact: true }).fill(entry.label);
  await fillLine(page, 1, entry.debit, "Débit", entry.amount);
  await fillLine(page, 2, entry.credit, "Crédit", entry.amount);
  await page.getByRole("button", { name: "Enregistrer et valider" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(entry.label);
}
