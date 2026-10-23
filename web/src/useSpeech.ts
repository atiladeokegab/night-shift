import { useCallback, useEffect, useRef, useState } from 'react'
import { isDemo, lineAudioUrl } from './api'
import type { Line } from './types'

// Reads each line aloud: the server's ElevenLabs voice (GET /lines/{id}/audio, #25) first, the
// browser's own speech when that route answers 503 or fails. A new line cuts off the one before it,
// so the voice never falls behind the match.
export function useSpeech() {
  const browser = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [on, setOn] = useState(true)
  const playing = useRef<HTMLAudioElement | null>(null)

  const hush = useCallback(() => {
    playing.current?.pause()
    playing.current = null
    if (browser) window.speechSynthesis.cancel()
  }, [browser])

  useEffect(() => {
    if (!on) hush()
  }, [on, hush])

  const speakInBrowser = useCallback(
    (text: string) => {
      if (!browser) return
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = 'en-GB'
      utterance.rate = 1.1
      window.speechSynthesis.speak(utterance)
    },
    [browser],
  )

  const say = useCallback(
    (line: Line) => {
      if (!on) return
      hush()
      if (isDemo) return speakInBrowser(line.text)
      const audio = new Audio(lineAudioUrl(line.line_id))
      playing.current = audio
      // A 503 (no key, upstream down) or a network failure lands here; a newer line has already
      // replaced this one if `playing` moved on, so only the current line falls back.
      const fallBack = () => {
        if (playing.current === audio) {
          playing.current = null
          speakInBrowser(line.text)
        }
      }
      audio.addEventListener('error', fallBack)
      audio.play().catch((e: DOMException) => {
        if (e.name !== 'AbortError') fallBack()
      })
    },
    [on, hush, speakInBrowser],
  )

  return { on, setOn, say, hush }
}
