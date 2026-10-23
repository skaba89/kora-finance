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
