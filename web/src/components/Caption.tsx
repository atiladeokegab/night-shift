import type { ReactNode } from 'react'
import type { Caption as CaptionData } from '../player'

interface Props {
  caption: CaptionData | null
  tag?: string // the moment tag of the line or answer
  fixed?: boolean // a producer's fix replaced the line
  asked?: string // an answer's question
  children?: ReactNode // a state in place of the caption: waiting, off air
}

// The caption card docked under the video (#132): the current caption with a speaker chip and the moment
// tag; for Ask, "A viewer asks: ..." and then the answer. Long text wraps inside the card, never clipped.
export function Caption({ caption, tag, fixed, asked, children }: Props) {
  const speaker = caption?.kind === 'question' ? 'Viewer' : caption?.speaker === 'analyst' ? 'Analyst' : 'Lead'
  return (
    <section className={`caption glass${fixed ? ' fixed' : ''}`} aria-label="Caption" aria-live="polite">
      {children ?? (caption && (
        <div key={caption.kind + caption.text}>
          <div className="cap-h">
            <span className={`chip ${speaker.toLowerCase()}`}>{speaker}</span>
            {tag && <span className={`tag${fixed ? ' fixed' : ''}`}>{fixed ? 'Fixed · ' : ''}{tag}</span>}
          </div>
          {caption.kind === 'question' ? (
            <p className="cap-asks">A viewer asks: {caption.text}</p>
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
