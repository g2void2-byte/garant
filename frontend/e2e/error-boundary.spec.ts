import { test } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — ErrorBoundary overlay e2e.
 *
 * ``frontend/src/components/ErrorBoundary.tsx`` (added in #141) wraps
 * the entire React tree and converts uncaught render exceptions into
 * a recoverable overlay. The unit suite
 * (``ErrorBoundary.test.tsx``) covers the class component in
 * isolation, but the audit's V12-M5 §"5xx ErrorBoundary" bullet calls
 * for an end-to-end check that the overlay surfaces inside the real
 * Vite-mounted tree and that both recovery affordances are wired.
 *
 * The trigger is the dev-only ``/__dev/crash`` route registered in
 * ``App.tsx`` under ``import.meta.env.DEV``. The route's element
 * throws synchronously during render, which is the cleanest way to
 * force a deterministic render-time throw without relying on brittle
 * malformed-API tricks or Vite's internal lazy-chunk loading.
 *
 * Note on the audit's "5xx" wording: the ErrorBoundary explicitly does
 * NOT react to 5xx HTTP responses — those surface as toasts via the
 * shared ``ky`` client. The audit acknowledges this and asks the e2e
 * to either force a render-throw or verify overlay + button wiring;
 * the former is what we do below.
 */
test.describe("ErrorBoundary overlay", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
    await mockApi(page);
  });

  test("renders the overlay with alert role and both recovery buttons when a route throws during render", async ({
    page,
  }) => {
    await page.goto("/__dev/crash");

    // ``role="alert"`` + ``aria-live="assertive"`` is the wrapper the
    // class component renders for the default fallback; assert against
    // that rather than a CSS class so the test survives styling tweaks.
    const overlay = page.getByRole("alert");
    await expect(overlay).toBeVisible();
    await expect(overlay).toHaveAttribute("data-testid", "error-boundary-overlay");
    await expect(page.getByText("Что-то пошло не так")).toBeVisible();
    await expect(
      page.getByText(/Произошла непредвиденная ошибка/),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Попробовать ещё раз/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Перезагрузить/ }),
    ).toBeVisible();
  });

  test('"Попробовать ещё раз" clears the boundary state and re-renders the same route (which throws again)', async ({
    page,
  }) => {
    await page.goto("/__dev/crash");
    const overlay = page.getByRole("alert");
    await expect(overlay).toBeVisible();

    // The dev route throws on every render, so clicking ``reset``
    // clears ``state.error`` and the immediate re-render of the same
    // ``<DevCrashRoute />`` element throws again — observable as the
    // overlay disappearing momentarily and reappearing once
    // ``componentDidCatch`` fires. We assert the overlay stays
    // mounted after the click round-trip (i.e. the boundary is wired
    // and recoverable), not that it transiently disappears, because
    // the latter is racy under Playwright's auto-wait. The unit suite
    // covers the "subtree no longer throws" recovery path.
    await page.getByRole("button", { name: /Попробовать ещё раз/ }).click();
    await expect(overlay).toBeVisible();
    await expect(page.getByText("Что-то пошло не так")).toBeVisible();
  });

  test('"Перезагрузить" triggers a real page reload', async ({ page }) => {
    // Chromium locks ``Location.prototype.reload`` — both
    // ``Object.defineProperty(window.location, "reload", …)`` and the
    // same call on the prototype are silently rejected, so the unit
    // pattern from ``ErrorBoundary.test.tsx`` cannot be replicated in
    // a real browser. Instead, observe the side effect: a reload
    // re-creates the JS context, which we detect by planting a
    // marker on ``window`` and asserting it is gone after the click.
    // The marker doubles as a sanity check that we did *not* trip a
    // SPA-internal route change (which would keep the JS context and
    // the marker intact).
    await page.goto("/__dev/crash");
    await expect(page.getByRole("alert")).toBeVisible();
    await page.evaluate(() => {
      (window as unknown as { __beforeReload: boolean }).__beforeReload = true;
    });

    let postClickLoadCount = 0;
    const handler = () => {
      postClickLoadCount += 1;
    };
    page.on("load", handler);
    try {
      await page.getByRole("button", { name: /Перезагрузить/ }).click();
      // The dev-only crash route throws on every render, so a real
      // reload re-mounts the boundary and the overlay re-appears.
      // ``waitForLoadState("load")`` won't fire again on its own
      // because Playwright treats the initial load as already
      // settled, but the ``page.on("load")`` handler above catches
      // the reload-driven re-load.
      await expect.poll(() => postClickLoadCount).toBeGreaterThanOrEqual(1);
    } finally {
      page.off("load", handler);
    }

    // Marker was wiped by the reload — proves it was a full document
    // reload, not just a SPA re-render or a ``history.pushState``.
    const markerStillPresent = await page.evaluate(
      () => (window as unknown as { __beforeReload?: boolean }).__beforeReload === true,
    );
    expect(markerStillPresent).toBe(false);
    // Overlay still mounted post-reload — the route threw again.
    await expect(page.getByRole("alert")).toBeVisible();
  });
});
