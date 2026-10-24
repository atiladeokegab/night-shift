import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'rolldown/experimental'

// The panel rendered to HTML in node, set up as live.test.ts does.
// The live page rendered to HTML in node: .tsx goes through Vite's own transform, and the app's
// extensionless imports resolve as Vite resolves them.
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
Object.assign(globalThis, { window: { location: { search: '' } } }) // api.ts reads ?demo on import
const { TeamFacts, TeamPanel } = await import('./components/TeamPanel.tsx')

const game = { date: '2016-04-20', opponent: 'Everton', home: true, score: '2-1', result: 'W' }
const headings = (html: string) => [...html.matchAll(/<h([1-6])[\s>]/g)].map((m) => Number(m[1]))

test('the panel reads top to bottom: headings, then short lists', () => {
  const html = renderToStaticMarkup(createElement(TeamFacts, { data: {
    teams: [
      { team: 'Chelsea', form: [game], squad: [{ name: 'Eden Hazard', matches: 21, headline: '9 goals in 21' }] },
      { team: 'Tottenham Hotspur', form: [], squad: [] },
    ],
    head_to_head: [game],
  } }))
  for (const s of ['<h3 id="team-Chelsea">Chelsea</h3>', 'Chelsea: won 1 of their last 1', '<h4>Squad</h4>', 'Eden Hazard: 9 goals in 21',
    '<h3 id="team-TottenhamHotspur">Tottenham Hotspur</h3>', 'Tottenham Hotspur: no recent games on record', '<h3 id="team-h2h">Head to head</h3>',
    'Won 2-1 at home against Everton, 20 April 2016']) assert.ok(html.includes(s), s)
})

test('a first match on record reads as such, with no squad box', () => {
  const html = renderToStaticMarkup(createElement(TeamFacts, { data: {
    teams: [{ team: 'Orlando Pride', form: [], squad: [], note: "This is Orlando Pride's first match on record" }, { team: 'Courage', form: [game], squad: [] }],
    head_to_head: [],
  } }))
  assert.ok(html.includes('first match on record') && !html.includes('no recent games'))
  assert.ok(!html.includes('<h4>Squad</h4>'))
})

test('Teams starts at h2 under the Live h1 and nests its headings without skips', () => {
  const panel = renderToStaticMarkup(createElement(TeamPanel, { sport: 'football', matchId: '1' }))
  const facts = renderToStaticMarkup(createElement(TeamFacts, { data: {
    teams: [
      { team: 'Chelsea', form: [game], squad: [{ name: 'Eden Hazard', matches: 21, headline: '9 goals in 21' }] },
      { team: 'Tottenham Hotspur', form: [], squad: [] },
    ],
    head_to_head: [game],
  } }))
  const levels = [1, ...headings(panel), ...headings(facts)]
  assert.deepEqual(levels, [1, 2, 3, 4, 3, 3])
  levels.forEach((level, i) => i && assert.ok(level <= levels[i - 1] + 1, `h${levels[i - 1]} then h${level}: ${levels.join(',')}`))
})

test('an empty graph says so instead of showing empty lists', () => {
  const html = renderToStaticMarkup(createElement(TeamFacts, { data: { teams: [{ team: 'A', form: [], squad: [] }], head_to_head: [] } }))
  assert.match(html, /No team facts/)
  assert.doesNotMatch(html, /<ul>/)
})

test('before the answer, the panel is a named region with a status', () => {
  const html = renderToStaticMarkup(createElement(TeamPanel, { sport: 'football', matchId: '1' }))
  assert.match(html, /aria-label="Teams"/)
  assert.match(html, /role="status"/)
})
