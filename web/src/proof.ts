import type { Autonomy, ConsoleReading, HeldOut, LineCheck, LineCheckExample, LineCheckStats, ScoreCheckStats, Stats, TaskAdapter, TaskVersion, VoiceHealth } from './types'

const NONE: Autonomy = { called: 0, first_time: 0, auto_fixed: 0, to_human: 0 }

// The Proof card's autonomy rows (#204): this match, then all matches, straight from /stats or the
// `stats` event. None before core reports them; a match with no calls yet counts zeros.
export function autonomyRows(stats: Pick<Stats, 'autonomy' | 'autonomy_by_match'>, matchId: string | null): [string, Autonomy][] {
  if (!stats.autonomy) return []
  const rows: [string, Autonomy][] = matchId ? [['This match', stats.autonomy_by_match?.[matchId] ?? NONE]] : []
  return [...rows, ['All matches', stats.autonomy]]
}

// A checked line's chip (#298): "Checker model: all ok" or the fields it calls wrong; none without a
// canonical reply, so a chip never claims a check that didn't happen.
export function checkText(c: LineCheck | undefined): string | null {
  if (!c?.labels) return null
  if (!c.wrong.length) return 'Checker model: all ok'
  return `Checker model: ${c.wrong.map((f) => f.replace('_', ' ')).join(', ')} may be wrong`
}

export const FALLBACK_NOTE = 'Voice: browser fallback (ElevenLabs unavailable)'

// The Proof card's voice row (#306): the server's last ElevenLabs failure, or the page's own fallback;
// null while ElevenLabs speaks the lines. A browser voice the viewer picked is no fallback.
export function voiceRow(v: VoiceHealth | undefined, fellBack: boolean): string | null {
  if (v?.provider !== 'browser' && !fellBack) return null
  const why = v?.provider === 'browser' && v.last_error ? ` · ${v.last_error.replaceAll('_', ' ')}` : ''
  const since = v?.provider === 'browser' && v.since ? ` since ${v.since.slice(11, 16)} UTC` : ''
  return FALLBACK_NOTE + why + since
}

// The Proof card's Line check row (#298), straight from /stats, with the training examples fixes sent
// today (#305), e.g. "· 3 examples from fixes today (2 corrected, 1 matched)".
export function linecheckRow(s: LineCheckStats): string {
  const row = `${s.checked} checked · ${s.flags} flagged (${s.rules_missed} the rules missed) · ${s.fixes_sent} fixes sent to it`
  if (s.examples_today === undefined) return row
  const kinds = Object.entries(s.examples_today_by_kind ?? {}).map(([kind, n]) => `${n} ${kind.replace('_', ' ')}`)
  return `${row} · ${s.examples_today} examples from fixes today${kinds.length ? ` (${kinds.join(', ')})` : ''}`
}

// Line check on held-out labelled lines beside the rules (#317), in counts, never a percentage, e.g.
// "held-out: caught 3 of 5 wrong lines (rules: 1 of 5), 5 false alarms".
export function heldoutRow(h: HeldOut | null | undefined): string | null {
  if (!h) return null
  const alarms = h.line_check.false_alarms
  return `held-out: caught ${h.line_check.caught} of ${h.wrong} wrong lines (rules: ${h.rules.caught} of ${h.wrong}), ${alarms} false alarm${alarms === 1 ? '' : 's'}`
}

// Mubit's console as read by hand (#317), with its source and time, e.g. "Mubit console, 24 Oct 19:15
// UTC: 8 tasks, 7 adapters, 0 serving; best 58.3% of a 95% target". A dated reading, never live data.
export function consoleRow(c: ConsoleReading | null | undefined): string | null {
  if (!c) return null
  const day = new Date(c.read_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })
  const scores = Object.values(c.listed).map((t) => t.quality)
  const best = scores.length ? `; best ${Math.max(...scores)}% of a ${c.target}% target` : ''
  return `${c.source}, ${day} ${c.read_at.slice(11, 16)} UTC: ${c.tasks} tasks, ${c.adapters} adapters, ${c.serving} serving${best}`
}

