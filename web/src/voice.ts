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
