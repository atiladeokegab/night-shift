import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// The headline and body faces, preloaded so the text doesn't reflow when they swap in; the hashed names only exist at build time.
const preloadFonts: Plugin = {
  name: 'preload-fonts',
  transformIndexHtml: {
    order: 'post',
    handler: (_html, ctx) =>
      Object.keys(ctx.bundle ?? {})
        .filter((f) => /(outfit-latin-(600|700)|inter-latin-400)-normal-.*\.woff2$/.test(f))
        .map((f) => ({ tag: 'link', attrs: { rel: 'preload', as: 'font', type: 'font/woff2', href: `/${f}`, crossorigin: '' }, injectTo: 'head' as const })),
  },
}

// In dev the page calls the match server (core/, #14) through this proxy; set API_URL if it isn't on :8000.
const api = process.env.API_URL ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), preloadFonts],
  server: {
    proxy: {
      '/matches': api,
      '/replays': api,
      '/lines': api,
      '/stats': api,
      '/health': api,
      '/voices': api,
      '/review': api, // the Review queue and the ledger read the server too (#171)
      '/ledger': api,
    },
  },
})
