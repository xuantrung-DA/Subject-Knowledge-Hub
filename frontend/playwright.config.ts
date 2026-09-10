import { defineConfig, devices } from "@playwright/test";

/** Tests use the actual running Docker stack; no API routes are mocked. */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 90000,
  expect: { timeout: 15000 },
  retries: 0,
  outputDir: "../artifacts/browser",
  reporter: [
    ["list"],
    ["html", { outputFolder: "../artifacts/browser-report", open: "never" }],
  ],
  use: {
    baseURL: process.env.SKH_BROWSER_URL || "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
