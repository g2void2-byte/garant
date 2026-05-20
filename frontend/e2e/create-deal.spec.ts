import { test } from "@playwright/test";
import { enterPinPromptDigits, expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — happy-path e2e for ``/deals/new``.
 *
 * ``CreateDealPage`` reads the currency list, lets the user pick a
 * role, counterparty, amount, description and commission split, and
 * POSTs ``/api/deals`` to mint a new deal. On success it
 * ``navigate(`/deals/${id}`)`` so the user lands on the brand-new
 * deal detail page. The unit suite covers form validation in
 * isolation; this spec exercises the full Vite-mounted flow.
 */

const NEW_DEAL = {
  id: 4242,
  buyer: "testbuyer",
  seller: "alice",
  sum: 150,
  description: "Custom illustration",
  pay_comission: "buyer",
  status: "pending_confirmation",
  confirm_buyer: false,
  confirm_seller: false,
  role: "buyer" as const,
  created_at: new Date().toISOString(),
  currency_code: "USDT",
  amount: 150,
  commission_amount: 7.5,
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

test.describe("Create-deal page", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("submits the form, posts /api/deals and navigates to the new deal", async ({
    page,
  }) => {
    await mockApi(page);

    let postedBody: Record<string, unknown> | null = null;
    await page.route(
      /^https?:\/\/[^/]+\/api\/deals(?:\?.*)?$/,
      async (route) => {
        const req = route.request();
        if (req.method() === "POST") {
          try {
            postedBody = req.postDataJSON() as Record<string, unknown>;
          } catch {
            postedBody = null;
          }
          return route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(NEW_DEAL),
          });
        }
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );
    // ``useCreateDeal``'s ``onSuccess`` invalidates the deal-detail
    // query; serve the new deal so the post-navigation page renders.
    await page.route(
      /^https?:\/\/[^/]+\/api\/deals\/4242(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(NEW_DEAL),
        }),
    );
    // ``DealDetailPage`` reads ``useReviews(otherUser)`` and renders
    // ``DealChatPanel`` (``useDealMessages(id)``) once it lands on
    // /deals/4242; the catch-all returns ``{}`` for unknown endpoints
    // and the hooks would then call ``.some(...)`` / ``.map(...)`` on
    // an object — ``?.`` doesn't short-circuit on ``{}`` — throwing
    // and tripping the ErrorBoundary before the heading renders.
    await page.route(
      /^https?:\/\/[^/]+\/api\/reviews(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        }),
    );
    await page.route(
      /^https?:\/\/[^/]+\/api\/deals\/\d+\/messages(?:\?.*)?$/,
      (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        }),
    );

    await page.goto("/deals/new");
    await expect(
      page.getByRole("heading", { name: "Новая сделка" }),
    ).toBeVisible();

    await page.getByLabel("Контрагент (username)").fill("alice");
    // ``Сумма (USDT)`` is the dynamic label driven by ``currencyCode``.
    await page.getByLabel(/^Сумма \(USDT\)/).fill("150");
    await page
      .getByLabel("Описание сделки")
      .fill("Custom illustration");

    await page.getByRole("button", { name: /Создать сделку/ }).click();

    // V12-Ix — PIN re-prompt now gates deal creation. Punch in 1234
    // on the on-screen PIN pad; the mocked ``POST /api/pin/check``
    // (see fixtures) returns a fresh token and the deal POST fires.
    await enterPinPromptDigits(page);

    // Reached the new deal detail page.
    await expect(page).toHaveURL(/\/deals\/4242$/);
    await expect(
      page.getByRole("heading", { name: "Сделка #4242" }),
    ).toBeVisible();

    // POST payload matches what the form collected — keep this loose
    // (only the fields under test) so future fields don't break the
    // assertion.
    expect(postedBody).toMatchObject({
      counterparty: "alice",
      role: "buyer",
      amount: 150,
      description: "Custom illustration",
      pay_comission: "buyer",
      currency_code: "USDT",
    });
  });

  test("does not POST when required fields are missing", async ({ page }) => {
    await mockApi(page);

    let postCalled = false;
    await page.route(
      /^https?:\/\/[^/]+\/api\/deals(?:\?.*)?$/,
      async (route) => {
        if (route.request().method() === "POST") {
          postCalled = true;
        }
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    await page.goto("/deals/new");
    await expect(
      page.getByRole("heading", { name: "Новая сделка" }),
    ).toBeVisible();
    // All fields empty — the inline ``submit`` guard
    // (``!counterparty || !description || !Number.isFinite(amount) ||
    // amount <= 0``) trips before any network call.
    await page.getByRole("button", { name: /Создать сделку/ }).click();

    // ``CreateDealPage`` doesn't render an explicit error banner for
    // the empty-form path (it just haptic-errors); the contract that
    // matters here is "no network call left the client".
    await page.waitForTimeout(150);
    expect(postCalled).toBe(false);
    await expect(page).toHaveURL(/\/deals\/new$/);
  });
});
