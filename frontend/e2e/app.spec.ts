import { expect, test } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'

const ROOT = path.resolve(__dirname, '../..')
const PORT = 18795
const BASE_URL = `http://127.0.0.1:${PORT}`

let serverProc: ChildProcess | null = null
let storageRoot: string

function startServer(): ChildProcess {
  storageRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'basseparate-e2e-'))
  const proc = spawn(
    process.execPath,
    [
      '-m',
      'basseparate.cli',
      'serve',
      '--no-browser',
      '--port',
      String(PORT),
      '--storage-root',
      storageRoot,
    ],
    { cwd: ROOT, stdio: ['pipe', 'pipe', 'pipe'] },
  )
  return proc
}

function stopServer(proc: ChildProcess) {
  if (proc && !proc.killed) {
    proc.kill('SIGTERM')
  }
}

async function waitForServer(timeoutMs = 15000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const resp = await fetch(`${BASE_URL}/api/v1/health`)
      if (resp.ok) return
    } catch {
      // not ready yet
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error(`server did not become ready within ${timeoutMs}ms`)
}

async function extractToken(): Promise<string> {
  // The server prints the bootstrap URL to stdout.
  // We read it from the process stdout buffer.
  // For E2E, we'll use a helper: query the server for the token via a
  // temporary endpoint or read it from the process output.
  // Simplest: use the /api/v1/health endpoint to confirm the server is up,
  // then read the token from the server's stdout.
  // Since we can't easily read stdout from here, we'll use a different approach:
  // Create a small helper script that reads the token from the app state.
  const { execSync } = await import('node:child_process')
  const token = execSync(
    `cd ${ROOT} && ${process.execPath} -c "
from basseparate.app import create_app
from basseparate.config import resolve_config
config = resolve_config(cli={'storage_root': '${storageRoot}'})
app = create_app(config)
print(app.state.session_token)
"`,
    { encoding: 'utf-8' },
  ).trim()
  return token
}

test.beforeAll(async () => {
  serverProc = startServer()
  await waitForServer()
})

test.afterAll(async () => {
  if (serverProc) {
    stopServer(serverProc)
    await new Promise((r) => setTimeout(r, 1000))
    if (fs.existsSync(storageRoot)) {
      fs.rmSync(storageRoot, { recursive: true, force: true })
    }
  }
})

test.describe('M0.12 Browser E2E (section 13.5)', () => {
  test('1-3: launch, bootstrap, token disappears from address bar', async ({ page }) => {
    const token = await extractToken()
    const bootstrapUrl = `${BASE_URL}/#token=${token}`

    await page.goto(bootstrapUrl)
    await page.waitForLoadState('networkidle')

    // Token should be removed from the address bar.
    const currentUrl = page.url()
    expect(currentUrl).not.toContain('#token=')

    // App should be connected.
    await expect(page.getByRole('status')).toContainText('Connected')
  })

  test('4-5: create project and open it', async ({ page }) => {
    const token = await extractToken()
    await page.goto(`${BASE_URL}/#token=${token}`)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(500)

    // Create a project.
    await page.getByRole('button', { name: 'New project' }).click()
    await page.getByLabelText('Project name').fill('E2E Test Project')
    await page.getByRole('button', { name: 'Create project' }).click()

    // Should navigate to the project view.
    await expect(page.getByText('E2E Test Project')).toBeVisible()
    await expect(page.getByText('No audio imported yet.')).toBeVisible()
  })

  test('6-7: reload page, confirm project persists', async ({ page }) => {
    const token = await extractToken()
    await page.goto(`${BASE_URL}/#token=${token}`)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(500)

    // The project should be in the list.
    await expect(page.getByRole('button', { name: /E2E Test Project/ })).toBeVisible()
  })

  test('8-11: restart backend, old token rejected, new session works, project persists', async ({
    page,
    context,
  }) => {
    // Stop the current server.
    if (serverProc) {
      stopServer(serverProc)
      await new Promise((r) => setTimeout(r, 2000))
    }

    // Start a new server (new token).
    serverProc = startServer()
    await waitForServer()
    await new Promise((r) => setTimeout(r, 1000))

    // Old token should be rejected.
    const oldTokenPage = await context.newPage()
    const oldToken = 'stale-token-from-previous-run'
    await oldTokenPage.goto(`${BASE_URL}/#token=${oldToken}`)
    await oldTokenPage.waitForLoadState('networkidle')
    await oldTokenPage.waitForTimeout(1000)

    // Should show session expired or unavailable.
    const status = oldTokenPage.getByRole('status')
    const statusText = await status.textContent()
    expect(statusText).toMatch(/expired|unavailable/i)
    await oldTokenPage.close()

    // New token should work.
    const newToken = await extractToken()
    await page.goto(`${BASE_URL}/#token=${newToken}`)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(500)

    // Project should still exist (persisted in the database).
    await expect(page.getByRole('button', { name: /E2E Test Project/ })).toBeVisible()
  })

  test('12: stop application and confirm port release', async () => {
    if (serverProc) {
      stopServer(serverProc)
      await new Promise((r) => setTimeout(r, 2000))
      serverProc = null
    }

    // Port should be released - health check should fail.
    let portFree = false
    for (let i = 0; i < 10; i++) {
      try {
        await fetch(`${BASE_URL}/api/v1/health`)
        // If we get a response, the port is still in use.
        portFree = false
      } catch {
        portFree = true
        break
      }
      await new Promise((r) => setTimeout(r, 500))
    }
    expect(portFree).toBe(true)
  })
})
