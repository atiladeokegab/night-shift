import type { Fix } from './types'

// Sends a producer fix and reports its answer only while `current()` still holds: a slow POST that lands
// after a sport switch must not close the new match's sheet, show its error there, or mark its replay.
export async function submitFix(
  post: () => Promise<Fix>,
  current: () => boolean,
  done: (fix: Fix) => void,
  failed: () => void,
): Promise<void> {
  let fix: Fix
  try {
    fix = await post()
  } catch {
    if (current()) failed()
    return
  }
  if (current()) done(fix)
}
