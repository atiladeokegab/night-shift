// A replay the server has dropped (#454): every replay-scoped route says 404 "no replay ..." (core/app.py,
// core/converse.py). The page then treats the replay as ended rather than failing quietly.
export const ENDED = 'This replay has ended. Start it again.'

// useReplay listens here for the id of the replay that went.
export const gone = new EventTarget()

// True only for that 404: "no such player" or "no shot map" is about something else in a live replay.
export async function replayGone(res: Response, replayId: string): Promise<boolean> {
  if (res.status !== 404) return false
  const body = await res.clone().json().catch(() => null)
  if (!String(body?.detail ?? '').startsWith('no replay')) return false
  gone.dispatchEvent(new CustomEvent('replay-gone', { detail: replayId }))
  return true
}
