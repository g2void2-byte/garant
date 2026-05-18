import { test } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — happy-path e2e for ``/profile``.
 *
 * The smoke spec already asserts the page mounts and the display name
 * surfaces. This file exercises the rest of the V12-M5 audit's
 * "happy-path per top-level домен" bullet for ProfilePage:
 *
 *  * services tab populates from ``GET /api/services?owner=...`` and
 *    renders a ``<ServiceCard />`` per row;
 *  * reviews tab swaps the body via ``ToggleTabs`` and pulls
 *    ``GET /api/reviews?user=...`` (the rating + author bubble visible);
 *  * an empty reviews response shows the ``EmptyState`` copy.
 *
 * Per-card admin/business logic stays under unit coverage
 * (``ProfilePage.test.tsx``); this spec only verifies that the real
 * Vite-mounted page wires the same data and the tab toggle works.
 */

const MY_SERVICE = {
  id: 42,
  owner_username: "testbuyer",
  title: "Branding pack",
  description: "Logo + business card + letterhead",
  price: 199,
  currency: "USDT",
  status: "active",
  category: {
    id: 1,
    slug: "design",
    name: "Design",
    icon_key: "design",
    services_count: 1,
  },
  created_at: new Date(Date.now() - 86_400_000).toISOString(),
};

const MY_REVIEW = {
  id: 7,
  deal_id: 17,
  author_username: "alice",
  target_username: "testbuyer",
  rating: 5,
  text: "Отличный продавец, всё чётко!",
  created_at: new Date(Date.now() - 60_000).toISOString(),
};

test.describe("Profile page", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("renders own services on the services tab, switches to reviews tab and surfaces the rating", async ({
    page,
  }) => {
    await mockApi(page, { services: [MY_SERVICE] });
    // ``useReviews(me.username)`` calls ``/api/reviews?user=...``. The
    // catch-all in ``mockApi`` would 200-with-empty-object the request,
    // but the hook expects an array — override with a one-row list so
    // the reviews tab has a deterministic row to assert on.
    await page.route(
      /^https?:\/\/[^/]+\/api\/reviews(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MY_REVIEW]),
        }),
    );

    await page.goto("/profile");
    // ProfileHeader puts the display name in an h1; assert against the
    // role-restricted match so we don't accidentally bind to a
    // ``BottomNav`` tab label that contains the same word.
    await expect(
      page.getByRole("heading", { name: "TestBuyer" }),
    ).toBeVisible();

    // Services tab is the default; ServiceCard renders the title.
    await expect(
      page.getByRole("heading", { name: "Branding pack" }),
    ).toBeVisible();

    // Switch to "Отзывы" — ToggleTabs renders as accessible buttons
    // labelled by the option label, with the count appended. Match by
    // a leading-word regex so the assertion survives count drift.
    await page.getByRole("button", { name: /^Отзывы/ }).click();

    // Review row surfaces the star + rating + author handle.
    await expect(page.getByText("★ 5.0")).toBeVisible();
    await expect(page.getByText("от @alice")).toBeVisible();
    await expect(
      page.getByText("Отличный продавец, всё чётко!"),
    ).toBeVisible();
  });

  test("shows the empty-reviews state when the user has no reviews yet", async ({
    page,
  }) => {
    await mockApi(page);
    await page.route(
      /^https?:\/\/[^/]+\/api\/reviews(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        }),
    );

    await page.goto("/profile");
    await page.getByRole("button", { name: /^Отзывы/ }).click();
    await expect(page.getByText("Отзывов нет")).toBeVisible();
    await expect(
      page.getByText(/Завершайте сделки, чтобы получить отзывы/),
    ).toBeVisible();
  });
});
