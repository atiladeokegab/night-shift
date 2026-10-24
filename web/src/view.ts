import type { Screen } from './components/Nav'

// Which page is on screen: it changes on every screen change and on every new match (A-6.5's next and
// sport switch), so App can bring each one in from the top instead of the last page's scroll.
export function viewOf(screen: Screen, matchKey: number | undefined): string {
  return screen === 'live' ? `live:${matchKey ?? 0}` : screen
}
