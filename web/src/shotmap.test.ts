// The shot map sheet's async boundary (#120 review): the real ShotMap.tsx, run with a minimal hook
// runtime and a loader whose answers the test releases by hand, so a fetch can stay open across a rewind,
// a player change or a late answer.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import ts from 'typescript'
import * as shots from './shots.ts'
import type { Shots } from './shots.ts'

type Node = { type: unknown; props: Record<string, unknown> }
type Ask = { name: string; idx: number; resolve: (s: Shots | null) => void }

// The sheet's Escape listener is the only browser API it touches.
if (!('window' in globalThis)) Object.assign(globalThis, { window: { addEventListener() {}, removeEventListener() {} } })

function mount() {
  const slots: unknown[] = []
  const deps: unknown[][] = []
  const cleanups: (() => void)[] = []
  let cursor = 0
  let pending: (() => void)[] = []
  const React = {
    useRef: (current: unknown) => ({ current }),
    useState(initial: unknown) {
      const i = cursor++
      if (!(i in slots)) slots[i] = initial
      return [slots[i], (v: unknown) => { slots[i] = v }]
    },
    useEffect(effect: () => (() => void) | void, next: unknown[]) {
      const i = cursor++
      if (!deps[i] || next.some((v, j) => v !== deps[i][j])) {
        cleanups[i]?.()
        deps[i] = next
        pending.push(() => { cleanups[i] = effect() ?? (() => {}) })
      }
    },
  }
  const jsx = (type: unknown, props: Record<string, unknown>) => ({ type, props: props ?? {} })
  const lib: Record<string, unknown> = { react: React, 'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'fragment' }, '../shots': shots, '../focus': { useSheetFocus() {} } }
  const src = readFileSync(new URL('./components/ShotMap.tsx', import.meta.url), 'utf8')
  const js = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText
  const mod = { exports: {} as { ShotMap: (p: unknown) => Node } }
  new Function('exports', 'require', 'module', js)(mod.exports, (n: string) => lib[n], mod)

  const asks: Ask[] = []
  const load = (name: string, idx: number) => new Promise<Shots | null>((resolve) => asks.push({ name, idx, resolve }))
  const render = (name: string, momentIdx: number) => {
    cursor = 0
    const tree = mod.exports.ShotMap({ name, momentIdx, load, onClose: () => {} })
    const run = pending
    pending = []
    run.forEach((f) => f())
    return chart(tree)
  }
  return { asks, render }
}

// The shots the Chart is drawn with, or null when the sheet shows no chart (loading, none, error).
function chart(node: unknown): Shots | null {
  if (!node || typeof node !== 'object') return null
  const n = node as Node
  if (typeof n.type === 'function' && n.type.name === 'Chart') return n.props.shots as Shots
  for (const child of [n.props?.children].flat(Infinity)) {
    const hit = chart(child)
    if (hit) return hit
  }
  return null
}

const map = (player: string, idxs: number[]): Shots => ({
  player, sport: 'basketball', season: [], zones: [],
  tonight: idxs.map((idx) => ({ idx, x: 0, y: 0, made: true })),
})
const tick = () => new Promise((r) => setTimeout(r))

test('a rewind with its fetch still open never shows a later shot', async () => {
  const { asks, render } = mount()
  render('Kobe Bryant', 10)
  asks[0].resolve(map('Kobe Bryant', [3, 10]))
  await tick()
  assert.deepEqual(render('Kobe Bryant', 10)?.tonight.map((s) => s.idx), [3, 10])
  const rewound = render('Kobe Bryant', 5) // the moment-5 fetch stays open
  assert.equal(asks.at(-1)?.idx, 5)
  assert.deepEqual(rewound?.tonight.map((s) => s.idx), [3])
})

test('a late answer for a later moment is dropped, and never shows past the moment on screen', async () => {
  const { asks, render } = mount()
  render('Kobe Bryant', 10)
  render('Kobe Bryant', 5) // rewound before the moment-10 answer came back
  asks[0].resolve(map('Kobe Bryant', [3, 10]))
  await tick()
  assert.equal(render('Kobe Bryant', 5), null) // still loading: the old answer was dropped
  asks[1].resolve(map('Kobe Bryant', [3]))
  await tick()
  assert.deepEqual(render('Kobe Bryant', 5)?.tonight.map((s) => s.idx), [3])
})

test("a player change with its fetch open shows loading, never the last player's map", async () => {
  const { asks, render } = mount()
  render('Kobe Bryant', 10)
  asks[0].resolve(map('Kobe Bryant', [10]))
  await tick()
  assert.ok(render('Kobe Bryant', 10))
  assert.equal(render('Lamar Odom', 10), null)
  render('Michael Jordan', 10)
  asks[1].resolve(map('Lamar Odom', [9])) // Odom's answer lands after the switch to Jordan
  await tick()
  assert.equal(render('Michael Jordan', 10), null)
  asks[2].resolve(map('Michael Jordan', [8]))
  await tick()
  assert.equal(render('Michael Jordan', 10)?.player, 'Michael Jordan')
})
