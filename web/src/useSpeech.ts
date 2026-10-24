import { useCallback, useRef, useState } from 'react'
import { isDemo, lineAudioUrl } from './api'
import { Floor } from './player'
import type { Line, Voice } from './types'

type Said = Pick<Line, 'line_id' | 'text'>

// Reads each line aloud in the chosen voice (A-6.3@1): the server's ElevenLabs audio
// (GET /lines/{id}/audio?voice=<id>, #25) first, the browser's own speech in that voice's language when
// the route answers 503 or fails, or when the voice is one of the page's browser voices. A new line cuts off the one before it,
// so the voice never falls behind the match. A viewer's answer is never cut off (#131): a line due
// while it is spoken waits on the Floor. `speaking` drives the design's "On air" bars.
export function useSpeech() {
  const available = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [on, setOn] = useState(available)
  const [speaking, setSpeaking] = useState(false)
  const playing = useRef<HTMLAudioElement | null>(null)
  const turn = useRef(0) // only the newest utterance may change `speaking`
  const floor = useRef(new Floor<{ line: Said; voice: Voice | null }>())
  const aired = useRef<(() => void) | null>(null) // ends the answer on air, so its subtitle comes down

  // Stops the sound only.
  const stop = useCallback(() => {
    turn.current++
    playing.current?.pause()
    playing.current = null
    if (available) window.speechSynthesis.cancel()
    setSpeaking(false)
  }, [available])

  // Stops whatever is being said and drops a held line: a rewind, a pause, leaving, the voice off.
  const hush = useCallback(() => {
    stop()
    floor.current.clear()
    aired.current?.()
    aired.current = null
  }, [stop])

  // Turning the voice off also stops whatever is being said now.
  const toggle = useCallback(
    (next: boolean) => {
      if (!next) hush()
      setOn(next)
    },
    [hush],
  )

  // `done` runs once the utterance ends or fails for good, never after a newer one took over.
  const speakInBrowser = useCallback(
    (text: string, lang: string, mine: number, done: () => void) => {
      if (!available) return done()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = lang
      utterance.rate = 1.1
      utterance.onstart = () => turn.current === mine && setSpeaking(true)
      utterance.onend = utterance.onerror = () => {
        if (turn.current !== mine) return
        setSpeaking(false)
        done()
      }
      window.speechSynthesis.speak(utterance)
    },
    [available],
  )

  const play = useCallback(
    (line: Said, voice: Voice | null, done: () => void) => {
      stop()
      const mine = turn.current
      const lang = voice?.lang ?? 'en-GB'
      if (isDemo || voice?.browser) return speakInBrowser(line.text, lang, mine, done)
      const audio = new Audio(lineAudioUrl(line.line_id, voice?.id))
      playing.current = audio
      // A 503 (no key, upstream down) or a network failure lands here; only the current line falls back,
      // once: the audio's error event and play()'s rejection both report the same failure.
      let fell = false
      const fallBack = () => {
        if (fell || turn.current !== mine) return
        fell = true
        playing.current = null
        speakInBrowser(line.text, lang, mine, done)
      }
      audio.addEventListener('playing', () => turn.current === mine && setSpeaking(true))
      audio.addEventListener('ended', () => {
        if (turn.current !== mine) return
        setSpeaking(false)
        done()
      })
      audio.addEventListener('error', fallBack)
      audio.play().catch((e: DOMException) => {
        if (e.name !== 'AbortError') fallBack()
      })
    },
    [stop, speakInBrowser],
  )

  const say = useCallback(
    (line: Said, voice: Voice | null) => {
      if (!on) return
      const now = floor.current.line({ line, voice }, performance.now())
      if (now) play(now.line, now.voice, () => {})
    },
    [on, play],
  )

  // A viewer's answer: resolves when it has been said (or hushed), then the held line, if still in time,
  // is spoken. null when the voice is off, so the caller shows the answer for a read time instead.
  const sayAnswer = useCallback(
    (answer: Said, voice: Voice | null): Promise<void> | null => {
      if (!on) return null
      aired.current?.() // a newer answer takes the floor from the one still on air
      floor.current.answer()
      return new Promise<void>((resolve) => {
        aired.current = resolve
        play(answer, voice, () => {
          aired.current = null
          resolve()
          const next = floor.current.answered(performance.now())
          if (next) play(next.line, next.voice, () => {})
        })
      })
    },
    [on, play],
  )

  return { available, on, setOn: toggle, speaking, say, sayAnswer, hush }
}
