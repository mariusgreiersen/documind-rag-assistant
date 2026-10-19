// End-to-end smoke test through the real UI (no mocks):
// upload a PDF -> wait until indexed -> semantic search -> open the source viewer
// -> check the PDF page renders with highlighted lines -> delete the document.
//
//   node scripts/e2e-smoke.mjs [baseUrl] [pdfPath]
//
// Needs the backend and frontend running, and Edge (or BROWSER_CHANNEL=chrome).
import { chromium } from 'playwright-core'

const base = process.argv[2] ?? 'http://localhost:5173'
const pdf = process.argv[3] ?? '../data/demo/caching-strategies-guide.pdf'
const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL ?? 'msedge' })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const step = (msg) => console.log(`✓ ${msg}`)

try {
  // Start from a workspace without this file (it may exist as a demo document).
  const docs = (await (await fetch(`${base}/api/v1/documents`)).json()).documents
  for (const d of docs.filter((d) => d.filename === 'caching-strategies-guide.pdf' || d.filename === 'e2e-upload.pdf')) {
    await fetch(`${base}/api/v1/documents/${d.id}`, { method: 'DELETE' })
  }

  await page.goto(base)
  await page.getByRole('button', { name: 'Upload documents' }).click()
  await page.locator('input[type=file]').setInputFiles({ name: 'e2e-upload.pdf', mimeType: 'application/pdf', buffer: (await import('node:fs')).readFileSync(pdf) })
  await page.getByText(/Ready · 4 pages · \d+ chunks indexed/).waitFor({ timeout: 60_000 })
  step('uploaded through the dialog and indexed (status shown: ready)')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Semantic search' }).click()
  await page.getByLabel('Search query').fill('how can a cache avoid a thundering herd when entries expire?')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await page.getByText(/passages ·/).waitFor()
  const first = page.locator('ol li button').first()
  const firstText = await first.innerText()
  if (!firstText.includes('Caching Strategies')) throw new Error(`unexpected top result: ${firstText.slice(0, 120)}`)
  step(`semantic search returned the caching guide first (${firstText.match(/p\. \d+/)?.[0]})`)

  await first.click()
  await page.locator('.pdf-page canvas').waitFor({ timeout: 30_000 })
  await page.locator('.react-pdf__Page__textContent mark').first().waitFor({ timeout: 15_000 })
  const marks = await page.locator('.react-pdf__Page__textContent mark').count()
  const pageLabel = await page.getByText(/^Page \d+ of \d+$/).innerText()
  step(`source viewer rendered the PDF (${pageLabel}) with ${marks} highlighted text lines`)

  await page.getByRole('button', { name: 'Document library' }).click()
  const row = page.locator('tr', { hasText: 'e2e-upload.pdf' })
  await row.getByRole('button', { name: /Actions for/ }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click()
  await row.waitFor({ state: 'detached' })
  const after = (await (await fetch(`${base}/api/v1/documents`)).json()).documents
  if (after.some((d) => d.filename === 'e2e-upload.pdf')) throw new Error('document still listed after delete')
  step('deleted from the library; no longer listed by the API')
  console.log('E2E smoke test passed')
} catch (err) {
  await page.screenshot({ path: 'e2e-failure.png' })
  console.error('E2E smoke test FAILED:', err.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
