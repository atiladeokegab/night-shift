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
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height || el.closest('.sr-only, p, [aria-hidden=true]') || getComputedStyle(el).visibility === 'hidden') continue
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2
    let where = ''
    const miss = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => (i * Math.PI) / 4).find((a) => {
      const x = cx + Math.cos(a) * 21.5, y = cy + Math.sin(a) * 21.5
      if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false // off screen: hit testing can't see it
      const hit = document.elementFromPoint(x, y)
      where = `at ${Math.round((a * 180) / Math.PI)}° hits ${hit ? `${hit.tagName.toLowerCase()}.${hit.className}` : 'nothing'}`
      return !hit || !(el === hit || el.contains(hit) || (el.labels?.length && [...el.labels].some((l) => l.contains(hit))))
    })
    if (miss) out.push(`${el.tagName.toLowerCase()} "${el.getAttribute('aria-label') ?? el.textContent?.trim().slice(0, 30)}" ${Math.round(r.width)}x${Math.round(r.height)} ${where}`)
  }
  return out
})

for (const width of WIDTHS) {
  test(`axe and 44 px targets on the wall and the live screen at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    await expect(page.getByRole('button', { name: KOBE })).toBeVisible()
    expect(await serious(page), 'wall').toEqual([])
    expect(await smallTargets(page), 'wall').toEqual([])
    await openLive(page)
    expect(await serious(page), 'live').toEqual([])
    expect(await smallTargets(page), 'live').toEqual([])
  })
}

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
