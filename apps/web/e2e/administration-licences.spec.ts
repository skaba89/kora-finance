import { expect, type Page, test } from "@playwright/test";

/**
 * SEC-1 : recette E2E positive de l'administration plateforme des licences
 * (anti-régression de #207). L'administrateur, l'offre et les dossiers clients
 * à états déterministes sont fournis par le seed
 * `kora.scripts.seed_platform_recette`, exécuté par `make e2e` avant
 * Playwright. Les dossiers mutables existent en N exemplaires : chaque
 * spécification sonde du premier au dernier et prend le premier à l'état
 * attendu, ce qui reste correct après une relance ou une reprise en CI.
 *
 * La console d'administration est une recette ordinateur : le projet mobile
 * est hors périmètre pour ces spécifications.
 */

const ADMIN_EMAIL = "admin@recette.kora.gn";
const ADMIN_PASSWORD = "Recette-Plateforme-2026!";
const CONSULTATION = "A Recette Licences Consultation";
const SUSPENSION = "A Recette Licences Suspension";
const REACTIVATION = "A Recette Licences Réactivation";
const RENEWAL = "A Recette Licences Renouvellement";
const CONFLICT_SUSPENSION = "A Recette Licences Conflit Suspension";
const CONFLICT_RENEWAL = "A Recette Licences Conflit Renouvellement";
const SLOTS = 4;
const SUSPENSION_409 = "État de licence modifié ; actualisez avant de réessayer.";
const RENEWAL_409 = "Une période commerciale chevauche déjà ces dates.";

test.beforeEach(() => {
  test.skip(
    test.info().project.name !== "chromium",
    "Console d'administration plateforme : recette ordinateur uniquement.",
  );
});

async function loginAdmin(page: Page) {
  await page.goto("/connexion");
  await page.getByLabel("Adresse email").fill(ADMIN_EMAIL);
  await page.getByLabel("Mot de passe").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).toHaveURL(/\/dossiers$/);
}

/** Confirme nativement les boîtes de dialogue (suspension, réactivation, renouvellement). */
function acceptDialogs(page: Page) {
  page.on("dialog", (dialog) => {
    void dialog.accept();
  });
}

/** Date civile AAAA-MM-JJ, décalée de `days` jours à partir d'aujourd'hui (UTC). */
function isoDayOffset(days: number): string {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() + days);
  return day.toISOString().slice(0, 10);
}

/** Attend qu'une condition d'écran devienne vraie (rendu différé des Server Components). */
async function waitForState(check: () => Promise<boolean>, timeoutMs = 4_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await check()) return true;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

const singlePeriodWithButton = (page: Page, button: string) =>
  waitForState(async () =>
    Boolean(
      (await page.getByText("Périodes affichées : 1 / 1").isVisible()) &&
        (await page.getByRole("button", { name: button, exact: true }).isVisible()),
    ),
  );

const singleSuspendedPeriod = (page: Page) =>
  waitForState(async () =>
    Boolean(
      (await page.getByText("Périodes affichées : 1 / 1").isVisible()) &&
        (await page.getByText("Suspension enregistrée").isVisible()) &&
        (await page.getByRole("button", { name: "Réactiver", exact: true }).isVisible()),
    ),
  );

/** Ouvre le premier dossier du préfixe dont l'écran est dans l'état attendu. */
async function openFirstMatching(
  page: Page,
  prefix: string,
  ready: (page: Page) => Promise<boolean>,
) {
  for (let slot = 1; slot <= SLOTS; slot++) {
    await page.goto("/administration/licences");
    const link = page.getByRole("link", { name: `${prefix} ${slot}` });
    if (!(await waitForState(() => link.isVisible()))) continue;
    await link.click();
    await expect(page.getByRole("heading", { level: 2, name: `${prefix} ${slot}` })).toBeVisible();
    if (await ready(page)) return;
  }
  throw new Error(
    `Aucun dossier « ${prefix} 1..${SLOTS} » à l'état attendu ; relancez le seed plateforme.`,
  );
}

