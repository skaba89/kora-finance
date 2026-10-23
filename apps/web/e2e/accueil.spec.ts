import { expect, test } from "@playwright/test";

test("la page d'accueil affiche l'API opérationnelle (web → API → PostgreSQL + Redis)", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Kora Finance");
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");
  await expect(page.getByRole("status")).toHaveText("Opérationnelle");
});
