import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { defineConfig } from '@playwright/test'

// The a11y checks (#170): `npx playwright test` starts the match server offline (no keys: nothing is
// voiced by ElevenLabs, the page falls back to the browser's speech) and Vite on ports of their own.
const API = 8170
const WEB = 5170

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
      reuseExistingServer: true,
    },
    {
      command: `npx vite --port ${WEB} --strictPort`,
      url: `http://localhost:${WEB}`,
      env: { API_URL: `http://localhost:${API}` },
      reuseExistingServer: true,
    },
  ],
})
