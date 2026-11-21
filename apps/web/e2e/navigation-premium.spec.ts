import { expect, test } from "@playwright/test";

import { createCompany, registerAndLogin } from "./helpers";

test("navigation premium : recherche et accès au module", async ({ page }, testInfo) => {
  await registerAndLogin(page);
  const companyId = await createCompany(page, "Navigation SARL");
  const nav = page.getByRole("navigation", { name: "Menu principal" });
  const search = nav.getByRole("searchbox", { name: "Rechercher un module" });
  await search.fill("ecritures");
  await expect(nav.getByRole("link", { name: "Écritures", exact: true })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Achats", exact: true })).toHaveCount(0);
  await nav.getByRole("link", { name: "Écritures", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/dossiers/${companyId}/ecritures`));
  await expect(search).toHaveValue("");
  await expect(nav.getByRole("link", { name: "Achats", exact: true })).toHaveCount(1);
  await search.fill("xyz-inexistant");
  await expect(nav.getByRole("status")).toHaveText("Aucun module trouvé");
  await search.press("Escape");
  await expect(search).toHaveValue("");
  await testInfo.attach("navigation-premium", { body: await page.screenshot(), contentType: "image/png" });

  const desktop = (page.viewportSize()?.width ?? 0) >= 768;
  await nav.getByRole("button", { name: desktop ? "Réduire la navigation" : "Fermer le menu" }).click();
  await expect(search).toBeHidden();
  if (desktop) {
    await expect(nav.getByRole("link", { name: "Écritures", exact: true })).toBeVisible();
    await expect(nav.getByRole("button", { name: "Développer la navigation" })).toHaveAttribute("aria-pressed", "true");
  } else {
    await expect(nav.getByRole("link", { name: "Écritures", exact: true })).toBeHidden();
    await expect(nav.getByRole("button", { name: "Ouvrir le menu" })).toHaveAttribute("aria-expanded", "false");
  }
  await testInfo.attach("navigation-premium-repliee", { body: await page.screenshot(), contentType: "image/png" });
  await page.keyboard.press("Control+k");
  await expect(search).toBeVisible();
  await expect(search).toBeFocused();
  await expect(nav.getByRole("link", { name: "Écritures", exact: true })).toBeVisible();
});
