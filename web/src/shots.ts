import type { Moment, Sport } from './types'

// GET /replays/{id}/players/{name}/shots (#120): the player's pre-match shots and tonight's so far.
export interface Shots {
  player: string
  sport: 'basketball' | 'football'
  season: { x: number; y: number; made: boolean; zone?: string }[]
  tonight: { x: number; y: number; made: boolean; idx: number }[]
  zones: { zone: string; attempts: number; made: number; rate: number }[]
}

export const MAPPED: Sport[] = ['basketball', 'football']

// The player behind the latest shot on screen, so the map opens even while the commentator is off air.
export function latestShooter(moments: Moment[]): string | null {
  for (let i = moments.length - 1; i >= 0; i--) {
    const shooter = moments[i].players?.shooter
    if (shooter) return shooter
  }
  return null
}

// The map picked on the live screen belongs to its replay: a new replay never reopens the old one's map.
export type Picked = { name: string; replay: number } | null
export const pickedFor = (picked: Picked, replay: number) => (picked?.replay === replay ? picked.name : null)

// NBA zone names, short enough for one line at phone width.
export const zoneName = (zone: string) => zone.replace('In The Paint (Non-RA)', 'Paint (non-RA)')

// A shot in the SVG's space. Basketball keeps NBA LOC_X/LOC_Y (tenths of a foot, hoop at the origin, away
// from the basket is down the screen). Football turns StatsBomb 120x80 to an attacking half, goal at the top.
export function place(sport: Shots['sport'], x: number, y: number): [number, number] {
  return sport === 'football' ? [y, 120 - x] : [x, y]
}
