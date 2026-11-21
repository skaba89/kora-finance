import { expect, test } from "@playwright/test";
import { createCompany, registerAndLogin } from "./helpers";

test("barre premium : changer de dossier sans perdre le contexte et changer de langue", async ({ page }, testInfo) => {
  await registerAndLogin(page);
  const first = await createCompany(page, "Premier dossier SARL");
  const second = await createCompany(page, "Second dossier SARL");
  const switcher = page.getByRole("combobox", { name: "Changer de dossier" });
  const open = page.getByRole("button", { name: "Ouvrir le dossier", exact: true });
  await expect(switcher).toHaveValue(second);
  await expect(open).toBeDisabled();
  await expect(switcher.locator("option")).toHaveCount(2);
  await switcher.selectOption(first);
  await expect(page).toHaveURL(new RegExp(`/dossiers/${second}$`));
  await open.click();
  await expect(page).toHaveURL(new RegExp(`/dossiers/${first}$`));
  await expect(page.getByRole("heading", { level: 1, name: "Premier dossier SARL" })).toBeVisible();
  await expect(switcher).toHaveValue(first);
  await testInfo.attach("company-switcher-fr", { body: await page.screenshot(), contentType: "image/png" });

  await page.getByRole("button", { name: "Langue : English" }).click();
  await expect(page.getByRole("combobox", { name: "Switch company" })).toHaveValue(first);
  await expect(page.getByRole("button", { name: "Open company", exact: true })).toBeDisabled();
  await testInfo.attach("company-switcher-en", { body: await page.screenshot(), contentType: "image/png" });
  await page.getByRole("banner").getByRole("link", { name: "My companies", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "My companies" })).toBeVisible();
});
