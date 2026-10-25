import { Component, type ReactNode } from 'react'

// The page's last resort: a render error anywhere shows this, announced, instead of a blank page.
export class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error('render failed', error)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="notice glass err" role="alert">
        Something went wrong. Reload the page to carry on.
        <button className="btn" onClick={() => window.location.reload()}>Reload</button>
      </div>
    )
  }
}
