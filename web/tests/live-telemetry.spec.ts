import { test, expect } from '@playwright/test'

test('real browser UI displays persisted trace IDs from the running API', async ({ page, request }) => {
  test.skip(process.env.CAUSALTRACE_REQUIRE_LIVE !== '1', 'Full isolated Compose lab is required')

  const apiKey = process.env.CAUSALTRACE_API_KEY
  if (!apiKey) throw new Error('Live Playwright requires CAUSALTRACE_API_KEY from the running lab')
  const api = await request.get('http://127.0.0.1:8000/api/traces?limit=10', {headers:{'x-api-key':apiKey}})
  expect(api.ok(), 'live CausalTrace API must respond').toBeTruthy()
  const response = (await api.json()) as { items: { trace_id: string }[] }
  expect(response.items.length, 'the lab must have stored actual traces').toBeGreaterThan(0)

  await page.goto('/')
  await page.getByLabel('Operator API key').fill(apiKey)
  await page.getByRole('button', {name:'Unlock views'}).click()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
  await page.getByRole('button', { name: 'Traces', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Recent distributed traces' })).toBeVisible()
  const expected = response.items[0].trace_id.slice(0, 16)
  await expect(page.getByText(expected, { exact: false })).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: 'Inspect' }).first().click()
  await expect(page.getByRole('heading', { name: /Trace [a-f0-9]{32}/ })).toBeVisible()
})
