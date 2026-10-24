import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

// The Teams tab (#375) in a real browser, on the two matches the demo uses. GET /teams is answered from
// responses recorded from the offline server (e2e/fixtures), so the page is checked against real data: no
// empty cell, no result from the match's own day or later, and the tab reachable by keyboard alone.

interface Recorded {
  date: string
  teams: { teams: { team: string; form: { date: string }[]; squad: unknown[] }[]; head_to_head: { date: string }[] }
}
const recorded = (name: string): Recorded => JSON.parse(readFileSync(new URL(`./fixtures/teams-${name}.json`, import.meta.url), 'utf8'))

const MATCHES: { name: string; tile: RegExp; facts?: boolean }[] = [
  { name: 'chelsea-spurs', tile: /^Football ?Battle of the Bridge/ },
  { name: 'lakers-raptors', tile: /^Basketball ?Kobe's 81/, facts: true }, // the basketball graph has landed (#402)
]

async function openTeams(page: Page, tile: RegExp, body: Recorded['teams'], width = 1280) {
  await page.route('**/teams/**', (r) => r.fulfill({ json: body }))
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: tile }).click()
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
  await page.keyboard.press('t')
  await expect(page.getByRole('heading', { name: 'Teams', level: 2 })).toBeFocused()
  return page.getByRole('region', { name: 'Teams' })
}

for (const { name, tile, facts: expected } of MATCHES) {
  test(`Teams on ${name}: no empty cell and no result from the match day or later`, async ({ page }) => {
    const rec = recorded(name)
    // the recording itself: nothing in it is dated on or after the match
    const dates = [...rec.teams.teams.flatMap((t) => t.form), ...rec.teams.head_to_head].map((g) => g.date)
    expect(dates.every((d) => d < rec.date), 'recorded dates').toBe(true)

    const panel = await openTeams(page, tile, rec.teams)
    const facts = rec.teams.teams.some((t) => t.form.length || t.squad.length) || rec.teams.head_to_head.length
    if (expected) expect(facts, 'the recording has real team facts').toBe(true)
    if (!facts) {
      await expect(panel.getByText('No team facts for this match.')).toBeVisible()
      return
    }
    for (const t of rec.teams.teams) await expect(panel.getByRole('heading', { name: t.team, level: 3 })).toBeVisible()
    if (expected) {
      await expect(panel.getByText('No team facts for this match.')).toHaveCount(0)
      await expect(panel.getByText('Kobe Bryant').first()).toBeVisible()
    }
    const cells = await panel.locator('li, p, h3, h4').allInnerTexts()
    expect(cells.length).toBeGreaterThan(0)
    for (const text of cells) {
      expect(text.trim(), 'an empty cell').not.toBe('')
      expect(text, 'a broken value').not.toMatch(/undefined|NaN|null|\[object/)
    }
    // every game the panel shows is dated before the match
    const shown = (await panel.locator('li').allInnerTexts()).flatMap((t) => t.match(/\d{1,2} \w+ \d{4}$/) ?? [])
    expect(shown.length).toBeGreaterThan(0)
    for (const day of shown) expect(new Date(`${day} UTC`).toISOString().slice(0, 10) < rec.date, day).toBe(true)
  })

  test(`Teams on ${name}: the tab works with the keyboard alone`, async ({ page }) => {
    const panel = await openTeams(page, tile, recorded(name).teams, 390) // the tab bar shows below 900 px
    await expect(page.locator('#tab-teams')).toHaveAttribute('aria-selected', 'true')
    await expect(panel).toBeVisible()
    // Lines by keyboard (focus its tab, Enter), then T brings Teams back
    await page.locator('#tab-lines').focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('#tab-lines')).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('#pane-teams')).toHaveAttribute('data-on', 'false')
    await page.locator('body').click({ position: { x: 1, y: 1 } })
    await page.keyboard.press('t')
    await expect(page.locator('#tab-teams')).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('heading', { name: 'Teams', level: 2 })).toBeFocused()
  })
}
