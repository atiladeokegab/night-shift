import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

const item = JSON.parse(readFileSync(new URL('./fixtures/review-item.json', import.meta.url), 'utf8'))

// #462: the fix sheet from the Review queue (docs/design.md "Fix sheet", A-4.1). It opens on a card with the
// line as said, Escape closes it without sending, a 503 keeps it open with the producer's text to send again,
// and a 200 closes it. The queue and the fix endpoint are mocked, so no store or token is needed.

const RIGHT = 'Gary Cahill with the half volley! Chelsea are back in it, but Tottenham still lead two-one.'

for (const width of [390, 1280]) {
  test(`the fix sheet opens from Review, closes with Escape, and keeps the text on a 503 at ${width}`, async ({ page }) => {
    let status = 503
    const sent: { corrected_text: string; reason: string }[] = []
    await page.route('**/review', (r) => r.fulfill({ json: [item] }))
    await page.route(`**/lines/${item.line_id}/fix`, (r) => {
      const body = JSON.parse(r.request().postData() ?? '{}')
      sent.push(body)
      if (status !== 200) return r.fulfill({ status, json: { detail: 'correction not sent' } })
      return r.fulfill({ json: { line_id: item.line_id, corrected_text: body.corrected_text, reason: body.reason, reply_matched: true } })
    })
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#review')

    // 1. it opens from the card, with the line as said and focus in the text box
    const open = page.locator('li.flag').filter({ hasText: item.text }).getByRole('button', { name: /^Fix this line/ })
    await open.click()
    const sheet = page.getByRole('dialog', { name: 'Fix this line' })
    await expect(sheet).toBeVisible()
    await expect(sheet.locator('.said')).toHaveText(item.text)
    const box = sheet.getByLabel('Corrected line')
    await expect(box).toBeFocused()
    await expect(box).toHaveValue(item.text) // it starts from the line as said
    await expect(sheet.getByRole('button', { name: 'Send fix' })).toBeDisabled() // nothing changed yet

    // 2. Escape closes it and sends nothing
    await page.keyboard.press('Escape')
    await expect(sheet).toHaveCount(0)
    expect(sent).toEqual([])

    // 3. it takes the fix text; a 503 keeps it open with that text and says why
    await open.click()
    await box.fill(RIGHT)
    await sheet.getByText('Wrong score').click()
    await sheet.getByRole('button', { name: 'Send fix' }).click()
    await expect(sheet.getByRole('alert')).toHaveText('Fix not saved. Check the connection and send again.')
    await expect(sheet).toBeVisible()
    await expect(box).toHaveValue(RIGHT)
    expect(sent).toEqual([{ corrected_text: RIGHT, reason: 'Wrong score' }])

    // 4. sent again and saved: the sheet closes
    status = 200
    await sheet.getByRole('button', { name: 'Send fix' }).click()
    await expect(sheet).toHaveCount(0)
    expect(sent).toHaveLength(2)
  })
}
