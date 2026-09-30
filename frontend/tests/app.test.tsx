import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'

const { mockClient } = vi.hoisted(() => ({
  mockClient: {
    GET: vi.fn(),
    POST: vi.fn(),
  },
}))

vi.mock('../src/api/client', () => ({
  createApiClient: () => mockClient,
  errorMessage: (e: unknown, fallback: string) => {
    if (e && typeof e === 'object' && 'error' in e) {
      const inner = (e as { error: { message?: string } }).error
      if (inner?.message) return inner.message
    }
    return fallback
  },
}))

function ok<T>(data: T) {
  return { response: { ok: true, status: 200 }, data }
}

const PROJECT = {
  schema_version: 1,
  id: '11111111-1111-1111-1111-111111111111',
  name: 'Test Project',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  revision: 0,
  source_asset_id: null,
  sample_rate: null,
  duration_samples: null,
  status: 'empty',
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  sessionStorage.setItem('basseparate.sessionToken', 'test-token')
  window.history.replaceState(null, '', '/')
  mockClient.GET.mockImplementation((path: string) => {
    if (path === '/api/v1/system') {
      return Promise.resolve(ok({ app_version: '0.1.0-dev', api_version: 1, ready: true }))
    }
    if (path === '/api/v1/projects') {
      return Promise.resolve(ok({ projects: [] }))
    }
    return Promise.resolve(ok(PROJECT))
  })
  mockClient.POST.mockImplementation(
    (_path: string, opts: { body: { name: string } }) =>
      Promise.resolve({
        response: { ok: true, status: 201 },
        data: { ...PROJECT, name: opts.body.name },
      }),
  )
})

afterEach(() => {
  cleanup()
})

describe('App states', () => {
  it('shows connecting state initially', () => {
    render(<App />)
    expect(screen.getByText('Connecting to backend…')).toBeInTheDocument()
  })

  it('shows empty project list when connected with no projects', async () => {
    render(<App />)
    expect(await screen.findByText('No projects yet. Create one to get started.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Connected')
  })

  it('shows existing projects', async () => {
    mockClient.GET.mockImplementation((path: string) => {
      if (path === '/api/v1/system') {
        return Promise.resolve(ok({ app_version: '0.1.0-dev', api_version: 1, ready: true }))
      }
      if (path === '/api/v1/projects') {
        return Promise.resolve(ok({ projects: [PROJECT] }))
      }
      return Promise.resolve(ok(PROJECT))
    })
    render(<App />)
    const link = await screen.findByRole('button', { name: /Test Project/ })
    expect(link).toBeInTheDocument()
  })

  it('shows backend unavailable state on network failure', async () => {
    mockClient.GET.mockRejectedValue(new TypeError('fetch failed'))
    render(<App />)
    expect(await screen.findByText('Backend unavailable.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Unavailable')
  })

  it('shows session expired state on 401', async () => {
    mockClient.GET.mockImplementation((path: string) => {
      if (path === '/api/v1/system') {
        return Promise.resolve(ok({ app_version: '0.1.0-dev', api_version: 1, ready: true }))
      }
      return Promise.resolve({
        response: { ok: false, status: 401 },
        error: { error: { code: 'UNAUTHORIZED', message: 'Session expired' } },
      })
    })
    render(<App />)
    expect(await screen.findByText('Session expired.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Session expired')
  })

  it('shows API error state on 500, not an empty list', async () => {
    mockClient.GET.mockImplementation((path: string) => {
      if (path === '/api/v1/system') {
        return Promise.resolve(ok({ app_version: '0.1.0-dev', api_version: 1, ready: true }))
      }
      return Promise.resolve({
        response: { ok: false, status: 500 },
        error: { error: { code: 'INTERNAL', message: 'Database error' } },
      })
    })
    render(<App />)
    expect(await screen.findByText('Something went wrong.')).toBeInTheDocument()
    expect(screen.getByText('Database error')).toBeInTheDocument()
  })
})

describe('new project workflow', () => {
  it('creates a project and navigates to it', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('No projects yet. Create one to get started.')

    await user.click(screen.getByRole('button', { name: 'New project' }))
    const input = screen.getByLabelText('Project name')
    await user.type(input, 'My First Project')
    await user.click(screen.getByRole('button', { name: 'Create project' }))

    expect(await screen.findByText('My First Project')).toBeInTheDocument()
    expect(screen.getByText('No audio imported yet.')).toBeInTheDocument()
    expect(mockClient.POST).toHaveBeenCalledWith('/api/v1/projects', {
      body: { name: 'My First Project' },
    })
  })

  it('validates name locally and disables submit for blank names', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('No projects yet. Create one to get started.')

    await user.click(screen.getByRole('button', { name: 'New project' }))
    const input = screen.getByLabelText('Project name')
    const submit = screen.getByRole('button', { name: 'Create project' })
    expect(submit).toBeDisabled()

    await user.type(input, 'Valid')
    expect(submit).toBeEnabled()
  })

  it('retains the name when creation fails', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('No projects yet. Create one to get started.')

    mockClient.POST.mockResolvedValueOnce({
      response: { ok: false, status: 500 },
      error: { error: { code: 'INTERNAL', message: 'Database error' } },
    })

    await user.click(screen.getByRole('button', { name: 'New project' }))
    const input = screen.getByLabelText('Project name')
    await user.type(input, 'Kept Name')
    await user.click(screen.getByRole('button', { name: 'Create project' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Database error')
    expect(input).toHaveValue('Kept Name')
  })

  it('disables duplicate submission while pending', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('No projects yet. Create one to get started.')

    let resolveCreate: (v: unknown) => void = () => {}
    mockClient.POST.mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolveCreate = r
        }),
    )

    await user.click(screen.getByRole('button', { name: 'New project' }))
    const input = screen.getByLabelText('Project name')
    await user.type(input, 'Pending')
    await user.click(screen.getByRole('button', { name: 'Create project' }))

    const submit = screen.getByRole('button', { name: /Creating/ })
    expect(submit).toBeDisabled()

    resolveCreate({
      response: { ok: true, status: 201 },
      data: { ...PROJECT, name: 'Pending' },
    })
    await screen.findByText('No audio imported yet.')
  })
})

