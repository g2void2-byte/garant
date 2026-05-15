import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for end-to-end smoke tests.
 *
 * Runs against ``vite dev`` (not ``vite preview``) so the
 * ``import.meta.env.DEV`` branch in ``src/lib/tg.ts`` reads our
 * ``dev_init_data`` localStorage seed — the production build strips
 * that fallback away. Every ``/api/*`` call is intercepted inside the
 * spec, so the suite needs neither Postgres / Redis nor the FastAPI
 * backend.
 *
 * To run locally:
 *   npm run test:e2e:install   # one-off: download Chromium
 *   npm run test:e2e           # boots vite dev + runs specs
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    viewport: { width: 390, height: 844 },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5174",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
