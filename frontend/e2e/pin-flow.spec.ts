import { test, type Page } from "@playwright/test";
import { expect, mockApi } from "./fixtures";

/**
 * V12-M5 — PIN-flow e2e.
 *
 * ``PinGate`` lazy-loads ``PinPage`` whenever ``hasValidPinToken()``
 * returns false. ``PinPage`` then walks the user through one of six
 * Mode states; this spec covers the most-trodden two:
 *
 *  * ``check`` happy-path: existing PIN, user types correct digits,
 *    backend returns ``{ token, expires_at }``, ``setPinToken`` fires
 *    the ``garant:pin-token-changed`` event, ``PinGate`` re-renders
 *    with ``unlocked=true``, the protected app appears.
 *  * ``check`` failure: existing PIN, user types wrong digits, the
 *    backend returns 401 with a server message, the error toast
 *    surfaces and the user stays on the PIN screen.
 *
 * The setup / reset modes are already covered by the comprehensive
 * ``PinPage`` unit suite (RTL) — this spec deliberately stays
 * scoped to the unlock path that the audit's V12-M5 ``PIN`` bullet
 * calls out as missing at the e2e layer.
 *
 * Unlike most other specs in this directory we do *not* call
 * ``seedSession(page)`` here, because that helper pre-writes a
 * valid ``garant.pin_token`` and would short-circuit ``PinGate``
 * past the page we're trying to exercise. Instead we seed only the
 * dev-init-data half of the session so the bot-handshake doesn't
 * trip but the PIN screen still renders.
 */

const DEV_INIT_DATA =
  "user=%7B%22id%22%3A111%2C%22first_name%22%3A%22TestBuyer%22%2C%22username%22%3A%22testbuyer%22%7D" +
  "&auth_date=1700000000&hash=dev";

async function seedDevSessionWithoutPinToken(page: Page) {
  await page.addInitScript((initData) => {
    window.localStorage.setItem("dev_init_data", initData);
    window.localStorage.removeItem("garant.pin_token");
    window.localStorage.removeItem("garant.pin_token_expires");
  }, DEV_INIT_DATA);
}

async function typePin(page: Page, digits: string) {
  for (const d of digits) {
    await page
      .getByRole("button", { name: d, exact: true })
      .first()
      .click();
  }
}

test.describe("PIN flow", () => {
  test.beforeEach(async ({ page }) => {
    await seedDevSessionWithoutPinToken(page);
  });

  test("check happy-path: correct PIN issues a token and unlocks the app", async ({
    page,
  }) => {
    await mockApi(page);

    // Method-aware override: POST /api/pin/check returns a fresh
    // token; anything else (shouldn't fire on this page) falls
    // through to ``{}``. Registered after ``mockApi`` so it wins
    // per the last-registered contract.
    await page.route(
      /^https?:\/\/[^/]+\/api\/pin\/check(?:\?.*)?$/,
      async (route) => {
        if (route.request().method() === "POST") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              token: "e2e-fresh-pin-token",
              expires_at: new Date(Date.now() + 60 * 60_000).toISOString(),
            }),
          });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({}),
        });
      },
    );

    await page.goto("/search");

    // PIN screen renders because no token is in localStorage.
    await expect(page.getByText("Введите PIN")).toBeVisible();
    await expect(
      page.getByText("Чтобы продолжить, введите ваш 4-значный PIN"),
    ).toBeVisible();

    await typePin(page, "1234");

    // After ``applyToken`` fires, PinGate re-renders the children
    // and the underlying /search page mounts. The bottom-nav
    // contains a deterministic landmark we can assert on.
    await expect(page.getByRole("link", { name: /Оповещения/ })).toBeVisible();
    await expect(page.getByText("Введите PIN")).toHaveCount(0);
  });

  test("check failure: wrong PIN surfaces an error toast and keeps the gate closed", async ({
    page,
  }) => {
    await mockApi(page);

    // Backend returns a 401 with a structured ``detail`` field —
    // ky's ``HTTPError`` carries that through and the catch branch
    // in ``handleComplete`` surfaces it via the toast layer.
    await page.route(
      /^https?:\/\/[^/]+\/api\/pin\/check(?:\?.*)?$/,
      async (route) => {
        if (route.request().method() === "POST") {
          await route.fulfill({
            status: 401,
            contentType: "application/json",
            body: JSON.stringify({ detail: "Неверный PIN" }),
          });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({}),
        });
      },
    );

    await page.goto("/search");
    await expect(page.getByText("Введите PIN")).toBeVisible();

    await typePin(page, "9999");

    // The PIN screen stays mounted (children still hidden) and the
    // error toast surfaces. We don't pin the exact toast string —
    // ``e?.message`` from ky's HTTPError is the upstream-derived
    // text and can drift; the generic Russian fallback that the
    // page falls back to is "Неверный PIN", which is what we
    // assert on.
    await expect(page.getByText("Неверный PIN")).toBeVisible();
    await expect(page.getByText("Введите PIN")).toBeVisible();
  });
});
