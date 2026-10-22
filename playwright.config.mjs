// Browser end-to-end tests:  npm run e2e:install && npm run e2e
import { defineConfig, devices } from "@playwright/test";

const PORT = 8790;

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  fullyParallel: true,
  workers: 2, // timing assertions (A/V sync) need CPU headroom
  reporter: [["list"]],
  outputDir: "tests/artifacts/playwright",
  use: { baseURL: `http://127.0.0.1:${PORT}/`, viewport: { width: 1280, height: 720 } },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 720 } } },
    { name: "firefox", use: { ...devices["Desktop Firefox"], viewport: { width: 1280, height: 720 } } },
    { name: "webkit", use: { ...devices["Desktop Safari"], viewport: { width: 1280, height: 720 } } },
  ],
  webServer: {
    command: `scripts/e2e-prepare.sh ${PORT}`,
    url: `http://127.0.0.1:${PORT}/silent/manifest.json`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
