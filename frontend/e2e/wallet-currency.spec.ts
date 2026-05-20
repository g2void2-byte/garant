import { test } from "@playwright/test";
import { expect, mockApi, seedSession, USDT_CURRENCY } from "./fixtures";

/**
 * /wallet currency row → /wallet/<code> drill-down e2e.
 *
 * ``WalletPage`` lists each balance row as a ``<Link to="/wallet/<code>">``
 * so users can tap a currency to open the per-currency deposit /
 * withdraw / history page (``WalletCurrencyPage``). The test seeds two
 * balances, clicks the USDT row, and asserts the URL + the
 * per-currency page header rendered.
 */

const TON_CURRENCY = {
  id: 2,
  code: "TON",
  name: "Toncoin",
  network: "TON",
  icon_url: "",
  decimals: 9,
  min_deposit: 1,
  min_withdraw: 1,
};

test.describe("Wallet currency drill-down", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("clicking a balance row opens /wallet/<code>", async ({ page }) => {
    await mockApi(page, {
      currencies: [USDT_CURRENCY, TON_CURRENCY],
      walletBalances: [
        {
          currency: USDT_CURRENCY,
          amount: 42,
          locked: 0,
          total: 42,
          updated_at: null,
        },
        {
          currency: TON_CURRENCY,
          amount: 10,
          locked: 0,
          total: 10,
          updated_at: null,
        },
      ],
    });

    await page.goto("/wallet");
    await expect(
      page.getByRole("heading", { name: "Депозит", exact: true }),
    ).toBeVisible();

    const usdtLink = page.getByRole("link", { name: /Tether/ });
    await expect(usdtLink).toHaveAttribute("href", "/wallet/USDT");

    await usdtLink.click();

    await expect(page).toHaveURL(/\/wallet\/USDT$/);
    await expect(page.getByRole("heading", { name: "Tether" })).toBeVisible();
    await expect(page.getByText("Доступно")).toBeVisible();
  });
});
