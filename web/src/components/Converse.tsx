import { useEffect, useLayoutEffect, useRef, useState } from 'react'
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
  const identity = JSON.stringify([sport, matchId, getReplayId()])
  const session = useRef<Conversation | null>(null)
  const pause = useRef(new TalkPause())
  const quiet = useRef<number | undefined>(undefined)
  const tries = useRef(0) // each start and each end moves it on, so a talk ended while connecting stays ended
  const latest = useRef({ paused, onPause, onPlay })
  useEffect(() => {
    latest.current = { paused, onPause, onPlay }
  })

  const over = () => {
    tries.current++
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
    const mine = ++tries.current
    const live = () => tries.current === mine
    const door = await converseDoor(id, sport, matchId, momentIdx)
    if (!live()) return
    if (!door) return fail('Talking is not available just now. Ask still works.')
    try {
      const s = await Conversation.startSession({
        signedUrl: door.signed_url,
        dynamicVariables: { ctx: door.ctx },
        onConnect: () => live() && setPhase('talking'),
        onDisconnect: () => live() && over(),
        onError: () => live() && fail('The conversation dropped. Ask still works.'),
        // the commentator has finished: if the fan says nothing, the talk is over and the match resumes
        onModeChange: ({ mode }) => {
          if (!live()) return
          window.clearTimeout(quiet.current)
          if (mode === 'listening') quiet.current = window.setTimeout(over, SILENT_MS)
        },
        onMessage: ({ source }) => {
          if (live() && source === 'user') window.clearTimeout(quiet.current)
        },
      })
      if (live()) session.current = s
      else void s.endSession().catch(() => {}) // ended while it connected: hang up, the match already plays
    } catch {
      if (live()) fail('Could not open the microphone. Ask still works.')
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
  useLayoutEffect(() => () => over(), [identity])

  return (
    <button type="button" className={`btn sm${phase === 'idle' ? '' : ' primary'}`} aria-pressed={phase !== 'idle'} aria-busy={phase === 'starting'}
      disabled={phase === 'starting' || (phase === 'idle' && momentIdx === null)}
      onClick={phase === 'talking' ? over : start}
      title={phase === 'talking' ? 'End the talk and resume the match (or press Escape)' : 'Pause the match and talk with the commentator'}>
      {phase === 'talking' ? 'Resume' : phase === 'starting' ? 'Connecting' : 'Talk'}
    </button>
  )
}
