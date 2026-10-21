import { defineConfig, devices } from "@playwright/test";

// Run through scripts/e2e_ui.py (`make ui-smoke`): it starts the STUB API and the web app and sets E2E_WEB_URL.
if (!process.env.E2E_WEB_URL) {
  throw new Error("E2E_WEB_URL is not set: run `make ui-smoke` (scripts/e2e_ui.py), which starts the API and the web app first");
}

export default defineConfig({
  testMatch: "*.spec.ts",
  timeout: 5 * 60_000, // one test = one stub run plus the UI; the golden path has six nodes. A loaded machine is 10x slower than an idle one
  globalTimeout: 9 * 60_000,
  expect: { timeout: 30_000 },
  workers: 1, // the tests share one API, its database and its day budget
  retries: 0,
  reporter: "list", // it prints the passes and the skips
  outputDir: "test-results",
  use: {
    baseURL: process.env.E2E_WEB_URL,
    actionTimeout: 60_000, // a click on a tab that never appears fails in a minute, not at the 5-minute test timeout
    navigationTimeout: 60_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
