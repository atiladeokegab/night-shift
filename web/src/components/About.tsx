import { Nav, type Screen } from './Nav'

// The About page, with docs/design.md's copy.
export function About({ onGo }: { onGo: (screen: Screen) => void }) {
  return (
    <div className="page">
      <Nav current="about" onGo={onGo} />
      <main className="wrap">
        <p className="eyebrow">About Touchline</p>
        <h1>Every match deserves a commentator.</h1>
        <div className="about">
          <p>
            <strong>Most matches are played with nobody calling them.</strong> Touchline watches a match's event feed
            and calls each key moment in one emotional spoken line, about a second after it happens, over the
            broadcast highlights.
          </p>
          <p><strong>One commentator, two sports.</strong> The same agent calls football and cricket; switch sport and it follows.</p>
          <p>
            <strong>It learns from its producer.</strong> A wrong line is fixed in one tap. Every call and every fix goes
            through Mubit, which trains a smaller commentator that matches the big one at lower cost.
          </p>
        </div>
        <p className="foot">Match data: StatsBomb open data and Cricsheet. Commentary is AI-generated.</p>
      </main>
    </div>
  )
}
