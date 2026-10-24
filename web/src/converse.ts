// Talk to the commentator (#380): the match pauses while the fan talks and resumes when the talk
// ends, but only a pause the talk made: a match the fan had already paused stays paused.

import { replayGone } from './ended.ts'

export interface Door {
  signed_url: string
  ctx: string
}

export const SILENT_MS = 12_000 // the fan says nothing this long after the commentator: the talk is over

export class TalkPause {
  private mine = false

  begin(alreadyPaused: boolean, pause: () => void) {
    if (alreadyPaused) return
    this.mine = true
    pause()
  }

  end(resume: () => void) {
    if (!this.mine) return
    this.mine = false
    resume()
  }
}

// GET /converse/{sport}/{match_id}/token for this replay at the moment on screen; null when a
// conversation can't start (not configured, off air, rate limited): the page keeps Ask.
export async function converseDoor(
  replayId: string, sport: string, matchId: string, momentIdx: number, get: typeof fetch = fetch,
): Promise<Door | null> {
  try {
    const q = new URLSearchParams({ replay_id: replayId, moment_idx: String(momentIdx) })
    const res = await get(`/converse/${encodeURIComponent(sport)}/${encodeURIComponent(matchId)}/token?${q}`)
    if (!res.ok) {
      await replayGone(res, replayId) // a dropped replay ends on the page (#454)
      return null
    }
    const door = (await res.json()) as Door
    return door.signed_url && door.ctx ? door : null
  } catch {
    return null
  }
}