test("l'administrateur plateforme consulte les licences et filtre par état", async ({ page }) => {
  await loginAdmin(page);
  await expect(page.getByRole("link", { name: "Administration", exact: true })).toBeVisible();
  await page.goto("/administration");
  await expect(page.getByRole("heading", { name: "Administration Kora Finance" })).toBeVisible();
  await page.getByRole("link", { name: "Consulter les licences" }).click();
  await expect(page).toHaveURL(/administration\/licences/);
  await expect(page.getByRole("heading", { name: "Licences commerciales" })).toBeVisible();

  await page.getByRole("link", { name: CONSULTATION }).click();
  await expect(page.getByRole("heading", { level: 2, name: CONSULTATION })).toBeVisible();
  await expect(page.getByText("Périodes affichées : 3 / 3")).toBeVisible();

  await page.getByRole("combobox", { name: "État" }).selectOption({ label: "Active" });
  await page.getByRole("button", { name: "Consulter" }).click();
  await expect(page.getByText("Périodes affichées : 1 / 3")).toBeVisible();
  await expect(page.getByText("Aucune période pour cet état.")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Suspendre", exact: true })).toBeVisible();
});

test("suspension auditée puis réactivation d'une période active", async ({ page }) => {
  await loginAdmin(page);
  acceptDialogs(page);
  await openFirstMatching(page, SUSPENSION, (current) => singlePeriodWithButton(current, "Suspendre"));

  await page.getByLabel("Motif de l’intervention").fill("Impayé constaté — suspension temporaire recette.");
  await page.getByRole("button", { name: "Suspendre", exact: true }).click();
  await expect(page.getByText("Suspension enregistrée")).toBeVisible();
  await expect(page.getByRole("button", { name: "Réactiver", exact: true })).toBeVisible();

  await page.getByLabel("Motif de l’intervention").fill("Régularisation du paiement — réactivation recette.");
  await page.getByRole("button", { name: "Réactiver", exact: true }).click();
  await expect(page.getByRole("button", { name: "Suspendre", exact: true })).toBeVisible();
  await expect(page.getByText("Suspension enregistrée")).toHaveCount(0);
});

test("réactivation directe d'une période suspendue en base", async ({ page }) => {
  await loginAdmin(page);
  acceptDialogs(page);
  await openFirstMatching(page, REACTIVATION, singleSuspendedPeriod);

  await page.getByLabel("Motif de l’intervention").fill("Paiement régularisé — réactivation recette.");
  await page.getByRole("button", { name: "Réactiver", exact: true }).click();
  await expect(page.getByRole("button", { name: "Suspendre", exact: true })).toBeVisible();
  await expect(page.getByText("Suspension enregistrée")).toHaveCount(0);
});

test("renouvellement : période adjacente créée, période actuelle inchangée", async ({ page }) => {
  await loginAdmin(page);
  acceptDialogs(page);
  await openFirstMatching(page, RENEWAL, (current) => singlePeriodWithButton(current, "Renouveler"));

  await page.getByLabel("Nouvelle fin (exclusive)").fill(isoDayOffset(180));
  await page.getByLabel("Motif du renouvellement").fill("Prolongation validée par la direction commerciale.");
  await page.getByRole("button", { name: "Renouveler", exact: true }).click();

  await expect(page.getByText("Déjà renouvelée.")).toBeVisible();
  await expect(page.getByText("Périodes affichées : 2 / 2")).toBeVisible();
  await expect(page.getByRole("button", { name: "Renouveler", exact: true })).toBeVisible();
});

test("suspension concurrente : l'onglet obsolète reçoit un 409 explicite", async ({ page }) => {
  await loginAdmin(page);
  acceptDialogs(page);
  await openFirstMatching(
    page, CONFLICT_SUSPENSION, (current) => singlePeriodWithButton(current, "Suspendre"),
  );

  const stale = await page.context().newPage();
  acceptDialogs(stale);
  await stale.goto(page.url());

  await page.getByLabel("Motif de l’intervention").fill("Incident de paiement signalé par le client.");
  await page.getByRole("button", { name: "Suspendre", exact: true }).click();
  await expect(page.getByText("Suspension enregistrée")).toBeVisible();

  await stale.getByLabel("Motif de l’intervention").fill("Tentative depuis un onglet devenu obsolète.");
  await stale.getByRole("button", { name: "Suspendre", exact: true }).click();
  // L'annonceur de routes Next.js a aussi le rôle alert : on vise l'alerte applicative.
  await expect(stale.locator('[data-slot="alert"]')).toContainText(SUSPENSION_409);
  await stale.close();
});

test("renouvellement concurrent : le second onglet reçoit un 409 de chevauchement", async ({ page }) => {
  await loginAdmin(page);
  acceptDialogs(page);
  await openFirstMatching(
    page, CONFLICT_RENEWAL, (current) => singlePeriodWithButton(current, "Renouveler"),
  );

  const stale = await page.context().newPage();
  acceptDialogs(stale);
  await stale.goto(page.url());

  await page.getByLabel("Nouvelle fin (exclusive)").fill(isoDayOffset(180));
  await page.getByLabel("Motif du renouvellement").fill("Renouvellement validé par le service commercial.");
  await page.getByRole("button", { name: "Renouveler", exact: true }).click();
  await expect(page.getByText("Déjà renouvelée.")).toBeVisible();

  await stale.getByLabel("Nouvelle fin (exclusive)").fill(isoDayOffset(180));
  await stale.getByLabel("Motif du renouvellement").fill("Soumission depuis un onglet devenu obsolète.");
  await stale.getByRole("button", { name: "Renouveler", exact: true }).click();
  // L'annonceur de routes Next.js a aussi le rôle alert : on vise l'alerte applicative.
  await expect(stale.locator('[data-slot="alert"]')).toContainText(RENEWAL_409);
  await stale.close();
});

test("la console des licences est consultable en anglais", async ({ page }) => {
  await page.goto("/en/connexion");
  await page.getByLabel("Email address").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/dossiers/);

  await page.goto("/en/administration/licences");
  await expect(page.getByRole("heading", { name: "Commercial licenses" })).toBeVisible();
  await page.getByRole("link", { name: CONSULTATION }).click();
  await expect(page.getByRole("heading", { level: 2, name: CONSULTATION })).toBeVisible();
  await expect(page.getByText("Displayed periods : 3 / 3")).toBeVisible();
  await expect(page.getByText("Kind : Paid")).toHaveCount(2);
  await expect(page.getByText("Kind : Trial")).toHaveCount(1);
});
