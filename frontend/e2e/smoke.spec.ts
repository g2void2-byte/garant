import { test } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

test.describe("App smoke", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
    await mockApi(page);
  });

  test("redirects / to /search and renders the search page", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/search$/);
    // Bottom navigation is the most stable global landmark across
    // pages — assert it shows up so we know the React tree mounted.
    const bottomNav = page.getByRole("navigation").first();
    await expect(bottomNav).toBeVisible();
  });

  test("loads the deals page from the bottom nav", async ({ page }) => {
    await page.goto("/deals");
    await expect(page.getByRole("link", { name: /Logo design package/ })).toBeVisible();
  });

  test("loads the wallet page", async ({ page }) => {
    await page.goto("/wallet");
    await expect(page.getByRole("heading", { name: "Депозит", exact: true })).toBeVisible();
    // ``WalletPage`` filters balances to ``kind === "fiat"`` after
    // the fiat-only deposit refactor, so the USD row from the
    // default fixture is what surfaces (Tether is hidden).
    await expect(page.getByText("US Dollar")).toBeVisible();
    await expect(page.getByText(/123\.45 USD/).first()).toBeVisible();
  });

  test("loads the profile page", async ({ page }) => {
    await page.goto("/profile");
    // Wait for the page tree to settle. The profile page reads
    // ``useMe()`` which we mock above, so the display name should
    // surface somewhere on the page.
    await expect(page.getByText("TestBuyer").first()).toBeVisible();
  });
});
