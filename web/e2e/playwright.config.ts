import { existsSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const port = Number(process.env.BASSEPARATE_E2E_PORT ?? 8899);
const baseURL = `http://127.0.0.1:${port}`;

/**
 * The installed offline browsers. Playwright's own browser bundle is older
 * than this checkout's Playwright, but the preserved Firefox revision and the
 * system Chrome both speak the protocols Playwright needs and expose
 * AudioWorklet on the loopback origin.
 */
function installedFirefox(): string | undefined {
  const explicit = process.env.PLAYWRIGHT_FIREFOX_EXECUTABLE;
  if (explicit && existsSync(explicit)) return explicit;
  const cache =
    process.env.PLAYWRIGHT_BROWSERS_PATH ??
    join(homedir(), ".cache", "ms-playwright");
  try {
    const revisions = readdirSync(cache)
      .filter((name) => /^firefox-\d+$/.test(name))
      .sort()
      .reverse();
    for (const revision of revisions) {
      const candidate = join(cache, revision, "firefox", "firefox");
      if (existsSync(candidate)) return candidate;
    }
  } catch {
    // fall through: Playwright reports the missing browser clearly.
  }
  return undefined;
}

const firefoxExecutable = installedFirefox();

export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 240_000,
  expect: { timeout: 20_000 },
  reporter: [
    ["list"],
    ["html", { outputFolder: "../playwright-report", open: "never" }],
  ],
  outputDir: resolve(repoRoot, "web", "test-results"),
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    viewport: { width: 1280, height: 900 },
  },
  webServer: {
    command: `.venv/bin/python scripts/e2e_server.py --port ${port}`,
    cwd: repoRoot,
    url: `${baseURL}/api/health`,
    reuseExistingServer: false,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
  projects: [
    {
      name: "firefox",
      use: {
        ...devices["Desktop Firefox"],
        browserName: "firefox",
        ...(firefoxExecutable
          ? { launchOptions: { executablePath: firefoxExecutable } }
          : {}),
        firefoxUserPrefs: {
          "media.autoplay.default": 0,
          "media.autoplay.block-webaudio": false,
        },
      },
    },
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        browserName: "chromium",
        channel: "chrome",
        launchOptions: {
          args: ["--autoplay-policy=no-user-gesture-required"],
        },
      },
    },
  ],
});
