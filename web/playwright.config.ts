import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { defineConfig } from '@playwright/test'

// The a11y checks (#170): `npx playwright test` starts the match server offline (no keys: nothing is
// voiced by ElevenLabs, the page falls back to the browser's speech) and Vite on ports of their own.
// #459: a server already on a port is never reused unless E2E_REUSE=1, since it may run other code (a stale
// checkout's); a busy port fails loudly instead. E2E_API_PORT and E2E_WEB_PORT move a run off one.
const API = Number(process.env.E2E_API_PORT ?? 8170)
const WEB = Number(process.env.E2E_WEB_PORT ?? 5170)
const reuseExistingServer = process.env.E2E_REUSE === '1'

export default defineConfig({
  testDir: 'e2e',
  timeout: 90_000,
  workers: 1, // one store, one replay at a time
  use: { baseURL: `http://localhost:${WEB}` },
  webServer: [
    {
      command: `uv run uvicorn core.main:app --port ${API}`,
      cwd: '..',
      url: `http://localhost:${API}/health`,
      env: { MUBIT_API_KEY: '', MUBIT_FALLBACK_KEY: '', ELEVENLABS_API_KEY: '', REPLAYS_PER_HOUR: '1000', STORE_DIR: join(tmpdir(), 'touchline-e2e') },
      reuseExistingServer,
    },
    {
      command: `npx vite --port ${WEB} --strictPort`,
      url: `http://localhost:${WEB}`,
      env: { API_URL: `http://localhost:${API}` },
      reuseExistingServer,
    },
  ],
})
