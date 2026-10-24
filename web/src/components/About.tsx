import { Nav, type Screen } from './Nav'

// The About page. It claims nothing the README doesn't.
export function About({ onGo }: { onGo: (screen: Screen) => void }) {
  return (
    <div className="page">
      <Nav current="about" onGo={onGo} />
      <main className="wrap">
        <p className="eyebrow">About Touchline</p>
        <h1>Every match deserves a commentator.</h1>
        <div className="about">
          <p>
            <strong>Most matches are played with nobody calling them.</strong> Touchline plays a match's broadcast
            highlights, and as each key moment plays it calls it in one short, emotional line, read aloud in a
            commentator's voice and shown as a large subtitle. A line is never shown or spoken before its moment
            reaches the picture.
          </p>
          <p>
            <strong>One commentator, four sports.</strong> The same agent, with the same prompt, calls football, cricket,
            basketball and F1. It reads the match's real event feed and never sees anything from later in the match
            than the moment it is calling.
          </p>
          <p>
            <strong>It learns from its producer.</strong> A producer corrects any line that's wrong. Every call and
            every fix goes through Mubit, which will train a smaller commentator of our own on them. That commentator
            isn't trained yet, so we make no claim for it.
          </p>
        </div>
        <p className="foot">
          Match data: StatsBomb open data (football), Cricsheet (cricket), NBA play-by-play (basketball) and OpenF1
          timing (F1). Video: broadcast highlights on YouTube, embedded and muted. Commentary is AI-generated.
        </p>
      </main>
    </div>
  )
}
