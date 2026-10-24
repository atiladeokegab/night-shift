import type { ReactNode } from 'react'
import type { Caption as CaptionData } from '../turns'

interface Props {
  caption: CaptionData | null
  tag?: string // the moment tag of the line or answer
  fixed?: boolean // a producer's fix replaced the line
  asked?: string // an answer's question
  offAir?: boolean // the answer came back off air: a calm state, never a headline (#153)
  pending?: string // a viewer's question waiting for its answer, one line in the header (#153)
  title?: string // the match, at the header's end (a phone drops it while a question waits)
  children?: ReactNode // a state in place of the caption: waiting, off air
  stale?: boolean // an answer from before the latest key moment: dimmed, never read as now
  announce?: boolean // #170: read out by a screen reader only while the voice is silent, never over it
}

// The caption card docked under the video (#132): the current caption with a speaker chip and the moment
// tag, then the line; an answer shows under its question. Long text wraps inside the card, never clipped.
export function Caption({ caption, tag, fixed, asked, offAir, pending, title, children, stale, announce }: Props) {
  const speaker = caption?.kind === 'question' ? 'Viewer' : caption?.speaker === 'analyst' ? 'Analyst' : 'Lead'
  return (
    <section className={`caption glass${fixed ? ' fixed' : ''}${stale ? ' stale' : ''}`} aria-label="Caption" aria-live={announce ? 'polite' : 'off'}>
      {children ?? (caption && (
        <div key={caption.kind + caption.text}>
          <div className="cap-h">
            <span className={`chip ${speaker.toLowerCase()}`}>{speaker}</span>
            {tag && <span className={`tag${fixed ? ' fixed' : ''}`}>{fixed ? 'Fixed · ' : ''}{tag}</span>}
            {pending && <span className="cap-side"><span className="chip viewer">Viewer</span><span className="cap-q">{pending}</span></span>}
            {title && <span className="cap-side cap-title">{title}</span>}
          </div>
          {offAir ? (
            <p className="cap-state">Couldn't answer that one. Try again.</p>
          ) : caption.kind === 'question' ? (
            // The Viewer chip already says who asks.
            <p className="cap-asks">{caption.text.replace(/^A viewer asks:\s*/, '')}</p>
          ) : (
            <>
              {asked && <p className="cap-asks">A viewer asks: {asked}</p>}
              <p className="cap-text">{caption.text}</p>
            </>
          )}
        </div>
      ))}
    </section>
  )
}
