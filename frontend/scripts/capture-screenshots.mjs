// Captures README screenshots from the running app with an installed Chromium-based browser.
//
//   node scripts/capture-screenshots.mjs [baseUrl] [outDir]
//
// Requires the backend (with demo documents loaded) and the frontend dev server to be
// running. Uses Microsoft Edge by default; set BROWSER_CHANNEL=chrome to use Chrome.
// Every screenshot shows real application output: if no LLM key is configured, the
// chat screenshots show retrieval-only mode, and the answer screenshot is skipped.
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright-core'

const base = process.argv[2] ?? 'http://localhost:5173'
const out = process.argv[3] ?? '../docs/images'
const channel = process.env.BROWSER_CHANNEL ?? 'msedge'
await mkdir(out, { recursive: true })

const browser = await chromium.launch({ channel })

async function page(theme = 'light', viewport = { width: 1440, height: 900 }) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 2, colorScheme: theme })
  await context.addInitScript((t) => {
    localStorage.setItem('documind.preferences.v1', JSON.stringify({ theme: t, topK: 5, showDiagnostics: true }))
    localStorage.removeItem('documind.conversations.v1')
  }, theme)
  const p = await context.newPage()
  await p.goto(base)
  await p.getByLabel('Question', { exact: true }).waitFor()
  await p.waitForTimeout(600)
  return p
}

async function ask(p, question) {
  await p.getByLabel('Question', { exact: true }).fill(question)
  await p.getByLabel('Send question').click()
  await p.getByRole('status').filter({ hasText: 'Searching your documents' }).waitFor({ state: 'detached', timeout: 120_000 })
  await p.waitForTimeout(500)
}

const shot = async (p, name) => {
  await p.screenshot({ path: `${out}/${name}.png` })
  console.log(`saved ${name}.png`)
}

const config = await (await fetch(`${base}/api/v1/config`)).json()

// 1. Workspace with suggested questions
let p = await page()
await shot(p, 'workspace')

// 2. Chat: generated answer when an LLM is configured, otherwise retrieval-only mode
await ask(p, 'When is a log entry considered committed in Raft?')
if (config.llm_configured) {
  await p.waitForTimeout(2500) // first citation opens in the source viewer automatically
  await shot(p, 'chat-answer-citations')
} else {
  await p.getByRole('button', { name: /^1\. Raft Consensus/ }).first().click().catch(() => {})
  await p.waitForTimeout(2500)
  await shot(p, 'chat-retrieval-only')
}

// 3. Diagnostics for the same question
await p.getByRole('button', { name: 'Diagnostics' }).last().click()
await p.waitForTimeout(600)
await shot(p, 'retrieval-diagnostics')

// 4. Insufficient evidence (relevance gate or model decline)
await ask(p, 'Who won the 2022 FIFA World Cup?')
await shot(p, 'insufficient-evidence')

// 5. Semantic search with the source viewer open on a result
p = await page()
await p.getByRole('button', { name: 'Semantic search' }).click()
await p.getByLabel('Search query').fill('how do leaders stop followers from starting new elections?')
await p.getByRole('button', { name: 'Search', exact: true }).click()
await p.getByText(/passages ·/).waitFor()
await p.locator('ol li button').first().click()
await p.waitForTimeout(2500)
await shot(p, 'semantic-search-source-viewer')

// 6. Document library and upload dialog
await p.getByRole('button', { name: 'Document library' }).click()
await p.getByRole('button', { name: 'Hide source panel' }).click()
await p.waitForTimeout(500)
await shot(p, 'document-library')
await p.getByRole('button', { name: 'Upload documents' }).click()
await p.waitForTimeout(400)
await shot(p, 'upload-dialog')

// 7. Dark mode
p = await page('dark')
await ask(p, 'Is optimistic concurrency control always faster than locking?')
await p.waitForTimeout(2000)
await shot(p, 'dark-mode')

// 8. Mobile
p = await page('light', { width: 390, height: 844 })
await shot(p, 'mobile')

await browser.close()
