import type { ReactNode } from 'react'
import { isDemo } from '../api'

// The wall (A-6.5) is home; Replays keeps the picker for choosing a speed.
export type Screen = 'wall' | 'picker' | 'about' | 'live' | 'review'

interface Props {
  current: Screen
  onGo: (screen: Screen) => void
  children?: ReactNode // the live page's match bar, between the wordmark and the links (#153)
}

// The mark: the touchline breaks into sound bars. A 16px grid, the same shapes as public/favicon.svg.
function Mark() {
  return (
    <svg className="mark" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect x="1" y="7" width="5" height="2" fill="currentColor" />
      <g className="bars">
        <rect x="7" y="5" width="2" height="6" />
        <rect x="10" y="2" width="2" height="12" />
        <rect x="13" y="4" width="2" height="8" />
      </g>
    </svg>
  )
}

// The top nav (docs/design.md): "Touchline." left; "Matches" (green dot), "Replays", "Review", "About" right.
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
        <button className="wordmark lockup" aria-label="Touchline, home" onClick={() => onGo('wall')}>
          <Mark />
          Touchline
        </button>
        {isDemo && <span className="badge">Demo data</span>}
      </div>
      {children}
      <nav className="links" aria-label="Main">
        {link('wall', 'Matches', true)}
        {link('picker', 'Replays')}
        {link('review', 'Review')}
        {link('about', 'About')}
      </nav>
    </header>
  )
}
