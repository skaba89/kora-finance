import { expect, test } from "@playwright/test";

test("thème système, choix explicite et persistance FR/EN", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/fr/connexion");
  const root = page.locator("html");
  const fr = page.getByRole("combobox", { name: "Thème d’affichage" });
  await expect(fr).toHaveValue("system");
  await expect(root).toHaveClass(/\bdark\b/);
  await fr.selectOption("light");
  await expect(root).not.toHaveClass(/\bdark\b/);
  await page.reload();
  await expect(fr).toHaveValue("light");
  await expect(root).not.toHaveClass(/\bdark\b/);
  await page.goto("/en/connexion");
  const en = page.getByRole("combobox", { name: "Display theme" });
  await expect(en).toHaveValue("light");
  await en.selectOption("dark");
  await expect(root).toHaveClass(/\bdark\b/);
  await en.selectOption("system");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(root).not.toHaveClass(/\bdark\b/);
});
