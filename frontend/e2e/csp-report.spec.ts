import { test } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — CSP violation reporter e2e (last bullet of 8).
 *
 * Closes the only remaining V12-M5 §"E2E suite" item flagged in
 * AUDIT-remaining-v9.md::§1.Medium.
 *
 * Contract under test
 * -------------------
 * The CSP policy in ``backend/app/main.py::_CSP_DIRECTIVES`` carries
 * a trailing ``report-uri /api/csp-report`` so browsers POST a
 * violation envelope on every blocked resource. The collector
 * (``backend/app/routers/csp_report.py``) accepts the envelope,
 * rate-limits per-IP and logs at INFO/DEBUG depending on
 * ``_classify_report`` bucketing. Backend unit tests
 * (``tests/test_csp_policy.py``, ``tests/test_csp_report.py``) cover
 * the header string and the collector in isolation. This spec adds
 * the third leg of the chain — that a real Chromium, when it sees
 * a ``report-uri`` directive AND a violation, actually POSTs the
 * envelope to our endpoint with the legacy
 * ``application/csp-report`` shape ``_classify_report`` expects.
 *
 * Mock surface
 * ------------
 * The e2e harness boots ``vite dev`` (see ``playwright.config.ts``)
 * with every ``/api/**`` call intercepted in ``fixtures.ts``; there
 * is no FastAPI process. Two consequences shape the spec:
 *
 *   1. Vite dev does NOT emit the CSP header on its own — the
 *      backend's ``_security_headers`` middleware only runs when
 *      FastAPI is the one serving the SPA. So we inject the policy
 *      via ``page.route`` on the document response. Plumbing the
 *      real middleware through the dev server would either need a
 *      parallel uvicorn boot in ``playwright.config.ts`` (slow,
 *      defeats the no-backend invariant the rest of the suite
 *      relies on) or duplicating the policy string in Vite's HTTP
 *      server (drift risk — the policy IS the contract). Both
 *      options leak backend ownership into the frontend test
 *      harness. Injecting the header here keeps the workaround
 *      contained to this one spec.
 *
 *   2. ``mockApi`` registers a catch-all ``page.route`` for every
 *      ``/api/*`` request that replies with ``[]``. Playwright runs
 *      the *last-registered* matching route first, so the
 *      ``/api/csp-report`` interceptor below is added inside the
 *      test body (after ``beforeEach`` finishes) and therefore wins
 *      over the catch-all.
 *
 * Why ``img-src`` and not inline-script / inline-style
 * ----------------------------------------------------
 * Vite dev injects HMR client modules into the document; restricting
 * ``script-src`` in our injected header would block them and break
 * the React mount before we even get a chance to trigger the
 * violation under test. ``img-src 'self'`` only constrains image
 * loads — orthogonal to the rest of the page — and a deterministic
 * cross-origin ``new Image(); img.src = "https://example.com/..."``
 * trip is the cleanest way to fire exactly one report.
 */
