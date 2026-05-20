import { test } from "@playwright/test";
import { enterPinPromptDigits, expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — withdraw/deposit e2e (withdraw half).
 *
 * ``/wallet/withdraw`` reads ``useWalletBalances`` to populate the
 * currency picker, pre-selects the first non-zero entry (USDT in
 * fixtures), and on submit calls ``POST /api/wallet/withdrawals``.
 * Successful submit fires a green "Заявка отправлена" toast; client-
 * side validation surfaces error toasts before the request is made.
 *
 * The previous smoke spec only covered the /wallet landing page —
 * neither the navigation into the withdraw subpage nor the
 * mutation-shaped POST + success-toast path was exercised. This spec
 * closes that gap.
 */
test.describe("Wallet withdraw", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("withdraws USDT happy-path: nav -> fill -> submit -> success toast", async ({
    page,
  }) => {
    await mockApi(page);

    // Override the catch-all ``wallet/withdrawals`` handler so the
    // POST gets a proper ``WalletWithdrawalDto`` instead of the
    // default GET-list ``[]``. Registered *after* ``mockApi`` so it
    // wins per the last-registered contract used elsewhere in the
    // e2e suite.
    await page.route(
      /^https?:\/\/[^/]+\/api\/wallet\/withdrawals(?:\?.*)?$/,
      async (route) => {
        if (route.request().method() === "POST") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              id: 42,
              currency_code: "USDT",
              amount: 123.45,
              address: "TXYZ1234567890",
              status: "pending",
              created_at: new Date().toISOString(),
            }),
          });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    // Land on /wallet, confirm we're seeing the deposit tiles, then
    // click into the withdraw flow.
    await page.goto("/wallet");
    await expect(
      page.getByRole("heading", { name: "Депозит", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Вывести\s+депозит/ }).click();

    // Page header confirms the subroute mounted.
    await expect(
      page.getByRole("heading", { name: "Вывести депозит" }),
    ).toBeVisible();

    // Click "Всё" to copy the full balance into the amount input,
    // then fill the address (no auto-fill).
    await page.getByRole("button", { name: "Всё" }).click();
    await expect(page.getByLabel("Сумма")).toHaveValue("123.45");
    await page.getByLabel("Адрес кошелька").fill("TXYZ1234567890");

    // Submit and assert the success toast surfaces. ``Toast`` renders
    // both the title and the body, so the title is enough to scope.
    await page.getByRole("button", { name: /Запросить вывод/ }).click();
    // V12-Ix — PIN re-prompt now gates withdrawals. Punch in 1234 on
    // the on-screen PIN pad; the mocked ``POST /api/pin/check`` (see
    // fixtures) returns a fresh token and the withdrawal POST fires.
    await enterPinPromptDigits(page);
    await expect(page.getByText("Заявка отправлена")).toBeVisible();
  });

  test("Card method opens info modal with a deeplink to the admin", async ({
    page,
  }) => {
    await mockApi(page);
    await page.goto("/wallet/withdraw");
    await expect(
      page.getByRole("heading", { name: "Вывести депозит" }),
    ).toBeVisible();

    await page.getByRole("button", { name: /^Карта$/ }).click();
    await expect(
      page.getByRole("heading", { name: /Вывод на карту/ }),
    ).toBeVisible();
    const adminBtn = page.getByRole("button", { name: /Написать админу/ });
    await expect(adminBtn).toBeEnabled();
  });

  test("rejects empty address with an error toast before posting", async ({
    page,
  }) => {
    await mockApi(page);
    let postCalled = false;
    await page.route(
      /^https?:\/\/[^/]+\/api\/wallet\/withdrawals(?:\?.*)?$/,
      async (route) => {
        if (route.request().method() === "POST") {
          postCalled = true;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    await page.goto("/wallet/withdraw");
    await expect(
      page.getByRole("heading", { name: "Вывести депозит" }),
    ).toBeVisible();

    // Fill the amount but leave the address blank — the client-side
    // guard in ``submit()`` must short-circuit before the POST fires.
    await page.getByRole("button", { name: "Всё" }).click();
    await page.getByRole("button", { name: /Запросить вывод/ }).click();
    await expect(page.getByText("Введите адрес кошелька")).toBeVisible();
    expect(postCalled).toBe(false);
  });
});
