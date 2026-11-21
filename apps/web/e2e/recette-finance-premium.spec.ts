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

const administrativeRoutes = [
  ["parametres/entreprise", "Identité de l'entreprise"],
  ["parametres/exercices", "Exercices comptables"],
  ["parametres/plan-comptable", "Plan comptable"],
  ["parametres/journaux", "Journaux"],
  ["parametres/taxes", "Taux de taxes"],
  ["parametres/utilisateurs", "Utilisateurs du dossier"],
  ["tresorerie/previsions/reglages", "Seuils d'alerte"],
  ["journal-audit", "Journal d'audit"],
  ["hors-connexion", "Saisie hors connexion"],
] as const;

test("recette responsive : finance et administration", async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  await registerAndLogin(page);
  const company = await createCompany(page, "Recette responsive SARL");
  const widths = testInfo.project.name === "mobile" ? [360, 390, 768] : [1024, 1440, 1920];
  const measurements: { route: string; width: number; viewport: number; overflow: number }[] = [];

  for (const [route, title] of [...routes, ...administrativeRoutes]) {
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

  const outliers = measurements.filter(({ overflow }) => overflow > 1);
  // Les 72 mesures financières de la CI #302 sont sans débordement : non-régression
  // bloquante. Les nouveaux écrans administratifs constituent une première baseline.
  await testInfo.attach("reflow-finance", { body: JSON.stringify({ measurements, outliers }, null, 2), contentType: "application/json" });
  expect(measurements).toHaveLength((routes.length + administrativeRoutes.length) * widths.length);
  expect(measurements.filter(({ width, viewport }) => width !== viewport), "Largeurs réellement testées").toEqual([]);
  expect(outliers.filter(({ route }) => routes.some(([financialRoute]) => financialRoute === route)), "Régression de débordement financier").toEqual([]);
});
