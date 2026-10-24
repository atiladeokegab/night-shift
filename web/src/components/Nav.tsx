import type { ReactNode } from 'react'
import { isDemo } from '../api'

// The wall (A-6.5) is home; Fixtures keeps the picker for choosing a speed.
export type Screen = 'wall' | 'picker' | 'about' | 'live' | 'review'

interface Props {
  current: Screen
  onGo: (screen: Screen) => void
  children?: ReactNode // the live page's match bar, between the wordmark and the links (#153)
}

// The top nav (docs/design.md): "Touchline." left; "Matches" (green dot), "Fixtures", "About" right.
export function Nav({ current, onGo, children }: Props) {
  const link = (screen: Screen, label: string, dot = false) => (
    <button aria-current={current === screen || (screen === 'wall' && current === 'live') ? 'page' : undefined} onClick={() => onGo(screen)}>
      {dot && <span className="dot" aria-hidden />}
      {label}
    </button>
  )
  return (
    <header className="nav">
      <div className="brand">
        <button className="wordmark" aria-label="Touchline, home" onClick={() => onGo('wall')}>Touchline.</button>
        {isDemo && <span className="badge">Demo data</span>}
      </div>
      {children}
      <nav className="links" aria-label="Main">
        {link('wall', 'Matches', true)}
        {link('picker', 'Fixtures')}
        {link('review', 'Review')}
        {link('about', 'About')}
      </nav>
    </header>
  )
}
