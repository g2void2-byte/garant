import { test } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — admin-routes e2e.
 *
 * Every admin page calls ``useAdminRedirect()`` which reads
 * ``useMe().is_admin`` and ``navigate("/search", { replace: true })``
 * inside a ``useEffect`` when the visitor isn't authorised. The
 * pages return ``null`` until the redirect lands.
 *
 * The two-case matrix below exercises both halves of that hook:
 *
 *  * non-admin (default ``mockApi`` ``me``) hitting /admin/dashboard
 *    gets bounced to /search and never sees the admin scaffolding;
 *  * admin (``is_admin: true`` override) hitting the same path
 *    stays on /admin/dashboard, renders the "Админ-панель" header,
 *    and surfaces the KPI tiles from the mocked
 *    /api/admin/dashboard response.
 *
 * Per-page admin business logic is exhaustively covered by the
 * ``AdminXxxPage.test.tsx`` RTL suites — this spec only verifies
 * the *routing guard* + the *real Vite mount* path that the audit's
 * V12-M5 ``/admin/*`` bullet calls out as missing at the e2e layer.
 */

const ADMIN_ME = {
  id: 111,
  user_id: 111,
  username: "testadmin",
  display_name: "TestAdmin",
  photo_url: null,
  balance: 0,
  admin: 1,
  prefix: null,
  is_admin: true,
  is_arbiter: false,
  is_vip: false,
  is_banned: false,
  is_frozen: false,
  good: 0,
  bad: 0,
  deposit: 0,
  rating: 0,
  reviews_count: 0,
  deals_count: 0,
  deals_sum: 0,
  online: true,
  banner_url: null,
  description: "",
  forums: [],
  is_hidden_profile: false,
};

const ADMIN_DASHBOARD = {
  total_users: 42,
  new_users_24h: 3,
  new_users_7d: 7,
  online_users_5min: 5,
  total_deals: 17,
  open_deals: 4,
  open_arbitration: 1,
  total_services: 9,
  active_services: 6,
  banned_users: 0,
  frozen_users: 0,
  admins: 2,
  arbiters: 1,
  vips: 3,
};

test.describe("Admin routes guard", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("non-admin visitors are redirected from /admin/dashboard to /search", async ({
    page,
  }) => {
    // Default ``mockApi`` ``me`` has ``is_admin: false``, so the
    // ``useAdminRedirect`` ``useEffect`` should fire and push us
    // to /search.
    await mockApi(page);

    await page.goto("/admin/dashboard");

    // ``navigate(..., { replace: true })`` runs after the React
    // tree settles — wait for the URL to flip before asserting on
    // landing-page content. Search-page heading "Профиль" /
    // bottom-nav landmark is the deterministic post-redirect
    // signal.
    await page.waitForURL(/\/search$/);
    await expect(
      page.getByRole("link", { name: /Оповещения/ }),
    ).toBeVisible();

    // And the admin scaffolding never flashed: ``Админ-панель`` is
    // the page's `<Header title>` value — it shouldn't be in the
    // DOM after the redirect resolved.
    await expect(page.getByText("Админ-панель")).toHaveCount(0);
  });

  test("admin visitors land on /admin/dashboard and see the KPI scaffolding", async ({
    page,
  }) => {
    await mockApi(page, { me: ADMIN_ME });
    await page.route(
      /^https?:\/\/[^/]+\/api\/admin\/dashboard(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(ADMIN_DASHBOARD),
        }),
    );

    await page.goto("/admin/dashboard");

    // Header surfaces — guard let us through.
    await expect(
      page.getByRole("heading", { name: "Админ-панель" }),
    ).toBeVisible();
    // KPI label confirms ``useAdminDashboard`` data wired through.
    await expect(page.getByText("Всего", { exact: true }).first()).toBeVisible();
    // Section heading confirms the rest of the dashboard rendered
    // (rather than the loading skeleton or error fallback).
    await expect(page.getByText("Пользователи")).toBeVisible();
  });
});
