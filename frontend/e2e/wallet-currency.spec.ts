import { test } from "@playwright/test";
import { expect, mockApi, seedSession, USD_CURRENCY } from "./fixtures";

/**
 * /wallet currency row → /wallet/<code> drill-down e2e.
 *
 * ``WalletPage`` lists each balance row as a ``<Link to="/wallet/<code>">``
 * so users can tap a currency to open the per-currency deposit /
 * withdraw / history page (``WalletCurrencyPage``). After the
 * fiat-only deposit refactor only ``kind === "fiat"`` rows surface,
 * so the test drills into the USD row (the default fiat fixture)
 * and asserts the URL + the per-currency page header rendered.
 */

const UAH_CURRENCY = {
  id: 101,
  code: "UAH",
  name: "Українська гривня",
  network: "",
  icon_url: "",
  decimals: 2,
  min_deposit: 50,
  min_withdraw: 50,
  kind: "fiat" as const,
};

test.describe("Wallet currency drill-down", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("clicking a balance row opens /wallet/<code>", async ({ page }) => {
    await mockApi(page, {
      currencies: [USD_CURRENCY, UAH_CURRENCY],
      walletBalances: [
        {
          currency: USD_CURRENCY,
          amount: 42,
          locked: 0,
          total: 42,
          updated_at: null,
          // Audit M-7 — string mirrors required by the
          // ``WalletBalanceDto`` contract; the WithdrawForm reads
          // ``balance?.amount_str`` for the "Всё" button.
          amount_str: "42",
          locked_str: "0",
          total_str: "42",
        },
        {
          currency: UAH_CURRENCY,
          amount: 10,
          locked: 0,
          total: 10,
          updated_at: null,
          amount_str: "10",
          locked_str: "0",
          total_str: "10",
        },
      ],
    });

    await page.goto("/wallet");
    await expect(
      page.getByRole("heading", { name: "Кошелёк", exact: true }),
    ).toBeVisible();

    const usdLink = page.getByRole("link", { name: /US Dollar/ });
    await expect(usdLink).toHaveAttribute("href", "/wallet/USD");

    await usdLink.click();

    await expect(page).toHaveURL(/\/wallet\/USD$/);
    await expect(page.getByRole("heading", { name: "US Dollar" })).toBeVisible();
    await expect(page.getByText("Доступно")).toBeVisible();
  });
});
