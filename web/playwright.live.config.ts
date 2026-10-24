import { defineConfig } from '@playwright/test'

// `make live-e2e`: one judge's path on the deployed site (LIVE_URL), in a real Chromium. No server is started.
export default defineConfig({
  testDir: 'live',
  timeout: 180_000,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.LIVE_URL || 'https://night-shift-5zvig7nbvq-ew.a.run.app',
    viewport: { width: 1280, height: 800 },
    trace: 'retain-on-failure',
    launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] },
  },
  outputDir: 'test-results/live',
})
