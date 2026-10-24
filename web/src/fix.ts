import type { Fix } from './types'

// Sends a producer fix and reports its answer only while `current()` still holds: a slow POST that lands
// after a sport switch must not close the new match's sheet, show its error there, or mark its replay.
export async function submitFix(
  post: () => Promise<Fix>,
  current: () => boolean,
  done: (fix: Fix) => void,
  failed: (wrong: string[]) => void, // the number check's reasons on a 422 (#232); [] otherwise
): Promise<void> {
  let fix: Fix
  try {
    fix = await post()
  } catch (err) {
    if (current()) failed((err as { wrong?: string[] } | null)?.wrong ?? [])
    return
  }
  if (current()) done(fix)
}
