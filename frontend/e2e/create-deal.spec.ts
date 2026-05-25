import { test } from "@playwright/test";
import { enterPinPromptDigits, expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — happy-path e2e for ``/deals/new``.
 *
 * ``CreateDealPage`` reads the currency list, lets the user pick a
 * counterparty, amount, description and payment provider, and POSTs
 * ``/api/deals/with-topup`` to mint a pending-topup deal plus invoice.
 * On success it renders the invoice preview. The unit suite covers form validation in
 * isolation; this spec exercises the full Vite-mounted flow.
 */

const NEW_DEAL = {
  id: 4242,
  buyer: "testbuyer",
  seller: "alice",
  sum: 150,
  description: "Custom illustration",
  status: "pending_topup",
  confirm_buyer: false,
  confirm_seller: false,
  role: "buyer" as const,
  created_at: new Date().toISOString(),
  currency_code: "USD",
  amount: 150,
  commission_amount: 7.5,
  commission_paid: false,
  topup_deposit_id: 777,
  topup_invoice: {
    deposit_id: 777,
    pay_url: "https://pay.example/invoice/777",
    total: "157.50",
    topup_principal: "150.00",
    commission: "7.50",
    currency_code: "USD",
    provider: "cryptobot",
    expires_at: null,
  },
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

  test("submits the form, posts /api/deals/with-topup and shows the invoice", async ({
    page,
  }) => {
    await mockApi(page);

    let postedBody: Record<string, unknown> | null = null;
    await page.route(
      /^https?:\/\/[^/]+\/api\/deals\/with-topup(?:\?.*)?$/,
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
            body: JSON.stringify({ deal: NEW_DEAL, invoice: NEW_DEAL.topup_invoice }),
          });
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

    // Audit C1 — the counterparty field is labelled "Продавец"
    // (seller) now that every deal is buyer-initiated; pre-fix it
    // was the generic "Контрагент" that flipped roles via a toggle.
    await page.getByLabel("Продавец (username)").fill("alice");
    // ``Сумма (USD)`` is the dynamic label driven by ``currencyCode``
    // (the create-deal currency picker filters to ``kind === "fiat"``
    // after the fiat-only deposit refactor, so USD is the default).
    await page.getByLabel(/^Сумма \(USD\)/).fill("150");
    await page
      .getByLabel("Описание сделки")
      .fill("Custom illustration");

    await page.getByRole("button", { name: /Создать сделку/ }).click();

    // V12-Ix — PIN re-prompt now gates deal creation. Punch in 1234
    // on the on-screen PIN pad; the mocked ``POST /api/pin/check``
    // (see fixtures) returns a fresh token and the deal POST fires.
    await enterPinPromptDigits(page);

    await expect(page.getByTestId("topup-invoice-preview")).toBeVisible();
    await expect(
      page.getByTestId("topup-invoice-preview").getByText("157.50 USD"),
    ).toBeVisible();

    // POST payload matches what the form collected — keep this loose
    // (only the fields under test) so future fields don't break the
    // assertion.
    expect(postedBody).toMatchObject({
      counterparty: "alice",
      role: "buyer",
      amount: 150,
      description: "Custom illustration",
      currency_code: "USD",
    });
  });

  test("does not POST when required fields are missing", async ({ page }) => {
    await mockApi(page);

    let postCalled = false;
    await page.route(
      /^https?:\/\/[^/]+\/api\/deals\/with-topup(?:\?.*)?$/,
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
