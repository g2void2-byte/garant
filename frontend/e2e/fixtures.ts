import { type Page, type Route, expect } from "@playwright/test";

/**
 * Test fixtures + helpers for the Playwright e2e suite.
 *
 * These keep the specs short and self-documenting: every spec only
 * needs to call ``seedSession(page)`` + ``mockApi(page)`` before
 * navigating. The mocks here cover the routes the public landing tree
 * (Search / Deals / Wallet / Profile) calls during initial render.
 */

const DEV_INIT_DATA =
  "user=%7B%22id%22%3A111%2C%22first_name%22%3A%22TestBuyer%22%2C%22username%22%3A%22testbuyer%22%7D" +
  "&auth_date=1700000000&hash=dev";

/**
 * Pre-seed the localStorage that the dev-mode auth fallback in
 * ``src/lib/tg.ts`` reads (``dev_init_data``) plus a valid PIN token
 * so ``PinGate`` lets the children through without a real PIN flow.
 * Must be called *before* the first navigation — uses
 * ``addInitScript`` so it runs in every new page context.
 */
export async function seedSession(page: Page) {
  const pinExpires = new Date(Date.now() + 60 * 60 * 1000).toISOString();
  await page.addInitScript(
    ({ initData, pinToken, pinExpires }) => {
      window.localStorage.setItem("dev_init_data", initData);
      window.localStorage.setItem("garant.pin_token", pinToken);
      window.localStorage.setItem("garant.pin_token_expires", pinExpires);
    },
    { initData: DEV_INIT_DATA, pinToken: "e2e-pin-token", pinExpires },
  );
}

/**
 * Default USDT currency used by ``mockApi``'s ``wallet/currencies``
 * and ``wallet/balances`` responses. Exported so specs that need the
 * exact shape (e.g. ``WalletDepositDto.currency`` in a POST response
 * stub) can reuse it instead of inlining a parallel copy that drifts.
 */
export const USDT_CURRENCY = {
  id: 1,
  code: "USDT",
  name: "Tether",
  network: "TRC20",
  icon_url: "",
  decimals: 2,
  min_deposit: 5,
  min_withdraw: 1,
};

interface MockOverrides {
  services?: unknown[];
  deals?: unknown[];
  users?: unknown[];
  walletBalances?: unknown[];
  currencies?: unknown[];
  me?: Record<string, unknown>;
}

/**
 * Intercept every ``/api/**`` call and respond with deterministic
 * fixtures. Unknown endpoints fall back to an empty JSON array so
 * the spec doesn't depend on a running backend.
 *
 * Why ``[]`` and not ``{}``: most ``/api/*`` endpoints are list-shaped
 * (``services``, ``deals``, ``reviews``, ``deals/<id>/messages``,
 * ``wallet/currencies``, ``notifications``, …) and their consumers
 * call ``.map`` / ``.some`` / ``.length`` directly. The optional
 * chain (``data?.map(…)``) short-circuits only on ``null`` /
 * ``undefined`` — *not* on ``{}`` — so a catch-all that replied with
 * ``{}`` would silently crash any list-consumer that forgot to mock
 * its endpoint and trip the ``ErrorBoundary`` instead of failing the
 * assertion that exercises the feature. ``[]`` is a no-op for those
 * consumers and equivalent to ``{}`` for object-shaped readers
 * (``[].field`` is ``undefined`` just like ``{}.field``).
 */
