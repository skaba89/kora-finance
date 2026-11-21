import { expect, test } from "@playwright/test";
import { createCompany, registerAndLogin } from "./helpers";

test("prévisions : horizon, scénario, détail accessible et export", async ({ page }, testInfo) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Prévisions SARL");
  await page.goto(`/dossiers/${companyId}/tresorerie/previsions`);
  await expect(page.getByRole("heading", { name: "Prévision de trésorerie", exact: true })).toBeVisible();
  await page.getByRole("group", { name: "Horizon" }).getByRole("link", { name: "30 jours" }).click();
  await page.getByRole("group", { name: "Scénario" }).getByRole("link", { name: "Prudent" }).click();
  await expect(page.getByRole("link", { name: "30 jours", exact: true })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("link", { name: "Prudent", exact: true })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("link", { name: "Exporter en PDF" })).toHaveAttribute("href", /horizon=30.*scenario=PRUDENT|scenario=PRUDENT.*horizon=30/);
  await page.getByText(/Détail journalier —/).click();
  await expect(page.getByRole("table", { name: "Détail journalier" })).toBeVisible();
  await testInfo.attach("previsions-prudent-30j", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
});
