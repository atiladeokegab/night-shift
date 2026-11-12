import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'rolldown/experimental'
import type { StreamEvent } from './types.ts'

// Set up as live.test.ts does: .tsx through Vite's own transform, extensionless imports as Vite resolves them.
registerHooks({
  resolve(specifier, context, next) {
    if (/^\.\.?\//.test(specifier) && !/\.[a-z]+$/.test(specifier)) {
      for (const ext of ['.ts', '.tsx']) {
        try {
          return next(specifier + ext, context)
        } catch {
          // not this extension
        }
      }
    }
    return next(specifier, context)
  },
  load(url, context, next) {
    if (!url.endsWith('.tsx')) return next(url, context)
    const { code } = transformSync(fileURLToPath(url), readFileSync(new URL(url), 'utf8'), { jsx: { runtime: 'automatic' } })
    return { format: 'module', source: code, shortCircuit: true }
  },
})

// A stand-in EventSource: the test fires the server's events by hand.
class FakeSource {
  static CLOSED = 2
  static last: FakeSource
  readyState = 1
  handlers: Record<string, ((e: { data?: string }) => void)[]> = {}
  constructor() {
    FakeSource.last = this
  }
  addEventListener(type: string, h: (e: { data?: string }) => void) {
    ;(this.handlers[type] ??= []).push(h)
  }
  close() {
    this.readyState = 2
  }
  fire(type: string, data?: string) {
    for (const h of this.handlers[type] ?? []) h({ data })
  }
}

Object.assign(globalThis, { window: { location: { search: '' }, setInterval, clearInterval }, EventSource: FakeSource })
const { followReplay, videoStartAt } = await import('./api.ts')

test('a malformed stream event is skipped, and the stream carries on', () => {
  const got: StreamEvent[] = []
  followReplay('r1', (e) => got.push(e), () => {})
  assert.doesNotThrow(() => FakeSource.last.fire('line', '{not json'))
  FakeSource.last.fire('line', JSON.stringify({ line_id: 'l1', text: 'Goal' }))
  assert.deepEqual(got.map((e) => e.type), ['line'])
})

test("a server error event that isn't JSON still reaches the page", () => {
  const got: StreamEvent[] = []
  followReplay('r2', (e) => got.push(e), () => {})
  const err = console.error
  console.error = () => {}
  try {
    assert.doesNotThrow(() => FakeSource.last.fire('error', 'Internal Server Error'))
  } finally {
    console.error = err
  }
  assert.equal(got[0]?.type, 'error')
})

test('a deep link whose start lookup fails falls back to the match start, never rejects', async () => {
  const real = globalThis.fetch
  globalThis.fetch = () => Promise.reject(new TypeError('Failed to fetch'))
  try {
    assert.equal(await videoStartAt('m', 3), null)
  } finally {
    globalThis.fetch = real
  }
})

test('a render error shows an announced message, never a blank page', async () => {
  const { Boundary } = await import('./components/Boundary.tsx')
  const b = new Boundary({ children: null })
  b.state = Boundary.getDerivedStateFromError()
  const html = renderToStaticMarkup(createElement(() => b.render()))
  assert.match(html, /role="alert"/)
  // and the whole app sits inside it
  assert.match(readFileSync(new URL('./main.tsx', import.meta.url), 'utf8'), /<Boundary>\s*<App \/>\s*<\/Boundary>/)
})
