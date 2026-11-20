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
});
