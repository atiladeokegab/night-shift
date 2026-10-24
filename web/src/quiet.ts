// Describe quiet spells (#186): after QUIET_MS of play with no new line, one "Where are we?", then nothing
// more until the next line starts a new spell. Kept out of React so the tests reach it. Times in ms.

export const QUIET_MS = 15000
export const WHERE = 'Where are we?'

export class QuietSpell {
  private since = 0
  private fired = false

  // A new line ends the spell.
  said(now: number) {
    this.since = now
    this.fired = false
  }

  // True once per spell, the first time play has gone QUIET_MS without a line. Time off play (paused, a
  // question on air) doesn't count: the spell starts again from when play resumes.
  due(now: number, playing: boolean): boolean {
    if (!playing) {
      this.since = now
      return false
    }
    if (this.fired || now - this.since < QUIET_MS) return false
    this.fired = true
    return true
  }
}
