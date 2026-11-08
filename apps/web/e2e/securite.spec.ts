import { expect, test } from "@playwright/test";

import {
  createCompany,
  login,
  PASSWORD,
  register,
  registerAndLogin,
  totp,
  uniqueEmail,
  waitForNextTotpStep,
} from "./helpers";

test("les pages protégées renvoient vers la connexion puis vers la page demandée", async ({ page }) => {
  const email = uniqueEmail();
  await page.goto("/dossiers/nouveau");
  await expect(page).toHaveURL(/\/connexion\?suivant=%2Fdossiers%2Fnouveau/);
  await register(page, email, "Ibrahima Barry");
  await page.goto("/connexion?suivant=%2Fdossiers%2Fnouveau");
  await page.getByLabel("Adresse email").fill(email);
  await page.getByLabel("Mot de passe").fill("Mot-de-passe-E2E-2026");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).toHaveURL(/\/dossiers\/nouveau$/);
});

test("une redirection externe après connexion est refusée", async ({ page }) => {
  const email = uniqueEmail();
  await register(page, email, "Mariama Diallo");
  await page.goto("/connexion?suivant=https%3A%2F%2Fevil.example");
  await page.getByLabel("Adresse email").fill(email);
  await page.getByLabel("Mot de passe").fill("Mot-de-passe-E2E-2026");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).toHaveURL(/\/dossiers$/);
});

test("le dossier d'un autre utilisateur est introuvable", async ({ browser }) => {
  const alice = await browser.newPage();
  const bob = await browser.newPage();
  await registerAndLogin(alice);
  const companyId = await createCompany(alice, "Société d'Alice SARL");
  await registerAndLogin(bob);
  await bob.goto(`/dossiers/${companyId}`);
  await expect(bob.getByRole("heading", { name: "Page introuvable" })).toBeVisible();
  await expect(bob.getByText("Société d'Alice SARL")).toHaveCount(0);
});

test("mauvais mot de passe : message clair, sans révéler si le compte existe", async ({ page }) => {
  await page.goto("/connexion");
  await page.getByLabel("Adresse email").fill(uniqueEmail());
  await page.getByLabel("Mot de passe").fill("Mauvais-mot-de-passe");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Adresse email ou mot de passe incorrect." }),
  ).toBeVisible();
});

test("en-têtes de sécurité et cookies de session httpOnly", async ({ page, context }) => {
  const response = await page.goto("/connexion");
  const csp = response?.headers()["content-security-policy"] ?? "";
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toContain("object-src 'none'");
  expect(csp).toContain("form-action 'self'");
  expect(csp).toMatch(/script-src 'self' 'unsafe-inline'(;|$)/);
  expect(response?.headers()["x-content-type-options"]).toBe("nosniff");

  await registerAndLogin(page);
  const session = (await context.cookies()).filter((c) => c.name.startsWith("kora_"));
  const access = session.find((c) => c.name === "kora_at");
  const refresh = session.find((c) => c.name === "kora_rt");
  expect(access?.httpOnly).toBe(true);
  expect(refresh?.httpOnly).toBe(true);
  expect(access?.sameSite).toBe("Lax");
});

test("la session est renouvelée quand le jeton d'accès a expiré", async ({ page, context }) => {
  await registerAndLogin(page);
  // Simule l'expiration du jeton d'accès : seul le refresh token reste.
  const cookies = await context.cookies();
  await context.clearCookies({ name: "kora_at" });
  expect(cookies.some((c) => c.name === "kora_rt")).toBe(true);
  await page.goto("/dossiers");
  await expect(page).toHaveURL(/\/dossiers$/);
  const renewed = await context.cookies();
  expect(renewed.some((c) => c.name === "kora_at")).toBe(true);
});

test("changement de langue", async ({ page }) => {
  await registerAndLogin(page);
  await page.getByRole("button", { name: /English/ }).click();
  await expect(page.getByRole("heading", { name: "My companies" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.getByRole("button", { name: /Français/ }).click();
  await expect(page.getByRole("heading", { name: "Mes dossiers" })).toBeVisible();
});

test("PWA : manifeste et page hors connexion disponibles", async ({ request }) => {
  const manifest = await request.get("/manifest.webmanifest");
  expect(manifest.ok()).toBe(true);
  const body = (await manifest.json()) as { name: string; icons: { src: string }[] };
  expect(body.name).toBe("Kora Finance");
  for (const icon of body.icons) {
    expect((await request.get(icon.src)).ok()).toBe(true);
  }
  expect((await request.get("/sw.js")).headers()["cache-control"]).toContain("no-cache");
  const offline = await request.get("/hors-connexion");
  expect(await offline.text()).toContain("Vous êtes hors connexion");
});

test("double authentification : activation puis connexion en deux étapes", async ({ page }) => {
  test.setTimeout(120_000);
  const email = await registerAndLogin(page);
  await page.goto("/compte/securite");
  // L'enrôlement exige la réauthentification (KF-08) : mot de passe au début...
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Activer" }).click();
  const secret = (await page.locator("code").first().textContent())?.trim() ?? "";
  expect(secret).toMatch(/^[A-Z2-7]{16,}$/);
  // ...et à la confirmation.
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Code de vérification").fill(totp(secret));
  await page.getByRole("button", { name: "Confirmer l'activation" }).click();
  await expect(page.getByText("Codes de secours")).toBeVisible();
  const recoveryCodes = await page.locator("ul.font-mono li").allTextContents();
  expect(recoveryCodes).toHaveLength(10);

  await page.getByRole("button", { name: "Se déconnecter" }).click();
  await expect(page).toHaveURL(/\/connexion\?deconnecte=1/);
  await login(page, email);
  await expect(page).toHaveURL(/\/connexion\/verification/);
  // Le code d'activation a consommé le pas de temps courant.
  await waitForNextTotpStep();
  await page.getByLabel("Code de vérification").fill(totp(secret));
  await page.getByRole("button", { name: "Vérifier" }).click();
  await expect(page).toHaveURL(/\/dossiers$/);

  // Un code de secours permet aussi de se connecter.
  await page.getByRole("button", { name: "Se déconnecter" }).click();
  await expect(page).toHaveURL(/\/connexion\?deconnecte=1/);
  await login(page, email);
  await page.getByLabel("Code de vérification").fill(recoveryCodes[0] ?? "");
  await page.getByRole("button", { name: "Vérifier" }).click();
  await expect(page).toHaveURL(/\/dossiers$/);
});
