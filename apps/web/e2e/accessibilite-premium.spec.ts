import { expect, test, type Page } from "@playwright/test";

import { createCompany, registerAndLogin } from "./helpers";

const widths = [360, 390, 768, 1024, 1440, 1920];

async function expectReflow(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
}

async function expectSkipLink(page: Page, label: string) {
  const main = page.getByRole("main");
  await expect(main).toHaveCount(1);
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: label, exact: true });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(main).toBeFocused();
}

test("connexion FR/EN : accès clavier et six largeurs", async ({ page }, testInfo) => {
  for (const [locale, skip] of [["fr", "Aller au contenu principal"], ["en", "Skip to main content"]] as const) {
    await page.goto(`/${locale}/connexion`);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectSkipLink(page, skip);
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 });
      await expectReflow(page);
      if (width === 390 || width === 1440) {
        await testInfo.attach(`connexion-${locale}-${width}`, { body: await page.screenshot(), contentType: "image/png" });
      }
    }
  }
});

test("dossier : accès direct au contenu et reflow du tableau de bord", async ({ page }, testInfo) => {
  await registerAndLogin(page);
  const id = await createCompany(page, "Accessibilité Premium SARL");
  await page.goto(`/dossiers/${id}`);
  await expect(page.getByRole("heading", { level: 1, name: "Accessibilité Premium SARL" })).toBeVisible();
  await expectSkipLink(page, "Aller au contenu principal");
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    await expectReflow(page);
    if (width === 390 || width === 1440) {
      await testInfo.attach(`dashboard-${width}`, { body: await page.screenshot(), contentType: "image/png" });
    }
  }
});
