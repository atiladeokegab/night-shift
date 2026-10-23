import { isDemo } from '../api'

// The wall (A-6.5) is home; Fixtures keeps the picker for choosing a speed.
export type Screen = 'wall' | 'picker' | 'about' | 'live'

interface Props {
  current: Screen
  onGo: (screen: Screen) => void
}

// The top nav (docs/design.md): "Touchline." left; "Live" (green dot), "Fixtures", "About" right.
export function Nav({ current, onGo }: Props) {
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
      <nav className="links" aria-label="Main">
        {link('wall', 'Live', true)}
        {link('picker', 'Fixtures')}
        {link('about', 'About')}
      </nav>
    </header>
  )
}
