import { useCallback, useEffect, useRef, useState } from 'react'
import { createApiClient, errorMessage } from './api/client'
import { bootstrapToken, getSessionToken } from './auth'
import type { ConnectionState, ProjectSummary } from './types'

const client = createApiClient()

type View =
  | { kind: 'connecting' }
  | { kind: 'unavailable' }
  | { kind: 'session-expired' }
  | { kind: 'project-list'; projects: ProjectSummary[] }
  | { kind: 'project-open'; project: ProjectSummary }
  | { kind: 'api-error'; message: string }

function toSummary(p: { id: string; name: string; status: string; created_at: string; updated_at: string }): ProjectSummary {
  return {
    id: p.id,
    name: p.name,
    status: p.status === 'ready' ? 'ready' : 'empty',
    created_at: p.created_at,
    updated_at: p.updated_at,
  }
}

function ConnectionIndicator({ state }: { state: ConnectionState }) {
  const label =
    state === 'connected'
      ? 'Connected'
      : state === 'connecting'
        ? 'Connecting…'
        : state === 'session-expired'
          ? 'Session expired'
          : 'Unavailable'
  const color =
    state === 'connected' ? 'var(--ok)' : state === 'connecting' ? 'var(--warn)' : 'var(--error)'
  return (
    <span className="conn-indicator" role="status" aria-live="polite">
      <span className="conn-dot" style={{ background: color }} aria-hidden="true" />
      {label}
    </span>
  )
}

function RuntimePanel({ appVersion }: { appVersion: string | null }) {
  return (
    <aside className="runtime-panel" aria-label="Runtime status">
      <h2>Runtime</h2>
      <dl>
        <dt>App version</dt>
        <dd>{appVersion ?? '—'}</dd>
        <dt>Storage</dt>
        <dd>Local (SQLite)</dd>
        <dt>Modules</dt>
        <dd>None installed</dd>
        <dt>Models</dt>
        <dd>None installed</dd>
      </dl>
    </aside>
  )
}

function NewProjectForm({
  onSubmit,
  pending,
  error,
  initialName,
}: {
  onSubmit: (name: string) => void
  pending: boolean
  error: string | null
  initialName: string
}) {
  const [name, setName] = useState(initialName)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const isValid = name.trim().length > 0 && name.trim().length <= 200

  return (
    <form
      className="new-project-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (isValid && !pending) onSubmit(name)
      }}
    >
      <h2>New project</h2>
      <div className="field">
        <label htmlFor="project-name">Project name</label>
        <input
          id="project-name"
          ref={inputRef}
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={pending}
          maxLength={200}
          aria-invalid={error !== null}
          aria-describedby={error ? 'name-error' : undefined}
        />
        {!isValid && name.length > 0 && (
          <p className="field-hint" id="name-error">
            Name must be 1–200 characters.
          </p>
        )}
        {error && (
          <p className="field-error" id="name-error" role="alert">
            {error}
          </p>
        )}
      </div>
      <button type="submit" disabled={!isValid || pending}>
        {pending ? 'Creating…' : 'Create project'}
      </button>
    </form>
  )
}

function ProjectListItem({
  project,
  onOpen,
}: {
  project: ProjectSummary
  onOpen: (id: string) => void
}) {
  return (
    <li className="project-item">
      <button type="button" onClick={() => onOpen(project.id)} className="project-link">
        <span className="project-name">{project.name}</span>
        <span className="project-status">{project.status === 'empty' ? 'Empty' : 'Ready'}</span>
      </button>
    </li>
  )
}

