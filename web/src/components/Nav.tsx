import { isDemo } from '../api'

export type Screen = 'picker' | 'about' | 'live'

interface Props {
  current: Screen
  onGo: (screen: Screen) => void
}

// The top nav (docs/design.md): "Touchline." left; "Live" (green dot), "Fixtures", "About" right.
export function Nav({ current, onGo }: Props) {
  const link = (screen: Screen, label: string, dot = false) => (
    <button aria-current={current === screen ? 'page' : undefined} onClick={() => onGo(screen)}>
      {dot && <span className="dot" aria-hidden />}
      {label}
    </button>
  )
  return (
    <header className="nav">
      <div className="brand">
        <button className="wordmark" aria-label="Touchline, home" onClick={() => onGo('picker')}>Touchline.</button>
        {isDemo && <span className="badge">Demo data</span>}
      </div>
      <nav className="links" aria-label="Main">
        {link('live', 'Live', true)}
        {link('picker', 'Fixtures')}
        {link('about', 'About')}
      </nav>
    </header>
  )
}
