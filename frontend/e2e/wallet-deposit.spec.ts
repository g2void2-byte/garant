import { test } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — withdraw/deposit e2e (deposit half).
 *
 * ``/wallet/deposit`` reads ``useCurrencies`` to populate the picker
 * and ``useWalletBalances`` for the "Доступно" hint. The first
 * currency is auto-selected; ``amount`` is auto-seeded to
 * ``min_deposit``. Submit calls ``POST /api/wallet/deposits`` which
 * returns a ``WalletDepositDto`` carrying a CryptoBot ``pay_url``
 * — the success path fires a "Счёт создан" toast and routes the
 * Telegram link through ``openTelegramLink``.
 *
 * The previous smoke spec covered the /wallet landing tile only;
 * neither the deposit subpage nor the mutation-shaped POST + toast
 * path was exercised. Together with the matching withdraw spec this
 * closes the V12-M5 ``withdraw/deposit`` bullet at the e2e layer.
 */

const USDT_CURRENCY = {
  id: 1,
  code: "USDT",
  name: "Tether",
  network: "TRC20",
  icon_url: "",
  decimals: 2,
  min_deposit: 5,
  min_withdraw: 1,
};

async function mockCurrencies(page: Parameters<typeof seedSession>[0]) {
  await page.route(
    /^https?:\/\/[^/]+\/api\/wallet\/currencies(?:\?.*)?$/,
    (r) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([USDT_CURRENCY]),
      }),
  );
}

test.describe("Wallet deposit", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("creates a USDT invoice happy-path: nav -> auto-fill -> submit -> success toast", async ({
    page,
  }) => {
    await mockApi(page);
    await mockCurrencies(page);

    // Method-aware override so the POST returns a proper
    // ``WalletDepositDto`` while GET keeps the default empty list.
    // Registered after ``mockApi`` so it wins per the
    // last-registered contract used elsewhere in the e2e suite.
    await page.route(
      /^https?:\/\/[^/]+\/api\/wallet\/deposits(?:\?.*)?$/,
      async (route) => {
        if (route.request().method() === "POST") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              id: 99,
              currency: USDT_CURRENCY,
              amount: 5,
              status: "pending",
              pay_url: "",
              invoice_id: "invoice-stub",
              created_at: new Date().toISOString(),
              paid_at: null,
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

    // The mocked DTO intentionally has an empty ``pay_url`` so the
    // ``if (dep.pay_url) openTelegramLink(dep.pay_url)`` branch is
    // skipped. Outside the real Telegram WebView, that branch falls
    // through to ``window.open(url, "_blank")``, which headless
    // Chromium downgrades to a same-window navigation — that would
    // yank the test off /wallet/deposit before the success toast
    // rendered. The unit suite already covers the ``pay_url``-set
    // branch (`WalletDepositPage.test.tsx` mocks `openTelegramLink`),
    // so we don't lose coverage by skipping it here at the e2e
    // layer; we just exercise the same toast and the underlying
    // POST roundtrip.
    await page.goto("/wallet/deposit");
    await expect(
      page.getByRole("heading", { name: "Пополнение депозита" }),
    ).toBeVisible();

    // ``useEffect`` seeds the amount to ``min_deposit`` (5) once the
    // currency resolves — assert it surfaced before submit.
    await expect(page.getByLabel("Сумма")).toHaveValue("5");

    await page.getByRole("button", { name: /Пополнить депозит/ }).click();
    await expect(page.getByText("Счёт создан")).toBeVisible();
  });

  test("rejects a zero amount with an error toast before posting", async ({
    page,
  }) => {
    await mockApi(page);
    await mockCurrencies(page);
    let postCalled = false;
    await page.route(
      /^https?:\/\/[^/]+\/api\/wallet\/deposits(?:\?.*)?$/,
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

    await page.goto("/wallet/deposit");
    await expect(
      page.getByRole("heading", { name: "Пополнение депозита" }),
    ).toBeVisible();

    // Wait for the auto-fill to settle, then clear the amount so the
    // client-side ``Number.isFinite || value <= 0`` guard trips.
    await expect(page.getByLabel("Сумма")).toHaveValue("5");
    await page.getByLabel("Сумма").fill("0");
    await page.getByRole("button", { name: /Пополнить депозит/ }).click();

    await expect(page.getByText("Введите корректную сумму")).toBeVisible();
    expect(postCalled).toBe(false);
  });
});
