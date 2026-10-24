import { expect, test, type Locator, type Page } from '@playwright/test'

// #170's last untested claims: the W key, the Follow box and card by keyboard alone, and what a screen reader
// hears while the voice is silent (the caption becomes a live region, an answer is read out in full).
// The replay runs on the offline server; Ask, the player list and the profile are answered here.

const KOBE = /^Basketball ?Kobe's 81/ // the tile, never its Jump pill
const ANSWER = 'Kobe has 26 points, Toronto lead by 14.'

async function openLive(page: Page, width = 1280) {
  const asked: string[] = []
  await page.route(/\/replays\/[^/]+\/ask$/, async (r) => {
    const { question, moment_idx } = r.request().postDataJSON()
    asked.push(question)
    await r.fulfill({ json: { line_id: `a${asked.length}`, moment_idx, question, text: ANSWER } })
  })
  await page.route(/\/replays\/[^/]+\/players(\?|$)/, (r) => r.fulfill({ json: [
    { name: 'Kobe Bryant', team: 'Los Angeles Lakers', record: true, named: true },
    { name: 'Chris Bosh', team: 'Toronto Raptors', record: true, named: false },
  ] }))
  await page.route(/\/replays\/[^/]+\/players\/[^/]+\/profile/, (r) => r.fulfill({ json: {
    player: 'Kobe Bryant', team: 'Los Angeles Lakers', sport: 'basketball', window: { from: '2005-11-01', to: '2006-01-21' },
    before: null, tonight: { attempts: 20, made: 11 }, n: 0, small_sample: false, text: '',
  } }))
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: KOBE }).click()
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
  return asked
}

// Tab forward until the focus lands on `el`, as a keyboard user gets there.
async function tabTo(page: Page, el: Locator) {
  for (let i = 0; i < 60; i++) {
    if (await el.evaluate((e) => e === document.activeElement)) return
    await page.keyboard.press('Tab')
  }
  await expect(el).toBeFocused()
}

test('W asks "Where are we?" from anywhere but a text box, and the button says so', async ({ page }) => {
  const asked = await openLive(page)
  const where = page.getByRole('button', { name: 'Where are we?' })
  await expect(where).toHaveAttribute('aria-keyshortcuts', 'W')
  await expect(where).toHaveAttribute('title', 'Where are we? (W)')

  await page.locator('body').press('w')
  await expect.poll(() => asked).toEqual(['Where are we?'])
  await expect(page.locator('.log li.qa').first()).toContainText(ANSWER)

  // typed into the Ask box, a w is a letter, never a question
  await page.locator('#ask-q').press('w')
  await expect(page.locator('#ask-q')).toHaveValue('w')
  expect(asked).toEqual(['Where are we?'])
})

// A phone reaches Follow through its tab; a desktop shows the box beside the lines.
for (const width of [390, 1280]) {
  test(`Follow by keyboard alone at ${width}: the box opens and Escape closes its list, Enter follows, the card is named, Unfollow returns`, async ({ page }) => {
    await openLive(page, width)
    if (width < 700) {
      await tabTo(page, page.locator('#tab-follow'))
      await page.keyboard.press('Enter')
      await expect(page.locator('#tab-follow')).toHaveAttribute('aria-selected', 'true')
    }
    const box = page.getByRole('combobox', { name: 'Follow a player' })
    await tabTo(page, box)
    await expect(box).toHaveAttribute('aria-expanded', 'true')
    await expect(page.getByRole('list', { name: 'Players' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(box).toHaveAttribute('aria-expanded', 'false')
    await expect(page.getByRole('list', { name: 'Players' })).toHaveCount(0)

    await page.keyboard.type('Kobe')
    await expect(box).toHaveAttribute('aria-expanded', 'true')
    await page.keyboard.press('Enter')
    const card = page.getByRole('region', { name: 'Following Kobe Bryant' })
    await expect(card).toBeVisible()
    await expect(card.getByText('11 of 20', { exact: false })).toBeVisible()

    const unfollow = card.getByRole('button', { name: 'Unfollow' })
    await tabTo(page, unfollow)
    await page.keyboard.press('Enter')
    await expect(card).toHaveCount(0)
    await expect(box).toBeVisible()
  })
}

test('voice silent: the caption is a live region and an answer is read out in full; voiced again, neither', async ({ page }) => {
  await openLive(page)
  const caption = page.getByRole('region', { name: 'Caption' })
  const announced = page.locator('.lines p.sr-only[aria-live="polite"]')
  await expect(caption).toHaveAttribute('aria-live', 'off')

  await page.getByRole('button', { name: 'Mute commentary' }).press('Enter')
  await expect(page.getByRole('button', { name: 'Unmute commentary' })).toHaveAttribute('aria-pressed', 'true')
  await expect(caption).toHaveAttribute('aria-live', 'polite')
  await page.locator('body').press('w')
  await expect(announced).toHaveText(`Touchline: ${ANSWER}`)

  await page.getByRole('button', { name: 'Unmute commentary' }).press('Enter')
  await expect(caption).toHaveAttribute('aria-live', 'off')
  await expect(announced).toHaveText('Answer ready')
})