export async function mockApi(page: Page, overrides: MockOverrides = {}) {
  const me = overrides.me ?? {
    id: 111,
    user_id: 111,
    username: "testbuyer",
    display_name: "TestBuyer",
    photo_url: null,
    balance: 0,
    admin: 0,
    prefix: null,
    is_admin: false,
    is_arbiter: false,
    is_vip: false,
    is_banned: false,
    is_frozen: false,
    good: 0,
    bad: 0,
    deposit: 0,
    rating: 0,
    reviews_count: 0,
    deals_count: 0,
    deals_sum: 0,
    online: true,
    banner_url: null,
    description: "",
    forums: [],
    is_hidden_profile: false,
  };

  const services = overrides.services ?? [
    {
      id: 1,
      owner_username: "alice",
      title: "Logo design",
      description: "Vector logo + brand book",
      price: 250,
      currency: "USDT",
      status: "active",
      category: { id: 1, slug: "design", name: "Design", icon_key: "design", services_count: 1 },
      created_at: new Date().toISOString(),
    },
  ];

  const deals = overrides.deals ?? [
    {
      id: 17,
      buyer: "testbuyer",
      seller: "alice",
      sum: 100,
      description: "Logo design package",
      pay_comission: "buyer",
      status: "in_progress",
      confirm_buyer: false,
      confirm_seller: false,
      role: "buyer",
      created_at: new Date(Date.now() - 60_000).toISOString(),
      currency_code: "USDT",
      amount: 100,
      commission_amount: 5,
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
    },
  ];

  const users = overrides.users ?? [
    {
      id: 2,
      user_id: 2,
      username: "alice",
      display_name: "Alice",
      photo_url: null,
      balance: 0,
      admin: 0,
      prefix: null,
      is_admin: false,
      is_arbiter: false,
      is_vip: false,
      is_banned: false,
      is_frozen: false,
      good: 4,
      bad: 0,
      deposit: 0,
      rating: 4.8,
      reviews_count: 4,
      deals_count: 4,
      deals_sum: 1200,
      online: true,
      banner_url: null,
      description: "",
      forums: [],
    },
  ];

  const walletBalances = overrides.walletBalances ?? [
    {
      currency: USDT_CURRENCY,
      amount: 123.45,
      locked: 0,
      total: 123.45,
      updated_at: null,
    },
  ];

  const currencies = overrides.currencies ?? [USDT_CURRENCY];

  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  // IMPORTANT: anchor every route to a path that *starts* with
  // ``/api/`` on the dev origin. A naive ``**/api/**`` glob also
  // matches Vite module URLs like ``/src/api/client.ts`` and breaks
  // the React bundle by replying with JSON instead of JavaScript.
  const routeApi = (
    suffix: string | RegExp,
    handler: (r: Route) => Promise<void> | void,
  ) => {
    const pattern =
      typeof suffix === "string"
        ? new RegExp(`^https?://[^/]+/api/${escapeRegex(suffix)}(?:\\?.*)?$`)
        : new RegExp(`^https?://[^/]+/api/(?:${suffix.source})(?:\\?.*)?$`);
    return page.route(pattern, handler);
  };

  // Playwright runs the *last-registered* matching route first, so
  // the catch-all is registered up front and the specific endpoints
  // win because they're added afterward. See the ``mockApi``
  // docstring for why this is ``[]`` rather than ``{}``.
  await routeApi(/.*/, (r) => json(r, []));
  await routeApi("pin/status", (r) =>
    json(r, {
      has_pin: true,
      attempts_left: 5,
      locked_until: null,
      max_attempts: 5,
      session_ttl_seconds: 600,
    }),
  );
  // ``PinPromptModal`` re-verifies the user's PIN before sensitive
  // mutations (deal creation, withdrawal). Return a fresh token so
  // the modal resolves and the underlying action fires.
  await routeApi("pin/check", (r) =>
    json(r, {
      token: "e2e-pin-token",
      expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    }),
  );
  await routeApi("me", (r) => json(r, me));
  await routeApi("settings/maintenance", (r) =>
    json(r, { enabled: false, message: null }),
  );
  await routeApi("notifications/counters", (r) =>
    json(r, { unread: 0, by_type: {} }),
  );
  await routeApi("services", (r) => json(r, services));
  await routeApi("deals", (r) => json(r, deals));
  await routeApi("users", (r) => json(r, users));
  await routeApi("categories", (r) =>
    json(r, [{ id: 1, slug: "design", name: "Design", icon_key: "design", services_count: 1 }]),
  );
  await routeApi("wallet/balances", (r) => json(r, walletBalances));
  await routeApi("wallet/currencies", (r) => json(r, currencies));
  await routeApi("wallet/deposits", (r) => json(r, []));
  await routeApi("wallet/withdrawals", (r) => json(r, []));
  // ``WalletWithdrawPage`` reads ``useAdmins`` to power the
  // "Написать админу" deeplink in the Card-method modal.
  await routeApi("support/admins", (r) =>
    json(r, [{ id: 1, user_id: 1, username: "admin", display_name: "Admin" }]),
  );
}

/**
 * Click "1 2 3 4" on the on-screen PIN pad rendered by
 * ``PinPromptModal``. Use this after triggering a sensitive action
 * (deal creation, withdrawal) to clear the modal so the underlying
 * POST fires.
 */
export async function enterPinPromptDigits(page: Page) {
  // ``role=dialog[aria-labelledby="pin-prompt-title"]`` scopes the
  // search to the modal — there can be other "1"/"2"/"3"/"4" buttons
  // on the page (e.g. the digit-only sum input).
  const modal = page.getByTestId("pin-prompt");
  await modal.waitFor({ state: "visible" });
  for (const d of ["1", "2", "3", "4"]) {
    await modal.getByRole("button", { name: d, exact: true }).click();
  }
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export { expect };
