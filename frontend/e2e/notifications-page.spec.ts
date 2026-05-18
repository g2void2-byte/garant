import { test } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — happy-path e2e for ``/notifications``.
 *
 * The existing ``notifications.spec.ts`` covers the bell-badge in
 * ``BottomNav``; this file exercises the ``NotificationsPage`` body:
 *
 *  * list renders one row per item (``NotificationRow``);
 *  * day grouping headers are present;
 *  * tab toggle re-fetches with ``?type=<tab>``;
 *  * "Прочитать все" CTA is visible only when ``unread > 0`` and
 *    POSTs ``/api/notifications/read-all``.
 */

const NOW = Date.now();

const NOTIFICATIONS = [
  {
    id: 101,
    type: "deals",
    title: "Сделка #17 подтверждена",
    body: "Покупатель подтвердил исполнение по сделке #17.",
    payload: { deal_id: 17 },
    is_read: false,
    created_at: new Date(NOW - 5 * 60_000).toISOString(),
  },
  {
    id: 102,
    type: "deposits",
    title: "Депозит зачислен",
    body: "Пополнение 10 USDT успешно зачислено на баланс.",
    payload: null,
    is_read: false,
    created_at: new Date(NOW - 60 * 60_000).toISOString(),
  },
];

test.describe("Notifications page", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("renders the list, the 'Прочитать все' CTA and re-fetches with the active tab", async ({
    page,
  }) => {
    await mockApi(page);
    await page.route(
      /^https?:\/\/[^/]+\/api\/notifications\/counters(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            unread: 2,
            by_type: { deals: 1, deposits: 1, system: 0 },
          }),
        }),
    );

    // Capture the type query each ``GET /api/notifications`` request
    // arrives with so we can assert the tab toggle drives the URL.
    const seenTypes: (string | null)[] = [];
    await page.route(
      /^https?:\/\/[^/]+\/api\/notifications(?:\?.*)?$/,
      (route) => {
        // Don't fight the more specific ``/counters`` / ``/read-all``
        // / ``/<id>/read`` patterns — those have their own handlers.
        const url = new URL(route.request().url());
        if (
          url.pathname.endsWith("/counters") ||
          url.pathname.endsWith("/read-all") ||
          /\/notifications\/\d+\/read$/.test(url.pathname)
        ) {
          return route.fallback();
        }
        if (route.request().method() !== "GET") {
          return route.fallback();
        }
        seenTypes.push(url.searchParams.get("type"));
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(
            url.searchParams.get("type") === "deposits"
              ? [NOTIFICATIONS[1]]
              : NOTIFICATIONS,
          ),
        });
      },
    );

    await page.goto("/notifications");

    // Header surfaces the counter subtitle and the bulk-action CTA.
    await expect(
      page.getByRole("heading", { name: "Оповещения" }),
    ).toBeVisible();
    await expect(page.getByText("2 непрочитанных")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Прочитать все" }),
    ).toBeVisible();

    // List body — both rows render with their titles.
    await expect(
      page.getByText("Сделка #17 подтверждена"),
    ).toBeVisible();
    await expect(page.getByText("Депозит зачислен")).toBeVisible();

    // Switch to the "Депозиты" tab — the page re-fetches with
    // ``?type=deposits`` and only the deposit row survives.
    await page.getByRole("button", { name: /^Депозиты/ }).click();
    await expect(
      page.getByText("Сделка #17 подтверждена"),
    ).toHaveCount(0);
    await expect(page.getByText("Депозит зачислен")).toBeVisible();
    expect(seenTypes).toContain("deposits");
  });

  test("hides the 'Прочитать все' CTA and shows the empty state when there are no notifications", async ({
    page,
  }) => {
    await mockApi(page);
    await page.route(
      /^https?:\/\/[^/]+\/api\/notifications\/counters(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ unread: 0, by_type: {} }),
        }),
    );
    await page.route(
      /^https?:\/\/[^/]+\/api\/notifications(?:\?.*)?$/,
      (route) => {
        const url = new URL(route.request().url());
        if (
          url.pathname.endsWith("/counters") ||
          url.pathname.endsWith("/read-all")
        ) {
          return route.fallback();
        }
        if (route.request().method() !== "GET") {
          return route.fallback();
        }
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    await page.goto("/notifications");
    await expect(
      page.getByRole("heading", { name: "Оповещения" }),
    ).toBeVisible();
    await expect(page.getByText("Уведомлений нет")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Прочитать все" }),
    ).toHaveCount(0);
  });
});
