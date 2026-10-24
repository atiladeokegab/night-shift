import { defineConfig } from '@playwright/test'

// Post-deploy browser checks against the live site (scripts/live_checklist.py): no local servers.
export default defineConfig({
  testDir: 'postdeploy',
  timeout: 90_000,
  workers: 1,
  use: { baseURL: process.env.LIVE_URL ?? 'https://night-shift-5zvig7nbvq-ew.a.run.app' },
})