test.describe("CSP violation reporter (V12-M5)", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
    await mockApi(page);
  });

  test("Chromium POSTs an application/csp-report envelope to /api/csp-report when img-src blocks a cross-origin image", async ({
    page,
  }) => {
    // 1. Capture the violation envelope the browser ships. Resolves
    //    when the route fires so the test can ``await`` the round
    //    trip deterministically.
    let reportBody: string | null = null;
    let reportContentType: string | null = null;
    let reportResolved = false;
    let resolveReportSeen: () => void = () => {};
    const reportSeen = new Promise<void>((resolve) => {
      resolveReportSeen = resolve;
    });
    await page.route("**/api/csp-report", async (route) => {
      const req = route.request();
      if (req.method() === "POST") {
        // ``postData()`` returns the raw bytes the browser sent;
        // ``headerValue("content-type")`` is the envelope-flavour
        // hint we cross-check below.
        reportBody = req.postData();
        reportContentType = await req.headerValue("content-type");
        // The collector returns 204 No Content; mimic that here so
        // the browser doesn't retry / log a network error.
        await route.fulfill({ status: 204, body: "" });
        if (!reportResolved) {
          reportResolved = true;
          resolveReportSeen();
        }
      } else {
        await route.fallback();
      }
    });

    // 2. Inject a strict ``img-src 'self'`` + ``report-uri`` policy
    //    onto the document response so Chromium enforces it on the
    //    page we're about to load. ``route.fetch()`` re-issues the
    //    request to Vite; ``route.fulfill({response, headers})``
    //    serves the original body back with our extra header.
    await page.route(/^https?:\/\/[^/]+\/(?:\?.*)?$/, async (route, req) => {
      if (req.resourceType() !== "document") {
        await route.fallback();
        return;
      }
      const response = await route.fetch();
      // ``APIResponse`` (the return type of ``route.fetch()``) exposes
      // its headers as a plain dict via ``.headers()`` — there is no
      // ``allHeaders()`` method on the API class (that lives on the
      // ``Response`` returned by ``page.waitForResponse`` etc., not
      // here). Shallow-copy so we don't mutate the underlying dict.
      const headers = { ...response.headers() };
      // Only restrict ``img-src``; everything else (scripts, styles,
      // HMR sockets) falls through to Vite's default which has no
      // CSP at all. ``report-uri`` is same-origin so the POST lands
      // on ``http://127.0.0.1:5174/api/csp-report`` — exactly the
      // route we intercepted above.
      headers["content-security-policy"] =
        "img-src 'self'; report-uri /api/csp-report";
      await route.fulfill({ response, headers });
    });

    // 3. Navigate. The Vite-served ``index.html`` now ships with our
    //    strict-img-src CSP attached. Wait for the React tree to
    //    mount so we know the document parsed + executed; otherwise
    //    a future Vite/HMR change that fails fast could let this
    //    test "pass" against an empty page.
    await page.goto("/");
    await expect(page.getByRole("navigation").first()).toBeVisible();

    // 4. Trigger a CSP violation. ``img-src 'self'`` blocks the load
    //    of a cross-origin URL — the HTTP request never leaves the
    //    browser; the violation report does (synchronously). We
    //    don't ``await`` the load; the browser's report-uri fire is
    //    decoupled from the failed image load.
    await page.evaluate(() => {
      const img = new Image();
      img.src = "https://example.com/v12-m5-csp-trip.png";
      // Appending to the document forces Chromium to start the
      // (blocked) load — without insertion the ``Image`` is a
      // detached object and no fetch is attempted.
      document.body.appendChild(img);
    });

    // 5. Wait for the captured request. 10 s is generous: the
    //    report is fired synchronously with the block, so in
    //    practice it lands within tens of ms.
    await Promise.race([
      reportSeen,
      new Promise<never>((_, reject) =>
        setTimeout(
          () => reject(new Error("Timed out waiting for CSP report POST")),
          10_000,
        ),
      ),
    ]);

    expect(reportBody).not.toBeNull();
    // Chromium ships the legacy ``application/csp-report`` MIME for
    // the ``report-uri`` flavour (the newer ``application/reports+json``
    // is reserved for the ``Report-To`` / ``report-to`` flavour we
    // don't enable). The backend's collector accepts either, but
    // pin the assertion to the shape we expect from this directive.
    expect(reportContentType ?? "").toContain("application/csp-report");

    const parsed = JSON.parse(reportBody!) as {
      "csp-report": {
        "violated-directive": string;
        "blocked-uri": string;
      };
    };
    // The fields the backend's ``_classify_report`` parser reads —
    // anything else (``source-file``, ``document-uri``, browser
    // version-bound additions) is intentionally NOT asserted so
    // this test survives Playwright Chromium upgrades.
    expect(parsed["csp-report"]["blocked-uri"]).toContain("example.com");
    // Chromium reports ``img-src`` in ``violated-directive``; some
    // releases append the source list (``"img-src 'self'"``), older
    // ones emit the bare directive. The leading directive name is
    // what the classifier groups on.
    expect(parsed["csp-report"]["violated-directive"]).toMatch(/^img-src/);
  });
});
