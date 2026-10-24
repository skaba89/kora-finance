import { expect, test } from "@playwright/test";

import { createCompany, emailLink, register, registerAndLogin, uniqueEmail, verifyEmail } from "./helpers";

const NEW_PASSWORD = "Nouveau-mot-de-passe-E2E-2026";

test("mot de passe oublié : lien reçu par email, nouveau mot de passe, connexion", async ({ page }) => {
  const email = uniqueEmail("oubli");
  await register(page, email);

  await page.getByRole("link", { name: "Mot de passe oublié ?" }).click();
  await expect(page).toHaveURL(/\/mot-de-passe-oublie$/);
  await page.getByLabel("Adresse email").fill(email);
  await page.getByRole("button", { name: "Envoyer le lien" }).click();
  await expect(page.getByRole("status")).toContainText("Si un compte existe avec cette adresse");

  await page.goto(await emailLink(email, /Réinitialisation de votre mot de passe/));
  await page.getByLabel("Nouveau mot de passe").fill(NEW_PASSWORD);
  await page.getByLabel("Confirmer le mot de passe").fill("autre chose");
  await page.getByRole("button", { name: "Enregistrer le mot de passe" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "ne sont pas identiques" })).toBeVisible();

  await page.getByLabel("Nouveau mot de passe").fill(NEW_PASSWORD);
  await page.getByLabel("Confirmer le mot de passe").fill(NEW_PASSWORD);
  await page.getByRole("button", { name: "Enregistrer le mot de passe" }).click();
  await expect(page).toHaveURL(/\/connexion\?reinitialise=1/);
  await expect(page.getByRole("status")).toContainText("Mot de passe modifié");

  await page.getByLabel("Adresse email").fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(NEW_PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).toHaveURL(/\/dossiers$/);
  // Avoir reçu le lien a confirmé l'adresse : plus de bandeau de vérification.
  await expect(page.getByText("Confirmez votre adresse email")).toHaveCount(0);
});

test("un lien de réinitialisation tronqué est signalé", async ({ page }) => {
  await page.goto("/reinitialisation-mot-de-passe?jeton=abc");
  await expect(page.getByRole("alert").filter({ hasText: "Ce lien est incomplet" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Faire une nouvelle demande" })).toBeVisible();
});

test("vérification de l'adresse depuis le bandeau et l'email", async ({ page }) => {
  const email = await registerAndLogin(page, uniqueEmail("verif"));
  const banner = page.getByText(`un lien vous a été envoyé à ${email}`);
  await expect(banner).toBeVisible();
  await page.getByRole("button", { name: "Renvoyer l'email" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Email envoyé" })).toBeVisible();

  // Le renvoi a invalidé le premier lien : c'est le second email qui sert.
  await verifyEmail(page, email, 2);
  await page.getByRole("link", { name: "Continuer" }).click();
  await expect(page).toHaveURL(/\/dossiers$/);
  await expect(banner).toHaveCount(0);
});

test("invitation d'une personne sans compte jusqu'à son arrivée dans le dossier", async ({ page, browser }) => {
  const owner = await registerAndLogin(page, uniqueEmail("dirigeant"), "Ousmane Keita");
  const companyId = await createCompany(page, "Transports du Fouta SARL");
  const invitee = uniqueEmail("invitee");

  // Adresse non confirmée : invitation refusée, avec l'explication.
  await page.goto(`/dossiers/${companyId}/parametres/utilisateurs`);
  await page.getByLabel("Email").fill(invitee);
  await page.getByRole("button", { name: "Ajouter" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Confirmez d'abord votre propre adresse" })).toBeVisible();

  await verifyEmail(page, owner);
  await page.goto(`/dossiers/${companyId}/parametres/utilisateurs`);
  await page.getByLabel("Email").fill(invitee);
  await page.getByRole("button", { name: "Ajouter" }).click();
  await expect(page.getByRole("status").filter({ hasText: `Invitation envoyée à ${invitee}` })).toBeVisible();
  const pending = page.getByRole("region", { name: "Invitations en attente" });
  await expect(pending.getByRole("cell", { name: invitee })).toBeVisible();

  // L'invité, dans un autre navigateur, ouvre le lien reçu et crée son compte.
  const link = await emailLink(invitee, /Ousmane Keita vous invite/);
  const context = await browser.newContext();
  const guest = await context.newPage();
  await guest.goto(link);
  await expect(guest.getByText("Ousmane Keita vous invite à rejoindre le dossier « Transports du Fouta SARL »")).toBeVisible();
  await expect(guest.getByText("avec le rôle Comptable")).toBeVisible();
  await guest.getByLabel("Nom complet").fill("Mariama Condé");
  await guest.getByLabel("Mot de passe").fill(NEW_PASSWORD);
  await guest.getByRole("button", { name: "Accepter et créer mon compte" }).click();
  await expect(guest).toHaveURL(new RegExp(`/dossiers/${companyId}$`));
  await expect(guest.getByRole("heading", { level: 1, name: "Transports du Fouta SARL" })).toBeVisible();
  await expect(guest.getByText("Confirmez votre adresse email")).toHaveCount(0);

  // Le lien ne sert qu'une fois.
  await guest.goto(link);
  await expect(guest.getByRole("alert").filter({ hasText: "invalide, a expiré ou a été annulée" })).toBeVisible();
  await context.close();

  await page.reload();
  await expect(page.getByRole("cell", { name: /Mariama Condé/ })).toBeVisible();
  await expect(pending.getByText("Aucune invitation en attente.")).toBeVisible();
});
