import { defineConfig, devices } from "@playwright/test";

/** Captures the README screenshots into docs/screenshots against a running
 * stack (same setup as the e2e suite): `npm run screenshots`. */
export default defineConfig({
  testDir: "./screenshots",
  globalSetup: "./e2e/global-setup.ts",
  workers: 1,
  timeout: 180_000,
  expect: { timeout: 30_000 },
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    viewport: { width: 1440, height: 900 },
    colorScheme: "light",
  },
});
