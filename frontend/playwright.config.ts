import { defineConfig } from '@playwright/test';

// CSS viewport and DPR are independent. This approximates, but does not reproduce,
// Windows display scaling. Keep visual evidence on Windows to preserve font rendering.
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  outputDir: 'test-results',
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    browserName: 'chromium',
    colorScheme: 'dark',
    reducedMotion: 'reduce',
    locale: 'zh-CN',
    timezoneId: 'Asia/Tokyo',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: '1080p', use: { viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 } },
    { name: '2k', use: { viewport: { width: 2560, height: 1440 }, deviceScaleFactor: 1 } },
    { name: '4k', use: { viewport: { width: 3840, height: 2160 }, deviceScaleFactor: 1 } },
    { name: '4k-150', use: { viewport: { width: 2560, height: 1440 }, deviceScaleFactor: 1.5 } },
    { name: '4k-200', use: { viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 } },
    { name: 'narrow', use: { viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 } },
    { name: 'laptop', use: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 } },
  ],
  webServer: {
    command: 'npm run preview',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
