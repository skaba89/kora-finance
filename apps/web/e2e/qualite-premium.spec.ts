import axe, { type AxeResults } from "axe-core";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { createCompany, registerAndLogin } from "./helpers";

async function audit(page: Page, name: string, testInfo: TestInfo) {
  await page.addScriptTag({ content: axe.source });
  const result = await page.evaluate(async () => {
    const axe = (window as unknown as { axe: typeof import("axe-core") }).axe;
    return axe.run({ runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] } });
  }) as AxeResults;
  // Ne pas joindre le HTML, les valeurs des champs ni les sélecteurs contenant des données métier.
  const report = {
    version: result.testEngine.version,
    passedRules: result.passes.length,
    violations: result.violations.map(({ id, impact, nodes }) => ({ id, impact, count: nodes.length })),
    manualReview: result.incomplete.map(({ id, nodes }) => ({ id, count: nodes.length })),
  };
  await testInfo.attach(`axe-${name}`, { body: JSON.stringify(report, null, 2), contentType: "application/json" });
  expect(report.passedRules, "Le moteur axe doit avoir évalué la page").toBeGreaterThan(0);
  // Première baseline : les violations sont publiées, sans prétendre à une certification WCAG.
}

test("audit WCAG automatisé : connexion FR/EN et tableau de bord", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  for (const locale of ["fr", "en"]) {
    await page.goto(`/${locale}/connexion`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await audit(page, `connexion-${locale}`, testInfo);
  }
  await registerAndLogin(page);
  await createCompany(page, "Qualité UX SARL");
  await expect(page.getByRole("searchbox", { name: "Rechercher un module" })).toBeVisible();
  await audit(page, "dashboard", testInfo);
});

type LabMetrics = { lcpMs: number | null; cls: number; longestInteractionMs: number | null; interactionEntries: number };

test("mesure laboratoire : tableau de bord sur réseau ralenti", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const company = await registerAndLogin(page).then(() => createCompany(page, "Performance UX SARL"));
  await page.addInitScript(() => {
    const metrics: LabMetrics = { lcpMs: null, cls: 0, longestInteractionMs: null, interactionEntries: 0 };
    (window as unknown as { koraLabMetrics: LabMetrics }).koraLabMetrics = metrics;
    let sessionStart = 0;
    let lastShift = 0;
    let sessionValue = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) metrics.lcpMs = entry.startTime;
    }).observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) {
        if (entry.hadRecentInput) continue;
        if (entry.startTime - lastShift >= 1000 || entry.startTime - sessionStart >= 5000 || sessionValue === 0) {
          sessionStart = entry.startTime;
          sessionValue = 0;
        }
        sessionValue += entry.value;
        lastShift = entry.startTime;
        metrics.cls = Math.max(metrics.cls, sessionValue);
      }
    }).observe({ type: "layout-shift", buffered: true });
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries() as (PerformanceEntry & { interactionId: number })[]) {
        if (!entry.interactionId) continue;
        metrics.interactionEntries++;
        metrics.longestInteractionMs = Math.max(metrics.longestInteractionMs ?? 0, entry.duration);
      }
    }).observe({ type: "event", buffered: true, durationThreshold: 16 } as PerformanceObserverInit);
  });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  await cdp.send("Network.setBypassServiceWorker", { bypass: true });
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 150, downloadThroughput: 200_000, uploadThroughput: 93_750 });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  try {
    await page.goto(`/dossiers/${company}`);
    await expect(page.getByRole("heading", { level: 1, name: "Performance UX SARL" })).toBeVisible({ timeout: 20_000 });
    const search = page.getByRole("searchbox", { name: "Rechercher un module" });
    await expect(search).toBeVisible({ timeout: 20_000 });
    await page.evaluate(() => document.fonts.ready);
    await expect.poll(() => page.evaluate(() => (window as unknown as { koraLabMetrics: LabMetrics }).koraLabMetrics.lcpMs)).not.toBeNull();
    await search.click();
    await search.pressSequentially("ecritures");
    await expect(search).toHaveValue("ecritures");
    await search.press("Escape");
    await expect(search).toHaveValue("");
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    const metrics = await page.evaluate(() => (window as unknown as { koraLabMetrics: LabMetrics }).koraLabMetrics);
    await testInfo.attach("core-web-vitals-lab", { body: JSON.stringify({
      profile: { latencyMs: 150, downKbps: 1600, upKbps: 750, cpuSlowdown: 4, cacheDisabled: true, serviceWorkerBypassed: true, viewport: page.viewportSize() },
      ...metrics,
      targets: { lcpMs: 2500, cls: 0.1, interactionMs: 200 },
      note: "Longest observed interaction is an indicative lab sample, not field INP. Null means no qualifying event was observed.",
    }, null, 2), contentType: "application/json" });
    expect(metrics.lcpMs).not.toBeNull();
  } finally {
    await cdp.detach();
  }
});
