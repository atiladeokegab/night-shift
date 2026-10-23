import { useCallback, useEffect, useState } from 'react'

// Reads lines aloud with the browser's own voice (IDEA.md ceiling: a hosted voice only if this sounds flat).
// A new line cuts off the one before it, so the voice never falls behind the match.
export function useSpeech() {
  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [on, setOn] = useState(supported)

  useEffect(() => {
    if (!on && supported) window.speechSynthesis.cancel()
  }, [on, supported])

  const say = useCallback(
    (text: string) => {
      if (!on || !supported) return
      window.speechSynthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = 'en-GB'
      utterance.rate = 1.1
      window.speechSynthesis.speak(utterance)
    },
    [on, supported],
  )

  return { supported, on, setOn, say }
}
