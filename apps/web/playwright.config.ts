import { defineConfig, devices } from "@playwright/test";

// Les tests E2E visent une pile déjà démarrée (docker compose) : pas de webServer ici.
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3100";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL,
    locale: "fr-FR",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    // Cible principale : smartphone Android d'entrée de gamme.
    { name: "mobile", use: { ...devices["Pixel 5"] } },
  ],
});
