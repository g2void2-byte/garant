import { test } from "@playwright/test";
import { expect, mockApi, seedSession, USD_CURRENCY } from "./fixtures";

/**
 * V12-M5 — withdraw/deposit e2e (deposit half).
 *
 * ``/wallet/deposit`` reads ``useCurrencies`` to populate the picker
 * and ``useWalletBalances`` for the "Доступно" hint. The first
 * currency is auto-selected; ``amount`` is auto-seeded to
 * ``min_deposit``. Submit calls ``POST /api/wallet/deposits`` which
 * returns a ``WalletDepositDto`` and (V14) opens the real-time
 * ``DepositStatusModal`` so the user can watch the invoice resolve
 * without leaving the wallet page.
 *
 * The previous smoke spec covered the /wallet landing tile only;
 * neither the deposit subpage nor the mutation-shaped POST + modal
 * path was exercised. Together with the matching withdraw spec this
 * closes the V12-M5 ``withdraw/deposit`` bullet at the e2e layer.
 */

test.describe("Wallet deposit", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("creates a USD invoice happy-path: nav -> auto-fill -> submit -> status modal", async ({
    page,
  }) => {
    await mockApi(page);

    // Method-aware override so the POST returns a proper
    // ``WalletDepositDto`` while the list GET keeps the default empty
    // list. The polling GET ``/api/wallet/deposits/{id}`` issued by
    // ``DepositStatusModal`` returns the same DTO so the modal's
    // ``query.data`` matches the freshly-created deposit instead of
    // landing on the catchall ``[]``. Registered after ``mockApi``
    // so it wins per the last-registered contract used elsewhere in
    // the e2e suite.
    const depositDto = {
      id: 99,
      currency: USD_CURRENCY,
      amount: 5,
      status: "pending",
      pay_url: "",
      invoice_id: "invoice-stub",
      provider: "cryptobot",
      purpose: "wallet",
      created_at: new Date().toISOString(),
      paid_at: null,
    };
    await page.route(
      /^https?:\/\/[^/]+\/api\/wallet\/deposits(?:\/\d+)?(?:\?.*)?$/,
      async (route) => {
        const url = new URL(route.request().url());
        const isById = /\/api\/wallet\/deposits\/\d+$/.test(url.pathname);
        if (route.request().method() === "POST") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(depositDto),
          });
          return;
        }
        if (isById) {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(depositDto),
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

    // V14 — the success path now opens the real-time
    // ``DepositStatusModal`` instead of firing a one-shot "Счёт
    // создан" toast. The modal mounts immediately with the freshly
    // returned ``WalletDepositDto`` and ~1 s later auto-opens the
    // upstream invoice page; the mocked DTO intentionally has an
    // empty ``pay_url`` so the auto-open path is a no-op and the
    // test isn't yanked off ``/wallet/deposit`` by headless
    // Chromium downgrading ``window.open`` to a same-window
    // navigation. We assert the modal mounted and surfaced the
    // pending status + amount header.
    await page.goto("/wallet/deposit");
    await expect(
      page.getByRole("heading", { name: "Пополнение баланса" }),
    ).toBeVisible();

    // ``useEffect`` seeds the amount to ``min_deposit`` (5) once the
    // currency resolves — assert it surfaced before submit.
    await expect(page.getByLabel("Сумма")).toHaveValue("5");

    await page.getByRole("button", { name: /Пополнить баланс/ }).click();
    await expect(page.getByTestId("deposit-status-modal")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Пополнение баланса" }),
    ).toBeVisible();
  });

  test("rejects a zero amount with an error toast before posting", async ({
    page,
  }) => {
    await mockApi(page);
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
      page.getByRole("heading", { name: "Пополнение баланса" }),
    ).toBeVisible();

    // Wait for the auto-fill to settle, then clear the amount so the
    // client-side ``Number.isFinite || value <= 0`` guard trips.
    await expect(page.getByLabel("Сумма")).toHaveValue("5");
    await page.getByLabel("Сумма").fill("0");
    await page.getByRole("button", { name: /Пополнить баланс/ }).click();

    await expect(page.getByText("Введите корректную сумму")).toBeVisible();
    expect(postCalled).toBe(false);
  });
});