export default function App() {
  const [view, setView] = useState<View>({ kind: 'connecting' })
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [retainedName, setRetainedName] = useState('')
  const [appVersion, setAppVersion] = useState<string | null>(null)

  const connectionState: ConnectionState =
    view.kind === 'connecting'
      ? 'connecting'
      : view.kind === 'unavailable'
        ? 'unavailable'
        : view.kind === 'session-expired'
          ? 'session-expired'
          : 'connected'

  const loadProjects = useCallback(async () => {
    setView({ kind: 'connecting' })
    setShowCreateForm(false)
    const token = getSessionToken()
    if (!token) {
      setView({ kind: 'session-expired' })
      return
    }
    try {
      const [sysRes, listRes] = await Promise.all([
        client.GET('/api/v1/system'),
        client.GET('/api/v1/projects'),
      ])
      if (sysRes.response.ok && sysRes.data) {
        setAppVersion(sysRes.data.app_version)
      }
      if (listRes.response.status === 401) {
        setView({ kind: 'session-expired' })
        return
      }
      if (!listRes.response.ok || !listRes.data) {
        setView({
          kind: 'api-error',
          message: errorMessage(listRes.error, `Request failed (${listRes.response.status})`),
        })
        return
      }
      const projects = listRes.data.projects.map(toSummary)
      setView({ kind: 'project-list', projects })
    } catch {
      setView({ kind: 'unavailable' })
    }
  }, [])

  useEffect(() => {
    bootstrapToken()
    loadProjects()
  }, [loadProjects])

  const openProject = useCallback(
    async (id: string) => {
      try {
        const res = await client.GET('/api/v1/projects/{project_id}', {
          params: { path: { project_id: id } },
        })
        if (res.response.status === 401) {
          setView({ kind: 'session-expired' })
          return
        }
        if (!res.response.ok || !res.data) {
          setView({ kind: 'api-error', message: `Could not open project (${res.response.status})` })
          return
        }
        setView({ kind: 'project-open', project: toSummary(res.data) })
      } catch {
        setView({ kind: 'unavailable' })
      }
    },
    [],
  )

  const createProject = useCallback(
    async (name: string) => {
      setCreating(true)
      setCreateError(null)
      try {
        const res = await client.POST('/api/v1/projects', { body: { name } })
        if (res.response.status === 401) {
          setView({ kind: 'session-expired' })
          setShowCreateForm(false)
          setCreating(false)
          return
        }
        if (!res.response.ok || !res.data) {
          setCreateError(errorMessage(res.error, `Creation failed (${res.response.status})`))
          setRetainedName(name)
          setCreating(false)
          return
        }
        const project = toSummary(res.data)
        setCreating(false)
        setRetainedName('')
        setShowCreateForm(false)
        setView({ kind: 'project-open', project })
      } catch {
        setCreating(false)
        setCreateError('Network error. Is the backend running?')
        setRetainedName(name)
      }
    },
    [],
  )

  return (
    <div className="shell">
      <header className="app-header">
        <h1>basseparate</h1>
        <ConnectionIndicator state={connectionState} />
      </header>

      <div className="app-body">
        <main className="app-main" aria-live="polite">
          {view.kind === 'connecting' && <p className="state-msg">Connecting to backend…</p>}

          {view.kind === 'unavailable' && (
            <div className="state-box">
              <p>Backend unavailable.</p>
              <p className="muted">Start the service and reload the page.</p>
              <button type="button" onClick={loadProjects}>
                Retry
              </button>
            </div>
          )}

          {view.kind === 'session-expired' && (
            <div className="state-box">
              <p>Session expired.</p>
              <p className="muted">
                Reopen the application from the launcher to get a fresh session token.
              </p>
            </div>
          )}

          {view.kind === 'api-error' && (
            <div className="state-box">
              <p>Something went wrong.</p>
              <p className="muted">{view.message}</p>
              <button type="button" onClick={loadProjects}>
                Try again
              </button>
            </div>
          )}

          {view.kind === 'project-list' && (
            <>
              <section aria-label="Projects">
                <div className="list-header">
                  <h2>Projects</h2>
                  <button
                    type="button"
                    onClick={() => {
                      setCreateError(null)
                      setShowCreateForm(true)
                    }}
                  >
                    New project
                  </button>
                </div>
                {view.projects.length === 0 ? (
                  <p className="empty-state">No projects yet. Create one to get started.</p>
                ) : (
                  <ul className="project-list">
                    {view.projects.map((p) => (
                      <ProjectListItem key={p.id} project={p} onOpen={openProject} />
                    ))}
                  </ul>
                )}
              </section>

              {showCreateForm && (
                <NewProjectForm
                  onSubmit={createProject}
                  pending={creating}
                  error={createError}
                  initialName={retainedName}
                />
              )}
            </>
          )}

          {view.kind === 'project-open' && (
            <section className="project-view" aria-label={`Project: ${view.project.name}`}>
              <button type="button" onClick={loadProjects} className="back-link">
                ← Back to projects
              </button>
              <h2>{view.project.name}</h2>
              <p className="empty-state">No audio imported yet.</p>
              <dl className="project-meta">
                <dt>Status</dt>
                <dd>{view.project.status === 'empty' ? 'Empty' : 'Ready'}</dd>
                <dt>Created</dt>
                <dd>{new Date(view.project.created_at).toLocaleString()}</dd>
                <dt>Updated</dt>
                <dd>{new Date(view.project.updated_at).toLocaleString()}</dd>
              </dl>
            </section>
          )}
        </main>

        <RuntimePanel appVersion={appVersion} />
      </div>
    </div>
  )
}
