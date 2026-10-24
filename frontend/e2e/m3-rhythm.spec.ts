/**
 * M3 rhythm workflow in a real Firefox window.
 *
 * Starts the application with an isolated storage root that symlinks the
 * installed Beat This! checkpoints, imports a deterministic 12 s click
 * track, runs Analyze Rhythm, and checks the ruler, selector, metronome,
 * count-in, and portable save UI. Audible listening is still a human step;
 * this covers the browser/state path around it.
 */
import { expect, test } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '../..')
const PORT = 18820
const BASE_URL = `http://127.0.0.1:${PORT}`
const PYTHON = path.join(ROOT, '.venv', 'bin', 'python')

let server: ChildProcess | null = null
let storageRoot = ''
let token = ''

function makeWav(file: string): void {
  const rate = 48_000
  const seconds = 12
  const frames = rate * seconds
  const data = Buffer.alloc(frames * 4)
  for (let frame = 0; frame < frames; frame += 1) {
    const t = frame / rate
    let sample = Math.sin(2 * Math.PI * 180 * t) * 0.02
    const beat = Math.round(t / 0.5)
    if (beat % 4 === 0 && Math.abs(t - beat * 0.5) < 0.02) sample += 0.7
    else if (Math.abs(t - beat * 0.5) < 0.015) sample += 0.35
    const value = Math.max(-1, Math.min(1, sample)) * 32767
    data.writeInt16LE(value, frame * 4)
    data.writeInt16LE(value, frame * 4 + 2)
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

async function waitForHealth(timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
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

test.beforeAll(async () => {
  storageRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'basseparate-m3-e2e-'))
  fs.mkdirSync(path.join(storageRoot, 'data'), { recursive: true })
  fs.symlinkSync(path.join(ROOT, 'storage/m3.2/data/models'), path.join(storageRoot, 'data/models'))
  makeWav(path.join(storageRoot, 'clicks.wav'))

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
  const matchToken = (chunk: string) => {
    output += chunk
    const match = output.match(/#token=([A-Za-z0-9_-]+)/)
    if (match) token = match[1]
  }
  server.stdout?.on('data', (chunk: Buffer) => matchToken(chunk.toString()))
  server.stderr?.on('data', (chunk: Buffer) => matchToken(chunk.toString()))
  await waitForHealth()
  const deadline = Date.now() + 10_000
  while (!token && Date.now() < deadline) await new Promise((r) => setTimeout(r, 100))
  if (!token) throw new Error(`no session token in server output: ${output}`)
})

test.afterAll(async () => {
  if (server && !server.killed) {
    server.kill('SIGTERM')
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  fs.rmSync(storageRoot, { recursive: true, force: true })
})

test('M3 rhythm workflow (Firefox)', async ({ page }) => {
  test.setTimeout(240_000)
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })

  await page.goto(`${BASE_URL}/#token=${token}`)
  await expect(page.getByText('Connected')).toBeVisible()
  await page.getByRole('button', { name: 'New project' }).click()
  await page.getByLabel('Project name').fill('M3 E2E')
  await page.getByRole('button', { name: 'Create project' }).click()

  await page.locator('input[type="file"]').setInputFiles(path.join(storageRoot, 'clicks.wav'))
  const projectLink = page.getByRole('button', { name: /M3 E2E/ })
  await expect(projectLink).toContainText('Ready', { timeout: 120_000 })
  await projectLink.click()
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible({
    timeout: 120_000,
  })

  await page.getByRole('button', { name: 'Analyze rhythm' }).click()
  await expect(page.locator('.rhythm-version-selector')).toBeVisible({ timeout: 180_000 })
  await expect(page.locator('.rhythm-analysis-status')).toContainText('completed')
  await expect(page.locator('.rhythm-lanes')).toBeVisible()
  await expect(page.locator('.rhythm-lanes-meter')).toContainText('4/4')
  await expect(page.locator('.rhythm-grid-bar')).not.toHaveCount(0)
  await expect(page.getByLabel('Active editable rhythm branch')).not.toHaveValue('')

  const metronome = page.getByRole('checkbox', { name: 'Metronome', exact: true })
  await metronome.click()
  await expect(metronome).toBeChecked({ timeout: 15_000 })

  const projectsAfter = await (
    await page.request.get(`${BASE_URL}/api/v1/projects`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  ).json()
  const readyProject = projectsAfter.projects.find((p: { name: string }) => p.name === 'M3 E2E')
  const scheduleResponse = await page.request.post(
    `${BASE_URL}/api/v1/projects/${readyProject.id}/metronome-schedule`,
    {
      headers: { Authorization: `Bearer ${token}` },
      data: { start_frame: 30_000, end_frame: 60_000 },
    },
  )
  expect(scheduleResponse.ok()).toBeTruthy()
  expect((await scheduleResponse.json()).clicks.length).toBeGreaterThan(0)
  await expect(page.getByRole('button', { name: 'Re-analyze' })).toBeVisible()
  await page.getByLabel('Count-in length').selectOption('one_bar')
  await expect(page.getByLabel('Count-in length')).toHaveValue('one_bar', { timeout: 15_000 })
  await page.getByRole('button', { name: 'Save portable project' }).click()
  await expect(page.getByText(/Saved through revision/)).toBeVisible({ timeout: 60_000 })

  expect(errors).toEqual([])
})
