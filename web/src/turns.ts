import type { Moment } from './types'

// Who speaks when (#131), kept out of React so the tests reach it. Two commentators share the air:
// the lead calls the moments, the analyst fills the gaps with numbers (#130); a viewer's answer is
// spoken in the lead's voice.

export type Speaker = 'lead' | 'analyst'

// A big moment cuts in on the other speaker, like a real broadcast: a goal, a wicket, a basket, an overtake.
export const isBig = (m: Pick<Moment, 'type' | 'outcome'> | undefined): boolean =>
  !!m && (m.outcome === 'Goal' || ['Wicket', 'Field goal', 'Overtake', 'Lead change'].includes(m.type))

// A held line spoken later than this after it was due is shown, never spoken: it would trail the picture.
export const HOLD_MAX_MS = 5000

export interface Turn {
  speaker: Speaker
  answer?: boolean // a viewer's answer: never cut off, and it cuts in on any line
  big?: boolean
}

// The floor: one voice at a time. A line by the same speaker cuts off the one before it, so the voice
// never falls behind the match; a line never cuts off the other speaker unless it is a big moment; and
// nothing cuts off an answer. A line that may not cut in waits (the newest only) for the turn on air
// to end. Times are in ms on one clock.
export class Floor<T extends Turn> {
  private on: T | null = null
  private held: { item: T; due: number } | null = null

  // A turn due at `now`: true to say it at once, false when it waits for the one on air.
  take(item: T, now: number): boolean {
    const on = this.on
    const waits = !item.answer && !!on && (!!on.answer || (on.speaker !== item.speaker && !item.big))
    if (waits) {
      this.held = { item, due: now }
      return false
    }
    this.on = item
    this.held = null
    return true
  }

  // `item` finished at `now`: the held turn to say next, unless it would start more than HOLD_MAX_MS late.
  ended(item: T, now: number): T | null {
    if (this.on !== item) return null
    const held = this.held
    this.on = null
    this.held = null
    if (!held || now - held.due > HOLD_MAX_MS) return null
    this.on = held.item
    return held.item
  }

  clear() {
    this.on = null
    this.held = null
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

// A viewer's question on the stage: "A viewer asks: …" until the answer arrives, then the answer for
// as long as it is spoken (`speak` resolves at its end; null when it isn't spoken), then the lines
// again. Resolves once the answer is in, so the ask box is free while it is spoken. `current` is false
// once the replay or a newer question replaced this one: it then changes nothing.
export async function airAnswer<A extends { text: string }>(
  question: string,
  ask: () => Promise<A | null>,
  speak: (answer: A) => Promise<void> | null,
  show: (caption: Caption | null) => void,
  current: () => boolean,
  readMs = READ_MS,
): Promise<void> {
  show({ kind: 'question', text: `A viewer asks: ${question}` })
  const answer = await ask()
  if (!current()) return
  if (!answer) return show(null)
  show({ kind: 'answer', text: answer.text, speaker: 'lead' })
  const aired = speak(answer) ?? new Promise<void>((r) => setTimeout(r, readMs))
  void aired.then(() => current() && show(null))
}
