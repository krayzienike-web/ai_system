import { defineConfig, devices } from "@playwright/test";

// The production build against the real API (`make e2e-live`): what the prototype cannot show — the session in
// an httpOnly cookie, a reload, signing out, a handed-out password (docs/13, TC-UI-31, TC-UI-34). Needs the
// backend's database (FAI_DATABASE_URL, FAI_MIGRATIONS_DATABASE_URL), migrated; not part of CI.
const API = 8011;
const WEB = 4180;

export default defineConfig({
  testDir: "e2e-live",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: `http://localhost:${WEB}`,
    trace: "retain-on-failure",
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  projects: [{ name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } }],
  webServer: [
    {
      command: `cd ../backend && FAI_ENV=dev uv run uvicorn app.main:app --port ${API}`,
      url: `http://localhost:${API}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite build --outDir dist-live && API_URL=http://localhost:${API} npx vite preview --outDir dist-live --port ${WEB} --strictPort`,
      url: `http://localhost:${WEB}`,
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
