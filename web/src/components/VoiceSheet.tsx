import { useEffect } from 'react'
import { sheetName, sheetVoices } from '../teams'
import { SPORT_NAMES, type Sport, type Voice } from '../types'

interface Props {
  sports: Sport[] // the sports the server has matches for
  voices: Voice[]
  chosen: (sport: Sport) => Voice | null
  available: boolean
  on: boolean
  onToggle: (on: boolean) => void
  describeQuiet: boolean // #186: a "Where are we?" after 15 s of play with no line
  onDescribeQuiet: (on: boolean) => void
  onPick: (sport: Sport, voice: Voice) => void
  onClose: () => void
}

// The voice setting (docs/design.md; A-6.3@1): on/off, then per sport the voices GET /voices lists,
// the default marked. A change applies from the next line, without reloading.
export function VoiceSheet({ sports, voices, chosen, available, on, onToggle, describeQuiet, onDescribeQuiet, onPick, onClose }: Props) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  return (
    <div className="scrim" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet glass" role="dialog" aria-modal="true" aria-labelledby="voice-h">
        <h2 id="voice-h">Commentator voice</h2>
        <p className="lede">Each line is spoken in this voice. A change applies from the next line, without reloading.</p>
        {available ? (
          <div className="toggle">
            <span>Voice</span>
            <button className="switch" role="switch" aria-checked={on} aria-label="Voice" onClick={() => onToggle(!on)} />
          </div>
        ) : (
          <p className="err-text" role="alert">Voice unavailable. Subtitles carry on.</p>
        )}
        <div className="toggle">
          <span>Describe quiet spells</span>
          <button className="switch" role="switch" aria-checked={describeQuiet} aria-label="Describe quiet spells"
            onClick={() => onDescribeQuiet(!describeQuiet)} />
        </div>
        <div className="voices">
          {sports.map((sport) => (
            <div key={sport} role="radiogroup" aria-label={`${SPORT_NAMES[sport]} voice`}>
              <span className="label">{SPORT_NAMES[sport]}</span>
              <div className="opts">
                {sheetVoices(voices, sport, chosen(sport)?.id).map((v) => (
                  <label key={v.id} className="opt">
                    <input type="radio" name={`voice-${sport}`} checked={chosen(sport)?.id === v.id}
                      disabled={!on || !available} onChange={() => onPick(sport, v)} />
                    <span>
                      {sheetName(v)}
                      {v.default_for === sport && <em>Default</em>}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="actions">
          <span className="spacer" />
          <button className="btn primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  )
}
