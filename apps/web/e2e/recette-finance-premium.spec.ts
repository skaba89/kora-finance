import { expect, test } from "@playwright/test";

import { createCompany, registerAndLogin } from "./helpers";

const routes = [
  ["ecritures", "Écritures"],
  ["ecritures/nouvelle", "Nouvelle écriture"],
  ["saisie-guidee", "Saisie guidée"],
  ["balance", "Balance générale"],
  ["grand-livre", "Grand livre"],
  ["lettrage", "Lettrage"],
  ["ventes", "Ventes"],
  ["achats", "Achats"],
  ["tiers", "Référentiel des tiers"],
  ["tresorerie", "Trésorerie"],
  ["tresorerie/previsions", "Prévision de trésorerie"],
  ["etats-financiers", "États financiers"],
] as const;

test("recette responsive : douze écrans financiers", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await registerAndLogin(page);
  const company = await createCompany(page, "Recette responsive SARL");
  const widths = testInfo.project.name === "mobile" ? [360, 390, 768] : [1024, 1440, 1920];
  const measurements: { route: string; width: number; viewport: number; overflow: number }[] = [];

  for (const [route, title] of routes) {
    await test.step(route, async () => {
      await page.goto(`/dossiers/${company}/${route}`);
      const heading = page.getByRole("heading", { level: 1, name: title, exact: true });
      await expect(heading).toBeVisible();
      for (const width of widths) {
        await page.setViewportSize({ width, height: 900 });
        await expect(heading).toBeVisible();
        await page.evaluate(() => document.fonts.ready);
        const dimensions = await page.evaluate(() => new Promise<{ viewport: number; overflow: number }>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => {
            const root = document.documentElement;
            resolve({ viewport: root.clientWidth, overflow: Math.max(0, root.scrollWidth - root.clientWidth) });
          }));
        }));
        measurements.push({ route, width, ...dimensions });
        if (width === 390 || width === 1440) {
          await testInfo.attach(`${route.replaceAll("/", "-")}-${width}`, { body: await page.screenshot(), contentType: "image/png" });
        }
      }
    });
  }

  // Première baseline : publier tous les écarts avant de rendre le reflow bloquant.
  // Les titres et la navigation réelle sont déjà vérifiés de façon bloquante.
  await testInfo.attach("reflow-finance", { body: JSON.stringify({ measurements, outliers: measurements.filter(({ overflow }) => overflow > 1) }, null, 2), contentType: "application/json" });
});
