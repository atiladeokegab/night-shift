import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev the page calls the match server (core/, #14) through this proxy; set API_URL if it isn't on :8000.
const api = process.env.API_URL ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/matches': api,
      '/replays': api,
      '/lines': api,
      '/stats': api,
      '/health': api,
      '/voices': api,
    },
  },
})
