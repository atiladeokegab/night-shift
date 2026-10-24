import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// #170: the page works for a fan who cannot see it. axe finds no serious or critical violation on the wall
// or the live screen, every control is a 44 px target, and a keyboard alone starts a match and asks a question.

const WIDTHS = [390, 1280]
const KOBE = /^Basketball ?Kobe's 81/ // the tile, never its Jump pill

// Every utterance the page starts: the browser's speech and any audio element (ElevenLabs lines).
async function listen(page: Page) {
  await page.addInitScript(() => {
    const said: string[] = ((window as unknown as { said: string[] }).said = [])
    const speak = window.speechSynthesis?.speak.bind(window.speechSynthesis)
    if (speak) window.speechSynthesis.speak = (u: SpeechSynthesisUtterance) => (said.push(u.text), speak(u))
    const play = HTMLMediaElement.prototype.play
    HTMLMediaElement.prototype.play = function () {
      said.push(`audio ${this.currentSrc || this.src}`)
      return play.call(this)
    }
  })
}
const said = (page: Page) => page.evaluate(() => (window as unknown as { said: string[] }).said)

async function openLive(page: Page) {
  await page.getByRole('button', { name: KOBE }).click()
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
}

async function serious(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .exclude('iframe[src*="youtube"]') // YouTube's own player: third-party markup the page can't change
    .analyze()
  return violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)
}

// A control's target is the area a tap lands on it: a 44 px circle centred on it must hit it all round.
// Inline links in running text are exempt (WCAG 2.5.8).
const smallTargets = (page: Page) => page.evaluate(() => {
  const out: string[] = []
  for (const el of document.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, [role=tab]')) {
    let r = el.getBoundingClientRect()
    if (!r.width || !r.height || el.closest('.sr-only, p, [aria-hidden=true]') || getComputedStyle(el).visibility === 'hidden') continue
    // A control in a sideways scroller (the sport tabs) is tapped once scrolled to: measure it there.
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      if (!/auto|scroll/.test(getComputedStyle(a).overflowX) || a.scrollWidth <= a.clientWidth) continue
      const ar = a.getBoundingClientRect(), er = el.getBoundingClientRect()
      a.scrollLeft += er.left < ar.left ? er.left - ar.left : Math.max(0, er.right - ar.right)
      r = el.getBoundingClientRect()
      break
    }
    const mine = (hit: Element | null) => !!hit && (el === hit || el.contains(hit) || !!el.labels?.length && [...el.labels].some((l) => l.contains(hit)))
    const circleMiss = (cx: number, cy: number) => {
      for (let i = 0; i < 8; i++) {
        const a = (i * Math.PI) / 4, x = cx + Math.cos(a) * 21.5, y = cy + Math.sin(a) * 21.5
        if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue // off screen: hit testing can't see it
        const hit = document.elementFromPoint(x, y)
        if (!mine(hit)) return `at ${i * 45}° hits ${hit ? `${hit.tagName.toLowerCase()}.${hit.className}` : 'nothing'}`
      }
      return ''
    }
    // A hit area may reach further one way than the other: failing a circle on the box, try one on the region that takes the tap.
    let miss = circleMiss(r.left + r.width / 2, r.top + r.height / 2)
    if (miss) {
      let [x0, y0, x1, y1] = [r.right, r.bottom, r.left, r.top]
      for (let x = r.left - 30; x <= r.right + 30; x += 2) for (let y = r.top - 30; y <= r.bottom + 30; y += 2)
        if (x >= 0 && y >= 0 && x <= innerWidth && y <= innerHeight && mine(document.elementFromPoint(x, y))) [x0, y0, x1, y1] = [Math.min(x0, x), Math.min(y0, y), Math.max(x1, x), Math.max(y1, y)]
      if (x0 < x1 && !circleMiss((x0 + x1) / 2, (y0 + y1) / 2)) miss = ''
    }
    if (miss) out.push(`${el.tagName.toLowerCase()} "${el.getAttribute('aria-label') ?? el.textContent?.trim().slice(0, 30)}" ${Math.round(r.width)}x${Math.round(r.height)} ${miss}`)
  }
  return out
})

