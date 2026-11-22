import { defineConfig, devices } from "@playwright/test";

/**
 * Browser end-to-end tests (`npm run e2e`): the web dev server against one plg-api process with a scripted
 * LLMClient (scripts/e2e_server.py: the poc-data corpus synced into a temporary index, scratch stores, no API keys).
 * Both start here; no Docker. Locally a server already listening on its port is reused.
 */
const API_PORT = 8100;
const WEB_PORT = 3100;

export default defineConfig({
  testDir: "./e2e",
  // One plg-api with shared state (threads, pending approvals): tests run one at a time.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    // localhost, not 127.0.0.1: the dev server serves its client bundles only to localhost (allowedDevOrigins).
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run --project .. python ../scripts/e2e_server.py --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/personas`,
      // The corpus sync (offline embeddings, local cross-encoder) takes a while on a cold cache.
      timeout: 600_000,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
    },
    {
      command: `npx next dev --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/sign-in`,
      timeout: 180_000,
      reuseExistingServer: !process.env.CI,
      env: { PLG_API_URL: `http://127.0.0.1:${API_PORT}`, PLG_NEXT_DIST_DIR: ".next-e2e" },
    },
  ],
});
