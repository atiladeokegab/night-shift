import { useCallback, useRef, useState } from 'react'
import { isDemo, lineAudioUrl } from './api'
import type { Line, Voice } from './types'

// Reads each line aloud in the chosen voice (A-6.3@1): the server's ElevenLabs audio
// (GET /lines/{id}/audio?voice=<id>, #25) first, the browser's own speech in that voice's accent when
// the route answers 503 or fails, or when the voice is one of the page's browser voices. A new line cuts off the one before it,
// so the voice never falls behind the match. `speaking` drives the design's "On air" bars.
export function useSpeech() {
  const available = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [on, setOn] = useState(available)
  const [speaking, setSpeaking] = useState(false)
  const playing = useRef<HTMLAudioElement | null>(null)
  const turn = useRef(0) // only the newest line may change `speaking`

  const hush = useCallback(() => {
    turn.current++
    playing.current?.pause()
    playing.current = null
    if (available) window.speechSynthesis.cancel()
    setSpeaking(false)
  }, [available])

  // Turning the voice off also stops whatever is being said now.
  const toggle = useCallback(
    (next: boolean) => {
      if (!next) hush()
      setOn(next)
    },
    [hush],
  )

  const speakInBrowser = useCallback(
    (text: string, accent: string, mine: number) => {
      if (!available) return
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = accent
      utterance.rate = 1.1
      utterance.onstart = () => turn.current === mine && setSpeaking(true)
      utterance.onend = utterance.onerror = () => turn.current === mine && setSpeaking(false)
      window.speechSynthesis.speak(utterance)
    },
    [available],
  )

  const say = useCallback(
    (line: Line, voice: Voice | null) => {
      if (!on) return
      hush()
      const mine = turn.current
      const accent = voice?.accent ?? 'en-GB'
      if (isDemo || voice?.browser) return speakInBrowser(line.text, accent, mine)
      const audio = new Audio(lineAudioUrl(line.line_id, voice?.id))
      playing.current = audio
      // A 503 (no key, upstream down) or a network failure lands here; only the current line falls back.
      const fallBack = () => {
        if (turn.current !== mine) return
        playing.current = null
        speakInBrowser(line.text, accent, mine)
      }
      audio.addEventListener('playing', () => turn.current === mine && setSpeaking(true))
      audio.addEventListener('ended', () => turn.current === mine && setSpeaking(false))
      audio.addEventListener('error', fallBack)
      audio.play().catch((e: DOMException) => {
        if (e.name !== 'AbortError') fallBack()
      })
    },
    [on, hush, speakInBrowser],
  )

  return { available, on, setOn: toggle, speaking, say, hush }
}
