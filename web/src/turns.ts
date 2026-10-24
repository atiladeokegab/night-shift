import type { Moment } from './types'

// Who speaks when (#131), kept out of React so the tests reach it. Two commentators share the air:
// the lead calls the moments, the analyst fills the gaps with numbers (#130); a viewer's answer is
// spoken in the analyst's voice, at a natural gap (#139).

export type Speaker = 'lead' | 'analyst'

// A big moment cuts in on the other speaker, like a real broadcast: a goal, a wicket, a basket, an overtake.
export const isBig = (m: Pick<Moment, 'type' | 'outcome'> | undefined): boolean =>
  !!m && (m.outcome === 'Goal' || ['Wicket', 'Field goal', 'Overtake', 'Lead change'].includes(m.type))

// A decisive moment stops a viewer's answer and is said at once: a goal, a wicket, a lead change, the final whistle.
export const isDecisive = (m: Pick<Moment, 'type' | 'outcome'> | undefined): boolean =>
  !!m && (m.outcome === 'Goal' || ['Own Goal Against', 'Wicket', 'Lead change', 'Full time', 'End of game'].includes(m.type))

// A held line spoken later than this after it was due is shown, never spoken: it would trail the picture.
export const HOLD_MAX_MS = 5000

// A viewer's answer is not started while a big moment is due within this many seconds (#139).
export const BIG_SOON_S = 3

// A big moment the picture reaches within BIG_SOON_S of `now` (video seconds): only gated moments know when.
export const bigSoon = (moments: Pick<Moment, 'type' | 'outcome' | 'video_t'>[], now: number): boolean =>
  moments.some((m) => isBig(m) && m.video_t !== undefined && m.video_t >= now && m.video_t - now <= BIG_SOON_S)

export interface Turn {
  speaker: Speaker
  answer?: boolean // a viewer's answer: only a decisive moment cuts it off, and it waits for a gap
  big?: boolean
  decisive?: boolean
  fill?: boolean // the extra pair in a long quiet (#297): any other line cuts it, so a moment is never late
}

// The floor: one voice at a time. A line by the same speaker cuts off the one before it, so the voice
// never falls behind the match; a line never cuts off the other speaker unless it is a big moment; and
// only a decisive moment cuts off an answer (`onCut` hears which). A line that may not cut in waits (the newest only) for the turn on air
// to end. A viewer's answer waits for a gap (#139): the commentary goes on until the line on air ends
// with no big moment due (`bigDue`), then the answer takes the floor. Times are in ms on one clock.
export class Floor<T extends Turn> {
  private on: T | null = null
  private held: { item: T; due: number } | null = null
  private asked: T | null = null // the answer waiting for a gap
  bigDue: () => boolean = () => false
  onCut: (answer: T) => void = () => {}

  // A turn due at `now`: true to say it at once, false when it waits for the one on air (or a gap).
  take(item: T, now: number): boolean {
    if (item.answer) {
      this.asked = item
      return this.gap() === item
    }
    const on = this.on
    const waits = !!on && (on.answer ? !item.decisive : on.speaker !== item.speaker && !item.big && !(on.fill && !item.fill))
    if (waits) {
      this.held = { item, due: now }
      return false
    }
    if (on?.answer) this.onCut(on)
    this.on = item
    this.held = null
    return true
  }

  // `item` finished at `now`: the held turn to say next, unless it would start more than HOLD_MAX_MS late.
  ended(item: T, now: number): T | null {
    if (this.on !== item) return null
    const held = this.held
    this.on = null
    const answer = this.gap()
    if (answer) return answer // the held line waits for the answer now
    this.held = null
    if (!held || now - held.due > HOLD_MAX_MS) return null
    this.on = held.item
    return held.item
  }

  // The waiting answer, once nothing is on air and no big moment is due; it holds the floor from here.
  gap(): T | null {
    const answer = this.asked
    if (!answer || this.on || this.bigDue()) return null
    this.asked = null
    this.on = answer
    return answer
  }

  clear() {
    this.on = null
    this.held = null
    this.asked = null
  }
}

// How a line sounds in its speaker's voice. The server reads an analyst line in the sport's analyst voice
// (core/voice.py), so it gets no voice id; the browser fallback has one voice per language, so the
// analyst speaks lower and slower to stay a different person.
export function voiceOf(speaker: Speaker, leadVoiceId: string | undefined): { id?: string; pitch: number; rate: number } {
  return speaker === 'analyst' ? { pitch: 0.8, rate: 1.0 } : { id: leadVoiceId, pitch: 1, rate: 1.1 }
}

// The commentary's level for a volume control: 0 to 1, and silence when muted.
export const loudness = (volume: number, muted: boolean): number => (muted ? 0 : Math.min(1, Math.max(0, volume || 0)))

export interface Caption {
  kind: 'line' | 'question' | 'answer'
  text: string
  speaker?: Speaker
}

export const READ_MS = 6000 // an answer that isn't spoken (voice off, off air) stays up this long

// A viewer's question on the stage: "A viewer asks: … · thinking…" until the answer is in, then the
// question alone until the answer starts (#139: it waits for a gap in the commentary), then the answer in the analyst's voice for as long as it is spoken
// (`speak` calls `started` as it goes on air and resolves at its end; null when it isn't spoken, and then
// it shows at once), then the lines again. Resolves once the answer is in, so the ask box is free while
// it waits and is spoken. `current` is false once the replay or a newer question replaced this one: it
// then changes nothing. `asker` is '' for the page's own "Where are we?" in a quiet spell (#186).
export async function airAnswer<A extends { text: string }>(
  question: string,
  ask: () => Promise<A | null>,
  speak: (answer: A, started: () => void) => Promise<void> | null,
  show: (caption: Caption | null) => void,
  current: () => boolean,
  readMs = READ_MS,
  asker = 'A viewer asks: ',
): Promise<void> {
  show({ kind: 'question', text: `${asker}${question} · thinking…` })
  const answer = await ask()
  if (!current()) return
  if (!answer) return show(null)
  show({ kind: 'question', text: `${asker}${question}` }) // answered: no longer thinking, waiting for a gap
  const started = () => current() && show({ kind: 'answer', text: answer.text, speaker: 'analyst' })
  const spoken = speak(answer, started)
  if (!spoken) started()
  const aired = spoken ?? new Promise<void>((r) => setTimeout(r, readMs))
  void aired.then(() => current() && show(null))
}
