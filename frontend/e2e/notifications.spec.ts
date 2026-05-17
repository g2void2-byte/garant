import { test } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — notification counter badge end-to-end.
 *
 * ``<BottomNav />`` reads ``useNotificationCounters`` and renders a
 * red pill on the Bell tab when ``counters.unread > 0`` (capped at
 * ``99+``). The fixture default returns ``{ unread: 0 }`` so every
 * other spec keeps the badge hidden; here we exercise the *visible*
 * path by overriding the route to return ``unread: 5`` and the *cap*
 * path with ``unread: 240``.
 */
test.describe("Notifications badge", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("renders the unread count on the bell tab when unread > 0", async ({
    page,
  }) => {
    await mockApi(page);
    await page.route(
      /^https?:\/\/[^/]+\/api\/notifications\/counters(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ unread: 5, by_type: {} }),
        }),
    );

    await page.goto("/search");

    const bellTab = page.getByRole("link", { name: /Оповещения/ });
    await expect(bellTab).toBeVisible();
    // ``5`` is exact-matched so the assertion can't accidentally
    // attach to a digit appearing elsewhere on the page (e.g. a
    // currency amount). Scoping to the bell tab also guards against
    // the same.
    await expect(bellTab.getByText("5", { exact: true })).toBeVisible();
  });

  test("caps the unread badge at '99+' when there are more than 99 unread items", async ({
    page,
  }) => {
    await mockApi(page);
    await page.route(
      /^https?:\/\/[^/]+\/api\/notifications\/counters(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ unread: 240, by_type: {} }),
        }),
    );

    await page.goto("/search");

    const bellTab = page.getByRole("link", { name: /Оповещения/ });
    await expect(bellTab.getByText("99+")).toBeVisible();
  });

  test("hides the badge entirely when there are no unread items", async ({
    page,
  }) => {
    await mockApi(page);

    await page.goto("/search");

    const bellTab = page.getByRole("link", { name: /Оповещения/ });
    await expect(bellTab).toBeVisible();
    // The ``relative`` ``<span>`` that hosts the bell icon also hosts
    // the badge when unread > 0. With ``unread: 0`` the badge is
    // conditionally not rendered at all, so it must have *zero*
    // matching elements — not just be off-screen.
    await expect(bellTab.locator(".bg-danger")).toHaveCount(0);
  });
});
