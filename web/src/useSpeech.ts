import { useCallback, useRef, useState } from 'react'
import { isDemo, lineAudioUrl } from './api'
import { Floor, loudness, voiceOf, type Speaker } from './turns'
import type { Line, Voice } from './types'

type Said = Pick<Line, 'line_id' | 'text'> & { speaker?: Speaker }
// `start` and `end` follow a viewer's answer on and off the air; `end(true)` when a decisive moment cut it off.
type OnAir = { line: Said; voice: Voice | null; speaker: Speaker; answer?: boolean; big?: boolean; decisive?: boolean; start?: () => void; end?: (cut?: boolean) => void }

// Reads each line aloud (A-6.3@1): the server's ElevenLabs audio (GET /lines/{id}/audio?voice=<id>, #25)
// first, the browser's own speech in that voice's language when the route answers 503 or fails, or
// when the voice is one of the page's browser voices. Each line is read in its speaker's voice (#131):
// the lead in the voice the viewer chose, the analyst in the sport's analyst voice. The Floor decides
// who speaks when: a line by the same speaker cuts off the one before it, so the voice never falls
// behind the match; only a big moment cuts in on the other speaker; only a decisive one cuts off a viewer's answer.
// `speaking` drives the design's "On air" bars; volume and mute apply to the commentary only.
export function useSpeech() {
  const available = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [on, setOn] = useState(available)
  const [speaking, setSpeaking] = useState(false)
  const [volume, setVolumeState] = useState(1)
  const [muted, setMuted] = useState(false)
  const level = useRef(1) // what the next sound plays at
  const silent = useRef(false) // muted: nothing is said until unmuted
  const playing = useRef<HTMLAudioElement | null>(null)
  const turn = useRef(0) // only the newest utterance may change `speaking`
  const floor = useRef(new Floor<OnAir>())
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

  // The commentary's volume (the video stays muted): the playing line follows at once, browser speech
  // from the next. Muting is silence: it hushes the line on air, and nothing is said until unmuted.
  const setVolume = useCallback(
    (next: number, mute: boolean) => {
      const v = loudness(next, false)
      setVolumeState(v)
      setMuted(mute)
      silent.current = mute
      level.current = v
      if (mute) hush()
      else if (playing.current) playing.current.volume = v
    },
    [hush],
  )

  // `done` runs once the utterance ends or fails for good, never after a newer one took over.
  const speakInBrowser = useCallback(
    (text: string, lang: string, sound: { pitch: number; rate: number }, mine: number, done: () => void) => {
      if (!available) return done()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = lang
      utterance.rate = sound.rate
      utterance.pitch = sound.pitch
      utterance.volume = level.current
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

  // Says what holds the floor; when it ends, whatever waited for it (if still in time) goes next.
  const play = useCallback(
    function play(item: OnAir) {
      stop()
      item.start?.()
      const mine = turn.current
      const { line, voice } = item
      const lang = voice?.lang ?? 'en-GB'
      const sound = voiceOf(item.speaker, voice?.id)
      const done = () => {
        item.end?.()
        const next = floor.current.ended(item, performance.now())
        if (next) play(next)
      }
      if (isDemo || voice?.browser) return speakInBrowser(line.text, lang, sound, mine, done)
      const audio = new Audio(lineAudioUrl(line.line_id, sound.id))
      audio.volume = level.current
      playing.current = audio
      // A 503 (no key, upstream down) or a network failure lands here; only the current line falls back,
      // once: the audio's error event and play()'s rejection both report the same failure.
      let fell = false
      const fallBack = () => {
        if (fell || turn.current !== mine) return
        fell = true
        playing.current = null
        speakInBrowser(line.text, lang, sound, mine, done)
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

  // A line as its moment plays. `big` (a goal, a wicket, a basket, an overtake) may cut in on the other speaker;
  // `decisive` (a goal, a wicket, a lead change, the final whistle) stops a viewer's answer.
  const say = useCallback(
    (line: Said, voice: Voice | null, big = false, decisive = false) => {
      if (!on || silent.current) return
      const item: OnAir = { line, voice, speaker: line.speaker ?? 'lead', big, decisive }
      if (floor.current.take(item, performance.now())) play(item)
    },
    [on, play],
  )

  // A viewer's answer, in the analyst's voice at a natural gap (#139): it waits until the line on air
  // ends with no big moment due (`bigDue`), checked again every 250 ms while the air is quiet. `started`
  // runs as it goes on air; resolves when it has been said (or hushed), true when a decisive moment cut it
  // off. null when the voice is off or muted, so the caller shows the answer for a read time instead.
  const sayAnswer = useCallback(
    (answer: Said, voice: Voice | null, started: () => void, bigDue: () => boolean): Promise<boolean> | null => {
      if (!on || silent.current) return null
      aired.current?.() // a newer answer replaces the one still waiting or on air
      floor.current.bigDue = bigDue
      floor.current.onCut = (cut) => cut.end?.(true)
      return new Promise<boolean>((resolve) => {
        const end = (cut = false) => {
          clearInterval(wait)
          if (aired.current === end) aired.current = null
          resolve(cut)
        }
        const item: OnAir = { line: answer, voice, speaker: 'analyst', answer: true, start: started, end }
        const wait = setInterval(() => {
          const next = floor.current.gap()
          if (next) play(next)
        }, 250)
        aired.current = end
        if (floor.current.take(item, performance.now())) play(item)
      })
    },
    [on, play],
  )

  return { available, on, setOn: toggle, speaking, say, sayAnswer, hush, volume, muted, setVolume }
}
