import type { Fix } from './types'

// Why a fix was not saved (#232): 401 the producer token is missing or wrong, 422 with `wrong` the
// number check's reasons, anything else the connection or Mubit (nothing stored, send again).
export interface Refused {
  status: number
  wrong: string[]
}

// Sends a producer fix and reports its answer only while `current()` still holds: a slow POST that lands
// after a sport switch must not close the new match's sheet, show its error there, or mark its replay.
export async function submitFix(
  post: () => Promise<Fix>,
  current: () => boolean,
  done: (fix: Fix) => void,
  failed: (why: Refused) => void,
): Promise<void> {
  let fix: Fix
  try {
    fix = await post()
  } catch (err) {
    const e = err as { status?: number; wrong?: string[] } | null
    if (current()) failed({ status: e?.status ?? 0, wrong: e?.wrong ?? [] })
    return
  }
  if (current()) done(fix)
}
