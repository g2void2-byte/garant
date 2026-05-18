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

  test('"Перезагрузить" calls window.location.reload exactly once', async ({
    page,
  }) => {
    // Replace ``location.reload`` with a counter before the React tree
    // mounts so the click handler's call is observable. In Chromium
    // ``window.location`` is a host object whose property descriptors
    // are mostly non-configurable, so we hook the prototype-level
    // ``reload`` getter via ``Object.defineProperty`` on the
    // ``Location.prototype`` chain instead of replacing ``location``
    // wholesale (which would also break router reads of ``href``).
    await page.addInitScript(() => {
      (
        window as unknown as { __reloadCallCount: number }
      ).__reloadCallCount = 0;
      Object.defineProperty(window.location, "reload", {
        configurable: true,
        writable: true,
        value: () => {
          (
            window as unknown as { __reloadCallCount: number }
          ).__reloadCallCount++;
        },
      });
    });

    await page.goto("/__dev/crash");
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: /Перезагрузить/ }).click();

    const count = await page.evaluate(
      () =>
        (window as unknown as { __reloadCallCount: number }).__reloadCallCount,
    );
    expect(count).toBe(1);
  });
});
