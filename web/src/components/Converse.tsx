import { useEffect, useRef, useState } from 'react'
import { Conversation } from '@elevenlabs/client'
import { converseDoor, SILENT_MS, TalkPause } from '../converse'

interface Props {
  sport: string
  matchId: string
  momentIdx: number | null // the moment on screen; null before the first
  paused: boolean
  getReplayId: () => string | null
  onPause: () => void
  onPlay: () => void
  onHint: (hint: string) => void // why it could not start: the viewer still has Ask
}

// Talk (#380): a natural conversation with the commentator. The match pauses, the fan and an
// ElevenLabs agent talk (its own turn-taking and interruptions), and when the fan goes quiet, or
// presses Resume or Escape, the match carries on. Where it can't start, Ask above is still there.
export function Converse({ sport, matchId, momentIdx, paused, getReplayId, onPause, onPlay, onHint }: Props) {
  const [phase, setPhase] = useState<'idle' | 'starting' | 'talking'>('idle')
  const session = useRef<Conversation | null>(null)
  const pause = useRef(new TalkPause())
  const quiet = useRef<number | undefined>(undefined)
  const latest = useRef({ paused, onPause, onPlay })
  useEffect(() => {
    latest.current = { paused, onPause, onPlay }
  })

  const over = () => {
    window.clearTimeout(quiet.current)
    const s = session.current
    session.current = null
    setPhase('idle')
    pause.current.end(() => latest.current.onPlay())
    void s?.endSession().catch(() => {})
  }

  const start = async () => {
    const id = getReplayId()
    if (phase !== 'idle' || !id || momentIdx === null) return
    setPhase('starting')
    pause.current.begin(latest.current.paused, () => latest.current.onPause())
    const door = await converseDoor(id, sport, matchId, momentIdx)
    if (!door) return fail('Talking is not available just now. Ask still works.')
    try {
      session.current = await Conversation.startSession({
        signedUrl: door.signed_url,
        dynamicVariables: { ctx: door.ctx },
        onConnect: () => setPhase('talking'),
        onDisconnect: over,
        onError: () => fail('The conversation dropped. Ask still works.'),
        // the commentator has finished: if the fan says nothing, the talk is over and the match resumes
        onModeChange: ({ mode }) => {
          window.clearTimeout(quiet.current)
          if (mode === 'listening') quiet.current = window.setTimeout(over, SILENT_MS)
        },
        onMessage: ({ source }) => {
          if (source === 'user') window.clearTimeout(quiet.current)
        },
      })
    } catch {
      fail('Could not open the microphone. Ask still works.')
    }
  }

  const fail = (hint: string) => {
    over()
    onHint(hint)
  }

  useEffect(() => {
    if (phase === 'idle') return
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && over()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [phase])
  useEffect(() => over, [])

  return (
    <button type="button" className={`btn sm${phase === 'idle' ? '' : ' primary'}`} aria-pressed={phase !== 'idle'}
      disabled={phase === 'starting' || (phase === 'idle' && momentIdx === null)}
      onClick={phase === 'talking' ? over : start}
      title={phase === 'talking' ? 'End the talk and resume the match (or press Escape)' : 'Pause the match and talk with the commentator'}>
      {phase === 'talking' ? 'Resume' : phase === 'starting' ? 'Connecting' : 'Talk'}
    </button>
  )
}
