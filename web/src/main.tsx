import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Self-hosted, as docs/design.md asks: Barlow Condensed for the score bar and labels, Source Sans 3 for text.
import '@fontsource/barlow-condensed/500.css'
import '@fontsource/barlow-condensed/600.css'
import '@fontsource/barlow-condensed/700.css'
import '@fontsource/source-sans-3/400.css'
import '@fontsource/source-sans-3/600.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
