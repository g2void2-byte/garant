import { test } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — maintenance-баннер end-to-end.
 *
 * ``<MaintenanceBanner />`` mounts inside ``QueryClientProvider`` in
 * ``App.tsx`` and polls ``/api/settings/maintenance`` every 30 s. The
 * fixture default returns ``enabled: false`` so the banner stays
 * hidden across the smoke suite; here we exercise the *visible*
 * branch by overriding the route to return ``enabled: true`` with a
 * server message and then assert the banner surfaces on the public
 * landing page.
 */
test.describe("Maintenance banner", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("renders the banner when /api/settings/maintenance reports enabled", async ({
    page,
  }) => {
    await mockApi(page);
    // Override the default ``enabled: false`` fixture *after*
    // ``mockApi`` so this route wins (Playwright runs the
    // last-registered matching handler first).
    await page.route(
      /^https?:\/\/[^/]+\/api\/settings\/maintenance(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            enabled: true,
            message: "Ведутся технические работы, депозиты приостановлены.",
          }),
        }),
    );

    await page.goto("/search");
    // ``exact: true`` so the heading locator doesn't also match the
    // body message (which starts with the same words and would trip
    // Playwright's strict-mode resolution to >1 element).
    await expect(
      page.getByText("Технические работы", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Ведутся технические работы, депозиты приостановлены."),
    ).toBeVisible();
  });

  test("stays hidden when /api/settings/maintenance reports disabled", async ({
    page,
  }) => {
    await mockApi(page);

    await page.goto("/search");
    // Wait for the page tree to settle on a stable landmark first,
    // otherwise the banner-absence assertion can race the initial
    // React mount and pass spuriously before the query has even
    // fired.
    await expect(page.getByRole("navigation").first()).toBeVisible();
    await expect(
      page.getByText("Технические работы", { exact: true }),
    ).toHaveCount(0);
  });
});