// What a Line check flag does: it never unsays a line (#317).
export const FLAG_NOTE = 'A flag only sends a line to the fix queue; it never unsays it.'

// The fix reasons that send Line check a training example: TEACHES in agent/linecheck.py (#298).
export const TEACHES = ['Wrong score', 'Wrong player', 'Wrong fact']

// A fixed line's Line check example (#305), on its chip and in Review. It says only that a training
// example was sent, never that a model was updated or serves.
export function exampleText(ex: LineCheckExample | null | undefined): string | null {
  if (!ex) return null
  if (ex.kind === 'error') return 'Line check example not sent'
  const request = ex.mubit_request_id ? ` (request ${ex.mubit_request_id.slice(0, 8)})` : ''
  return `Sent to Mubit as a Line check example${request} · kind ${ex.kind.replace('_', ' ')}`
}

// Score check is the one task trained on Mubit (#321): the commentary tasks are not on the card.
const TASKS: [string, string][] = [['score_check', 'Score check']]

// The Proof card's row per Mubit task (#209) in the console's words, e.g. "Score check: v1, 82%, Passed"
// or "v1, 55.8%, below 95% target", from only what the task's latest record says. No record reads
// "no version recorded yet"; a version without Mubit's verdict, "verdict not recorded".
// None before core reports `adapters`.
// Score check (#321) adds its earlier versions, where each was read, its examples by source and each
// held-out score, e.g. "Score check held-out (lines never sent): Claude via API, 70 of 74 match the data".
export function adapterRows(adapters: Record<string, TaskAdapter> | undefined, sc?: ScoreCheckStats): string[] {
  if (!adapters) return []
  const rows = TASKS.map(([task, label]) => `${label}: ${adapterRow(adapters[task])}${history(adapters[task])}`)
  if (!sc) return rows
  const kinds = Object.entries(sc.from_fixes_by_kind).map(([kind, n]) => `${n} ${kind}`)
  rows.push(`Score check examples sent: ${sc.seeded} seeded, ${sc.from_fixes} from fixes${kinds.length ? ` (${kinds.join(', ')})` : ''}`)
  for (const [what, e] of Object.entries(sc.held_out)) rows.push(`Score check held-out (lines never sent): ${what}, ${e.agree} of ${e.scored} match the data`)
  return rows
}

function verdictOf(a: Pick<TaskAdapter, 'score' | 'target' | 'passed'>, testing: boolean): string | null {
  // the console's own wording only where the record shows it: a score under its target; else its verdict
  const failed = a.score !== null && a.target !== null && a.score < a.target ? `below ${a.target}% target` : 'Failed'
  return a.passed === null ? (testing ? 'verdict not recorded' : null) : a.passed ? 'Passed' : failed
}

function adapterRow(a: TaskAdapter | undefined): string {
  if (!a) return 'no version recorded yet'
  return [
    a.state === 'collecting' ? 'collecting' : null,
    a.version === null ? null : `v${a.version}${a.version_id ? ` (${a.version_id})` : ''}`,
    a.score === null ? null : `${a.score}%`,
    verdictOf(a, a.state === 'testing'),
    a.kept === null ? null : `${a.kept.toLocaleString()} kept`,
  ].filter(Boolean).join(', ')
}

// " · before: v1, 88.5%, below 95% target · Mubit console, 25 Oct 06:10 UTC": only what records say
function history(a: TaskAdapter | undefined): string {
  if (!a) return ''
  const earlier = (a.versions ?? []).filter((v: TaskVersion) => v.version !== a.version)
  const before = earlier.map((v) => [`v${v.version}`, v.score === null ? null : `${v.score}%`, verdictOf(v, true)].filter(Boolean).join(', '))
  const when = a.recorded_at ? `, ${new Date(a.recorded_at).toISOString().slice(0, 16).replace('T', ' ')} UTC` : ''
  return (before.length ? ` · before: ${before.join('; ')}` : '') + (a.source ? ` · ${a.source}${when}` : '')
}

// The fix counts' heading: "Training" alone read as training under way; these are recorded data.
export const TRAINING_LABEL = 'Training data'
