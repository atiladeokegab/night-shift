// Ask by voice (#139): push-to-talk over the browser's own speech recognition, kept out of React so the
// tests drive it with a fake. Only the slice of SpeechRecognition used here is typed.
export interface Recognizer {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
}

export const NO_MIC = 'Microphone blocked: allow it, or type your question'
export const NO_SPEECH = "Didn't catch that: hold the mic and speak, or type"

// The browser's recognizer, or null where it has none (the mic is then hidden and typing still works).
export function recognizer(): (() => Recognizer) | null {
  const w = globalThis as unknown as Record<string, (new () => Recognizer) | undefined>
  const R = w.SpeechRecognition ?? w.webkitSpeechRecognition
  return R ? () => new R() : null
}

export interface Heard {
  heard: (text: string) => void // the words so far, while the viewer talks
  done: (text: string) => void // the final words, once
  hint: (text: string) => void // once instead of `done`: mic denied or nothing heard
}

// Listens until a final result or the release, which is the returned stop: whatever was heard by then is sent.
export function listen(make: () => Recognizer, on: Heard): () => void {
  const r = make()
  r.lang = 'en-GB'
  r.interimResults = true
  r.continuous = false
  let text = ''
  let over = false
  const finish = (hint?: string) => {
    if (over) return
    over = true
    if (!hint && text) on.done(text)
    else on.hint(hint ?? NO_SPEECH)
  }
  r.onresult = (e) => {
    text = Array.from(e.results, (res) => res[0].transcript).join('').trim()
    if (e.results[e.results.length - 1]?.isFinal) finish()
    else on.heard(text)
  }
  r.onerror = (e) => finish(['not-allowed', 'service-not-allowed', 'audio-capture'].includes(e.error) ? NO_MIC : NO_SPEECH)
  r.onend = () => finish()
  try {
    r.start()
  } catch {
    finish(NO_MIC)
  }
  return () => r.stop()
}

// Mic on (#286): hands-free, the viewer talks whenever they like. The page's own voice reaches the mic too, so
// a transcript is the viewer's only if most of its words are not the line on air (or the one that just ended),
// and while a line is on air only from 3 words.
const words = (s: string) => s.toLowerCase().match(/[\p{L}\p{N}']+/gu) ?? []
export function isViewer(text: string, onAir: string | null): boolean {
  const said = words(text)
  if (!onAir || !said.length) return said.length > 0
  const line = new Set(words(onAir))
  return said.length >= 3 && said.filter((w) => line.has(w)).length / said.length < 0.6
}

export const MIC_FAILED = "Mic off: voice isn't working here, so type your question"
const DENIED = ['not-allowed', 'service-not-allowed', 'audio-capture']

export interface Always extends Heard {
  barge: () => void // the viewer started talking: hush the commentary now
}

// Listens until the returned stop, starting the recognizer again whenever it ends (Chrome stops after a
// silence); a session that ended within a second waits a second first, so a failing one never spins.
// Each sentence the viewer says goes to `done` once; an echo of `airing()` is never sent. `hint` turns it off.
export function listenAlways(make: () => Recognizer, on: Always, airing: () => string | null): () => void {
  let r: Recognizer | null = null
  let live = true
  let again: ReturnType<typeof setTimeout> | undefined
  const off = (hint?: string) => {
    if (!live) return
    live = false
    clearTimeout(again)
    r?.stop()
    if (hint) on.hint(hint)
  }
  const begin = () => {
    const rec = (r = make())
    rec.lang = 'en-GB'
    rec.interimResults = true
    rec.continuous = false
    const began = Date.now()
    let barged = false
    let shown = false
    rec.onresult = (e) => {
      const text = Array.from(e.results, (res) => res[0].transcript).join('').trim()
      const viewer = isViewer(text, airing())
      if (viewer && !barged) {
        barged = true
        on.barge()
      }
      const final = e.results[e.results.length - 1]?.isFinal
      if (viewer) (final ? on.done : on.heard)(text)
      else if (shown && final) on.heard('') // the words shown turned out to be the page's own
      shown = !final && (shown || viewer)
      barged &&= !final // the next sentence may barge in again
    }
    rec.onerror = (e) => {
      if (DENIED.includes(e.error)) off(NO_MIC)
      else if (!['no-speech', 'aborted'].includes(e.error)) off(MIC_FAILED)
    }
    rec.onend = () => {
      if (live) again = setTimeout(begin, Date.now() - began < 1000 ? 1000 : 0)
    }
    try {
      rec.start()
    } catch {
      off(NO_MIC)
    }
  }
  begin()
  return () => off()
}
