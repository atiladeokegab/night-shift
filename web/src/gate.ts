// A-6.4@2: the server sends lines (and their moments) ahead of time, tagged with the video time of the
// moment; the page presents each one only when the YouTube player's clock reaches that time, so the
// commentary never runs ahead of the picture.

// A line whose moment the video passed more than this long ago (a forward seek, a long stall) is
// logged but never shown as the subtitle or spoken: it would describe something already gone.
export const LATE_AFTER_S = 1.0

export interface Timed {
  video_t?: number // seconds into the highlights video; untagged items need no video
}

export interface Released<T> {
  live: T[] // due now: show and speak
  late: T[] // due long ago: log only
  waiting: T[] // still ahead of the picture
}

// Whether a newly presented line is voiced: never one released late, nor one a jump (#163) brought
// from an earlier replay, which was never called this time.
export const speaks = (line: { line_id: string; history?: boolean }, late: string[]) =>
  !late.includes(line.line_id) && !line.history

// The lines in `lines` (newest first) not yet handed to the speaking queue, oldest first, marked as
// seen. Several can land in one render (a call and an analyst fill), and each must reach the queue:
// it, not the page, decides which one to drop.
export function fresh<T extends { line_id: string; history?: boolean }>(lines: T[], seen: Set<string>, late: string[]): T[] {
  const out = lines.filter((l) => !seen.has(l.line_id))
  out.forEach((l) => seen.add(l.line_id))
  return out.filter((l) => speaks(l, late)).reverse()
}

// Splits queued items by the player's current time `t`, keeping arrival order within each group.
export function release<T extends Timed>(queue: T[], t: number): Released<T> {
  const out: Released<T> = { live: [], late: [], waiting: [] }
  for (const item of queue) {
    const at = item.video_t ?? -Infinity
    if (at > t) out.waiting.push(item)
    else if (t - at > LATE_AFTER_S) out.late.push(item)
    else out.live.push(item)
  }
  return out
}

// The replay's own clock, for when the video can't play: it runs from `from` (where the picture was, or
// where it should have started) at real speed and never pauses, so the mapped lines still play in step.
export function replayClock(from: number, now = () => performance.now()) {
  const t0 = now()
  return () => ({ t: from + (now() - t0) / 1000, playing: true, duration: 0 })
}
