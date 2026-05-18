import { test } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — happy-path e2e for ``/deals`` and ``/deals/:id``.
 *
 * The smoke spec asserts the list mounts and a row link is reachable;
 * this file goes one step further:
 *
 *  * the role toggle re-fetches with ``?role=<role>``;
 *  * clicking a deal row navigates to ``/deals/:id`` and the detail
 *    page surfaces the amount, status, role and counterparty handle.
 *
 * Per-action business logic (accept / decline / cancel / debate /
 * resolve / review) is covered by ``DealDetailPage.test.tsx``; this
 * spec only confirms the real Vite-mounted detail page wires the
 * ``useDeal(id)`` response into the layout.
 */

const ACTIVE_DEAL = {
  id: 17,
  buyer: "testbuyer",
  seller: "alice",
  sum: 250,
  description: "Logo design package",
  pay_comission: "buyer",
  status: "in_progress",
  confirm_buyer: false,
  confirm_seller: false,
  role: "buyer" as const,
  created_at: new Date(Date.now() - 60 * 60_000).toISOString(),
  currency_code: "USDT",
  amount: 250,
  commission_amount: 12.5,
  in_progress_at: null,
  completed_at: null,
  cancellation_initiator: null,
  cancellation_reason: null,
  cancellation_requested_at: null,
  arbitration_initiator: null,
  arbitration_reason: null,
  arbitration_resolved_by: null,
  arbitration_resolution: null,
  arbitration_resolved_at: null,
};

test.describe("Deals list + detail", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("role toggle re-fetches deals with ?role=buyer", async ({ page }) => {
    await mockApi(page, { deals: [ACTIVE_DEAL] });

    const seenRoles: (string | null)[] = [];
    await page.route(
      /^https?:\/\/[^/]+\/api\/deals(?:\?.*)?$/,
      (route) => {
        const url = new URL(route.request().url());
        // Defer ``/api/deals/<id>`` and POST mutations to other
        // handlers / the catch-all.
        if (/\/deals\/\d+/.test(url.pathname)) return route.fallback();
        if (route.request().method() !== "GET") return route.fallback();
        seenRoles.push(url.searchParams.get("role"));
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([ACTIVE_DEAL]),
        });
      },
    );

    await page.goto("/deals");
    await expect(
      page.getByRole("heading", { name: "Ваши сделки" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Logo design package/ }),
    ).toBeVisible();

    // Click "Покупки" — the page should re-fetch with ?role=buyer.
    await page.getByRole("button", { name: /^Покупки/ }).click();
    // ``useDeals`` swaps the queryKey so a fresh request fires; poll
    // until we see the new role in the recorded URLs.
    await expect.poll(() => seenRoles).toContain("buyer");
  });

  test("clicking a deal row navigates to the detail page and renders the amount + status + counterparty", async ({
    page,
  }) => {
    await mockApi(page, { deals: [ACTIVE_DEAL] });
    await page.route(
      /^https?:\/\/[^/]+\/api\/deals\/17(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(ACTIVE_DEAL),
        }),
    );

    await page.goto("/deals");
    await page.getByRole("link", { name: /Logo design package/ }).click();

    await expect(page).toHaveURL(/\/deals\/17$/);
    await expect(
      page.getByRole("heading", { name: "Сделка #17" }),
    ).toBeVisible();

    // ``formatAmount`` uses ``toLocaleString`` with
    // ``minimumFractionDigits: 0`` so an integer amount renders as
    // "250", not "250.00". Keep the assertion tolerant of either.
    await expect(page.getByText(/250(?:\.\d+)?\s+USDT/).first()).toBeVisible();

    // Status label + counterparty handle confirm the right deal loaded.
    // ``В работе`` is rendered both in the Header subtitle and the
    // status row beneath the amount, so anchor on the role-targeted
    // status row text rather than counting nodes.
    await expect(
      page.getByText("В работе", { exact: true }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "@alice" }),
    ).toBeVisible();
    // For a buyer-side ``in_progress`` deal the page renders the
    // confirm-execution CTA in the action grid.
    await expect(
      page.getByRole("button", { name: /Подтвердить исполнение/ }),
    ).toBeVisible();
  });
});
