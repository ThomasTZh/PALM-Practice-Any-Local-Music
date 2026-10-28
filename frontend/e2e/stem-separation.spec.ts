/**
 * Real local Demucs separation through the browser panel.
 *
 * This test is opt-in because it runs CPU inference and needs the local
 * analysis environment plus the bundled model:
 *
 *   BASSEPARATE_TEST_SEPARATION=1 npm run e2e:separation
 */
import { expect, test } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '../..')
const PORT = 20000 + Math.floor(Math.random() * 10000)
const BASE_URL = `http://127.0.0.1:${PORT}`
const PYTHON = path.join(ROOT, '.venv', 'bin', 'python')

let server: ChildProcess | null = null
let storageRoot = ''
let token = ''

function makeWav(file: string): void {
  const rate = 48_000
  const frames = rate * 8
  const data = Buffer.alloc(frames * 4)
  for (let frame = 0; frame < frames; frame += 1) {
    const t = frame / rate
    const value = Math.sin(2 * Math.PI * 110 * t) * 0.05
    const byte = Math.max(-1, Math.min(1, value)) * 32767
    data.writeInt16LE(byte, frame * 4)
    data.writeInt16LE(byte, frame * 4 + 2)
  }
  const header = Buffer.alloc(44)
  header.write('RIFF', 0)
  header.writeUInt32LE(36 + data.length, 4)
  header.write('WAVE', 8)
  header.write('fmt ', 12)
  header.writeUInt32LE(16, 16)
  header.writeUInt16LE(1, 20)
  header.writeUInt16LE(2, 22)
  header.writeUInt32LE(rate, 24)
  header.writeUInt32LE(rate * 4, 28)
  header.writeUInt16LE(4, 32)
  header.writeUInt16LE(16, 34)
  header.write('data', 36)
  header.writeUInt32LE(data.length, 40)
  fs.writeFileSync(file, Buffer.concat([header, data]))
}

async function waitForHealth(): Promise<void> {
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE_URL}/api/v1/health`)
      if (res.ok) return
    } catch {
      // not ready
    }
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  throw new Error('server did not become ready')
}

test.use({
  launchOptions: {
    executablePath:
      process.env.BASSEPARATE_FIREFOX_PATH ??
      path.join(os.homedir(), '.cache/ms-playwright/firefox-1542/firefox/firefox'),
  },
})

test.skip(
  !process.env.BASSEPARATE_TEST_SEPARATION,
  'set BASSEPARATE_TEST_SEPARATION=1 to run real Demucs acceptance',
)

test.beforeAll(async () => {
  storageRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'basseparate-stems-e2e-'))
  makeWav(path.join(storageRoot, 'tone.wav'))
  server = spawn(
    PYTHON,
    [
      '-u',
      '-m',
      'basseparate.cli',
      'serve',
      '--no-browser',
      '--port',
      String(PORT),
      '--storage-root',
      storageRoot,
    ],
    { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] },
  )
  let output = ''
  const capture = (chunk: Buffer) => {
    output += chunk.toString()
    const match = output.match(/#token=([A-Za-z0-9_-]+)/)
    if (match) token = match[1]
  }
  server.stdout?.on('data', capture)
  server.stderr?.on('data', capture)
  await waitForHealth()
  const deadline = Date.now() + 10_000
  while (!token && Date.now() < deadline) await new Promise((r) => setTimeout(r, 100))
  if (!token) throw new Error(`no token: ${output}`)
})

test.afterAll(async () => {
  if (server && !server.killed) {
    server.kill('SIGTERM')
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  if (storageRoot) fs.rmSync(storageRoot, { recursive: true, force: true })
})

test('separates stems and shows the four-track mixer', async ({ page }) => {
  test.setTimeout(600_000)
  await page.goto(`${BASE_URL}/#token=${token}`)
  await expect(page.getByText('Connected')).toBeVisible()
  await page.getByRole('button', { name: 'New project' }).click()
  await page.getByLabel('Project name').fill('Stem E2E')
  await page.getByRole('button', { name: 'Create project' }).click()
  await page.locator('input[type="file"]').setInputFiles(path.join(storageRoot, 'tone.wav'))
  const projectLink = page.getByRole('button', { name: /Stem E2E/ })
  await expect(projectLink).toContainText('Ready', { timeout: 120_000 })
  await projectLink.click()
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible({
    timeout: 120_000,
  })

  await page.getByRole('button', { name: 'Separate stems' }).click()
  await expect(page.getByText(/1 stem result set/)).toBeVisible({ timeout: 540_000 })
  await expect(page.locator('.track-row')).toHaveCount(4, { timeout: 60_000 })
})
