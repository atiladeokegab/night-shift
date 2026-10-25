import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Self-hosted, as docs/design.md asks: Outfit for the wordmark, headings, score bar and subtitles; Inter for the rest.
import '@fontsource/outfit/500.css'
import '@fontsource/outfit/600.css'
import '@fontsource/outfit/700.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import './index.css'
import App from './App.tsx'
import './brand.css' // the header lockup, after App.css

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