// Low-vision visitors swap fonts and enlarge text: with the fallback font (what a blocked web font gives, and
// wider), then text at 200%, the bars may wrap, but no control's 44 px target may land on another's.
// In the same page, so no replay starts beyond the test's own.
async function heldUnderFallbackAndZoom(page: Page, screen: string) {
  const fallback = await page.addStyleTag({ content: ':root { --display: ui-sans-serif, system-ui, sans-serif; --body: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif }' })
  expect(await smallTargets(page), `${screen}, fallback font`).toEqual([])
  const zoom = await page.addStyleTag({ content: 'html { font-size: 200% }' })
  expect(await smallTargets(page), `${screen}, fallback font, text at 200%`).toEqual([])
  await zoom.evaluate((e) => e.remove())
  await fallback.evaluate((e) => e.remove())
}

for (const width of WIDTHS) {
  test(`axe and 44 px targets on the wall and the live screen at ${width}, also with the fallback font and text at 200%`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    await expect(page.getByRole('button', { name: KOBE })).toBeVisible()
    expect(await serious(page), 'wall').toEqual([])
    expect(await smallTargets(page), 'wall').toEqual([])
    await heldUnderFallbackAndZoom(page, 'wall')
    await openLive(page)
    expect(await serious(page), 'live').toEqual([])
    expect(await smallTargets(page), 'live').toEqual([])
    await heldUnderFallbackAndZoom(page, 'live')
  })
}

test('axe on the review queue: each Fix button says its visible words first', async ({ page }) => {
  const item = {
    line_id: 'l1', match_id: '3754092', match: 'Chelsea v Tottenham Hotspur', sport: 'football', moment_idx: 28,
    clock: '57:41', period: 2, score: 'Chelsea 1, Tottenham 2', play: 'A substitution', text: 'Tottenham still lead one-nil.',
    wrong: ['one-nil is not the score (1-2)'], lines: 2, others: ['Spurs lead one-nil.'], later_check: false,
  }
  await page.route('**/review', (r) => r.fulfill({ json: [item] }))
  await page.goto('/#review')
  await expect(page.locator('.flag .btn.primary')).toBeVisible()
  expect(await serious(page), 'review').toEqual([])
})

test('keyboard only: Tab to Kobe, Enter, it is called aloud; Tab to Ask, Enter, the answer is spoken', async ({ page }) => {
  await listen(page)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await expect(page.getByRole('button', { name: KOBE })).toBeVisible()
  const focused = () => page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null
    return el ? `${el.id} ${el.getAttribute('aria-label') ?? ''} ${el.textContent ?? ''}`.trim() : ''
  })
  const tabTo = async (to: RegExp) => {
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press('Tab')
      if (to.test(await focused())) return
    }
    throw new Error(`Tab never reached ${to}`)
  }

  await tabTo(KOBE)
  // The focus ring shows where the keyboard is.
  await expect(page.locator(':focus-visible')).toHaveCSS('outline-style', 'solid')
  await page.keyboard.press('Enter')
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
  await expect.poll(() => said(page), { timeout: 15_000 }).not.toEqual([]) // spoken with no further clicks
  await expect(page.getByRole('status').filter({ hasText: /^Playing Kobe's 81 v Toronto$/ })).toBeAttached()
  // A line on the caption is heard, never announced over the voice.
  await expect(page.getByRole('region', { name: 'Caption' })).toHaveAttribute('aria-live', 'off')

  await tabTo(/^ask-q\b/)
  const before = (await said(page)).length
  await page.keyboard.type('How many points has Kobe got?')
  await page.keyboard.press('Enter')
  const answer = page.locator('.log li.qa').first()
  await expect(answer).toContainText('How many points has Kobe got?', { timeout: 30_000 })
  await expect(answer).not.toHaveClass(/off/)
  await expect(page.getByText('Answer ready', { exact: true })).toBeAttached()
  const text = (await answer.locator('.text > span').textContent())!
  await expect.poll(async () => (await said(page)).slice(before), { timeout: 30_000 }).toContain(text)

  // A sheet takes the focus and gives it back: no trap, no lost place.
  await page.getByRole('button', { name: /^Voice:/ }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Commentator voice' }).locator(':focus')).toHaveCount(1)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: /^Voice:/ })).toBeFocused()
})
