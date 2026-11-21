import { expect, test } from "@playwright/test";
import { createCompany, registerAndLogin } from "./helpers";

test("prévisions : horizon, scénario, détail accessible et export", async ({ page }, testInfo) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Prévisions SARL");
  await page.goto(`/dossiers/${companyId}/tresorerie/previsions`);
  await expect(page.getByRole("heading", { name: "Prévision de trésorerie", exact: true })).toBeVisible();
  const horizon30 = page.getByRole("group", { name: "Horizon" }).getByRole("link", { name: "30 jours" });
  const prudent = page.getByRole("group", { name: "Scénario" }).getByRole("link", { name: "Prudent" });
  await horizon30.click();
  // Attendre le rendu serveur, pas seulement la navigation : les liens du
  // second groupe doivent reprendre le nouvel horizon avant le clic suivant.
  await expect(horizon30).toHaveAttribute("aria-current", "true");
  await expect(prudent).toHaveAttribute("href", "?horizon=30&scenario=PRUDENT");
  await prudent.click();
  await expect(page.getByRole("link", { name: "30 jours", exact: true })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("link", { name: "Prudent", exact: true })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("link", { name: "Exporter en PDF" })).toHaveAttribute("href", /horizon=30.*scenario=PRUDENT|scenario=PRUDENT.*horizon=30/);
  await page.getByText(/Détail journalier —/).click();
  await expect(page.getByRole("table", { name: "Détail journalier" })).toBeVisible();
  await testInfo.attach("previsions-prudent-30j", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
});