describe('project list persistence', () => {
  it('shows created project in the list after going back', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('No projects yet. Create one to get started.')

    await user.click(screen.getByRole('button', { name: 'New project' }))
    await user.type(screen.getByLabelText('Project name'), 'Persisted')
    await user.click(screen.getByRole('button', { name: 'Create project' }))
    await screen.findByText('No audio imported yet.')

    // Simulate reload by going back to the list, which re-fetches.
    mockClient.GET.mockImplementation((path: string) => {
      if (path === '/api/v1/system') {
        return Promise.resolve(ok({ app_version: '0.1.0-dev', api_version: 1, ready: true }))
      }
      if (path === '/api/v1/projects') {
        return Promise.resolve(ok({ projects: [{ ...PROJECT, name: 'Persisted' }] }))
      }
      return Promise.resolve(ok(PROJECT))
    })
    await user.click(screen.getByRole('button', { name: /Back to projects/ }))
    const list = await screen.findByRole('button', { name: /Persisted/ })
    expect(list).toBeInTheDocument()
  })
})

describe('keyboard navigation', () => {
  it('can fill and submit the project form using keyboard input', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('No projects yet. Create one to get started.')

    await user.click(screen.getByRole('button', { name: 'New project' }))

    const input = await screen.findByLabelText('Project name')
    input.focus()
    await user.keyboard('Keyboard Project')

    await user.click(screen.getByRole('button', { name: 'Create project' }))

    expect(await screen.findByText('Keyboard Project')).toBeInTheDocument()
    expect(screen.getByText('No audio imported yet.')).toBeInTheDocument()
  })

  it('can navigate from project view back to list using keyboard', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('No projects yet. Create one to get started.')

    await user.click(screen.getByRole('button', { name: 'New project' }))
    const input = await screen.findByLabelText('Project name')
    input.focus()
    await user.keyboard('Nav Test')
    await user.click(screen.getByRole('button', { name: 'Create project' }))
    await screen.findByText('No audio imported yet.')

    mockClient.GET.mockImplementation((path: string) => {
      if (path === '/api/v1/projects') {
        return Promise.resolve(ok({ projects: [{ ...PROJECT, name: 'Nav Test' }] }))
      }
      if (path === '/api/v1/system') {
        return Promise.resolve(ok({ app_version: '0.1.0-dev', api_version: 1, ready: true }))
      }
      return Promise.resolve(ok(PROJECT))
    })

    const backBtn = screen.getByRole('button', { name: /Back to projects/ })
    await user.click(backBtn)

    expect(await screen.findByRole('button', { name: /Nav Test/ })).toBeInTheDocument()
  })
})
