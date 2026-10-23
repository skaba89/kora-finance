import { expect, test } from "@playwright/test";

/** Aucune violation de CSP ni erreur JavaScript sur les pages publiques. */
test("pas d'erreur dans la console du navigateur", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  for (const path of ["/connexion", "/inscription", "/hors-connexion"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  expect(errors).toEqual([]);
});
