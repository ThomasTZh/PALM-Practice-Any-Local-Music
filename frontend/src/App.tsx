import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { createApiClient, errorMessage } from './api/client'
import {
  createJob,
  ensurePlaybackTarget,
  fetchAssetBytes,
  getSourceInfo,
  latestCompletedImportId,
  setMonitoringChannels,
  waitForJob,
  type SourceInfo,
} from './api/playback'
import {
  listProjectImports,
  selectStream,
  uploadFile,
  type AudioStreamSummary,
  type IncompleteImport,
  type UploadState,
} from './api/uploader'
import { bootstrapToken, getSessionToken } from './auth'
import { PlaybackEngine, type AudioContextLike, type EngineState } from './playback/engine'
import { formatTime } from './playback/pcm'
import { WaveformEditor } from './waveform/WaveformEditor'
import type { ConnectionState, ProjectSummary } from './types'

const client = createApiClient()

type View =
  | { kind: 'connecting' }
  | { kind: 'unavailable' }
  | { kind: 'session-expired' }
  | { kind: 'project-list'; projects: ProjectSummary[] }
  | { kind: 'project-open'; project: ProjectSummary }
  | { kind: 'api-error'; message: string }

function toSummary(p: {
  id: string
  name: string
  status: string
  created_at: string
  updated_at: string
  canonical_asset_id?: string | null
}): ProjectSummary {
  return {
    id: p.id,
    name: p.name,
    status: p.status === 'ready' ? 'ready' : 'empty',
    created_at: p.created_at,
    updated_at: p.updated_at,
    canonical_asset_id: p.canonical_asset_id ?? null,
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

function ImportPanel({ projectId, onImported }: { projectId: string; onImported: () => void }) {
  const [uploadState, setUploadState] = useState<UploadState>({ kind: 'idle' })
  const [incomplete, setIncomplete] = useState<IncompleteImport[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [multiFilePrompt, setMultiFilePrompt] = useState<File[] | null>(null)
  const [streamChoice, setStreamChoice] = useState<{
    importId: string
    streams: AudioStreamSummary[]
  } | null>(null)
  const [selecting, setSelecting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const loadIncomplete = useCallback(async () => {
    try {
      const imports = await listProjectImports(projectId)
      setIncomplete(imports)
    } catch {
      setIncomplete([])
    }
  }, [projectId])

  useEffect(() => {
    loadIncomplete()
  }, [loadIncomplete])

  const startUpload = useCallback(
    async (file: File) => {
      const controller = new AbortController()
      abortRef.current = controller
      setUploadState({
        kind: 'uploading',
        progress: { bytesUploaded: 0, totalBytes: file.size, chunkIndex: 0, totalChunks: 1 },
      })
      try {
        const result = await uploadFile({
          projectId,
          file,
          signal: controller.signal,
          onProgress: setUploadState,
        })
        if (result.selectedStreamIndex === null && result.audioStreams.length > 1) {
          setStreamChoice({ importId: result.importId, streams: result.audioStreams })
        } else {
          onImported()
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          setUploadState({ kind: 'cancelled' })
        } else {
          setUploadState({
            kind: 'error',
            message: err instanceof Error ? err.message : String(err),
          })
        }
      }
    },
    [projectId, onImported],
  )

  const handleFiles = useCallback(
    (files: FileList | File[]) => {
      const arr = Array.from(files)
      if (arr.length === 0) return
      if (arr.length > 1) {
        setMultiFilePrompt(arr)
        return
      }
      startUpload(arr[0])
    },
    [startUpload],
  )

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      if (e.dataTransfer.files.length > 0) {
        handleFiles(e.dataTransfer.files)
      }
    },
    [handleFiles],
  )

  const handleCancel = useCallback(async () => {
    abortRef.current?.abort()
    setUploadState({ kind: 'cancelled' })
  }, [])

  const handleSelectStream = useCallback(
    async (streamIndex: number) => {
      if (!streamChoice) return
      setSelecting(true)
      try {
        await selectStream(streamChoice.importId, streamIndex)
        setStreamChoice(null)
        onImported()
      } catch (err) {
        setStreamChoice(null)
        setUploadState({
          kind: 'error',
          message: err instanceof Error ? err.message : String(err),
        })
      } finally {
        setSelecting(false)
      }
    },
    [streamChoice, onImported],
  )

  const progress =
    uploadState.kind === 'uploading'
      ? Math.round((uploadState.progress.bytesUploaded / uploadState.progress.totalBytes) * 100)
      : 0

  return (
    <div className="import-panel" aria-label="Import audio">
      {incomplete.length > 0 && uploadState.kind === 'idle' && (
        <div className="import-recovery" role="alert">
          <p>
            Transfer interrupted. {incomplete.length} incomplete import
            {incomplete.length > 1 ? 's' : ''} found.
          </p>
          <ul>
            {incomplete.map((i) => (
              <li key={i.id}>
                {i.filename}: {i.receivedByteCount} / {i.declaredByteCount} bytes
              </li>
            ))}
          </ul>
          <p className="muted">Select the same file to resume, or start a new import.</p>
        </div>
      )}

      {multiFilePrompt && (
        <div className="import-multi-prompt" role="dialog" aria-label="Multiple files selected">
          <p>Multiple files selected. Choose one to import:</p>
          <ul>
            {multiFilePrompt.map((f, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => {
                    setMultiFilePrompt(null)
                    startUpload(f)
                  }}
                >
                  {f.name} ({(f.size / 1024 / 1024).toFixed(1)} MiB)
                </button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={() => setMultiFilePrompt(null)}>
            Cancel
          </button>
        </div>
      )}

      {streamChoice && (
        <div className="import-stream-dialog" role="dialog" aria-label="Choose audio stream">
          <p>
            This file contains {streamChoice.streams.length} audio streams. Choose the one to
            import:
          </p>
          <ul>
            {streamChoice.streams.map((s) => (
              <li key={s.index}>
                <button
                  type="button"
                  disabled={selecting}
                  onClick={() => handleSelectStream(s.index)}
                  className={s.isDefault ? 'stream-default' : undefined}
                >
                  Stream {s.index}: {s.title ?? s.language ?? s.codec}
                  {s.isDefault ? ' (default)' : ''}
                  {' — '}
                  {s.channelLayout ?? `${s.channelCount} ch`}, {s.sampleRate} Hz
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {uploadState.kind === 'idle' && !multiFilePrompt && !streamChoice && (
        <div
          className={`import-dropzone ${dragOver ? 'drag-over' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click()
          }}
          onClick={() => fileInputRef.current?.click()}
          aria-label="Drop an audio file here or click to browse"
        >
          <p>Drop an audio or video file here</p>
          <p className="muted">or click to browse</p>
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*,video/*"
            style={{ display: 'none' }}
            onChange={(e) => {
              if (e.target.files) handleFiles(e.target.files)
              e.target.value = ''
            }}
          />
        </div>
      )}

      {(uploadState.kind === 'uploading' || uploadState.kind === 'completing') && (
        <div className="import-progress" role="status" aria-live="polite">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
          <p>
            {uploadState.kind === 'completing'
              ? 'Finalizing…'
              : `${progress}% (${(uploadState.progress.bytesUploaded / 1024 / 1024).toFixed(1)} / ${(uploadState.progress.totalBytes / 1024 / 1024).toFixed(1)} MiB)`}
          </p>
          <button type="button" onClick={handleCancel}>
            Cancel
          </button>
        </div>
      )}

      {uploadState.kind === 'error' && (
        <div className="import-error" role="alert">
          <p>Import failed: {uploadState.message}</p>
          <button type="button" onClick={() => setUploadState({ kind: 'idle' })}>
            Try again
          </button>
        </div>
      )}

      {uploadState.kind === 'cancelled' && (
        <div className="import-cancelled">
          <p>Import cancelled.</p>
          <button type="button" onClick={() => setUploadState({ kind: 'idle' })}>
            Dismiss
          </button>
        </div>
      )}
    </div>
  )
}

function defaultCreateAudioContext(): AudioContextLike {
  return new AudioContext() as unknown as AudioContextLike
}

const PlaybackPanel = memo(function PlaybackPanel({
  projectId,
  createAudioContext,
  onPositionChange,
}: {
  projectId: string
  createAudioContext?: () => AudioContextLike
  /** Reports the playhead position (project frames) so sibling views, such
   * as the waveform editor, can draw a playhead (M1.10). */
  onPositionChange?: (frame: number) => void
}) {
  const [info, setInfo] = useState<SourceInfo | null>(null)
  const [infoError, setInfoError] = useState<string | null>(null)
  const [importId, setImportId] = useState<string | null>(null)

  const [leftCh, setLeftCh] = useState(0)
  const [rightCh, setRightCh] = useState(1)
  const [mixState, setMixState] = useState<'idle' | 'working' | 'error'>('idle')
  const [mixError, setMixError] = useState<string | null>(null)

  const [engineState, setEngineState] = useState<EngineState>('idle')
  const [position, setPosition] = useState(0)
  const [preparing, setPreparing] = useState(false)
  const [playError, setPlayError] = useState<string | null>(null)
  const engineRef = useRef<PlaybackEngine | null>(null)

  const loadInfo = useCallback(async () => {
    try {
      const source = await getSourceInfo(projectId)
      setInfo(source)
      setInfoError(null)
      setImportId(await latestCompletedImportId(projectId))
      if (source.monitoring) {
        setLeftCh(source.monitoring.leftChannel)
        setRightCh(source.monitoring.rightChannel)
      }
    } catch (err) {
      setInfoError(err instanceof Error ? err.message : String(err))
    }
  }, [projectId])

  useEffect(() => {
    loadInfo()
  }, [loadInfo])

  useEffect(() => {
    return () => {
      void engineRef.current?.dispose()
      engineRef.current = null
    }
  }, [])

  const isStandard51 = info !== null && info.channelCount === 6 && info.channelLayout === '5.1'

  const handleCreateMix = useCallback(async () => {
    if (!info) return
    setMixState('working')
    setMixError(null)
    try {
      if (!isStandard51) {
        await setMonitoringChannels(projectId, leftCh, rightCh)
      }
      if (!importId) throw new Error('No completed import found for this project')
      const job = await createJob(projectId, importId, 'monitoring_downmix')
      await waitForJob(job.id)
      await loadInfo()
      setMixState('idle')
    } catch (err) {
      setMixState('error')
      setMixError(err instanceof Error ? err.message : String(err))
    }
  }, [importId, info, isStandard51, leftCh, loadInfo, projectId, rightCh])

  const reportPosition = useCallback(
    (frame: number) => {
      setPosition(frame)
      onPositionChange?.(frame)
    },
    [onPositionChange],
  )

  const handlePlayPause = useCallback(async () => {
    const existing = engineRef.current
    if (existing && existing.currentState === 'playing') {
      await existing.pause()
      return
    }
    if (existing && existing.currentState === 'paused') {
      await existing.resume()
      return
    }
    if (!info) return
    setPlayError(null)
    setPreparing(true)
    try {
      const context = (createAudioContext ?? defaultCreateAudioContext)()
      await context.resume()
      const target = await ensurePlaybackTarget(projectId, importId, context.sampleRate)
      const engine = new PlaybackEngine({
        target: {
          assetId: target.assetId,
          sampleRate: target.sampleRate,
          channelCount: target.channelCount,
          frameCount: target.frameCount,
          byteCount: target.byteCount,
          durationSeconds: target.durationSeconds,
        },
        projectRate: info.sampleRate,
        projectDurationFrames: info.durationFrames,
        fetchChunk: (start, end) =>
          fetchAssetBytes(target.assetId, start, end).then((r) => r.bytes),
        context,
        onState: (s) => {
          setEngineState(s)
          if (s === 'playing' || s === 'stopped') setPreparing(false)
          if (s === 'error') {
            setPreparing(false)
            setPlayError(engine.currentError ?? 'Playback failed')
          }
        },
        onPosition: reportPosition,
      })
      engineRef.current = engine
      await engine.start()
    } catch (err) {
      setPreparing(false)
      setPlayError(err instanceof Error ? err.message : String(err))
    }
  }, [createAudioContext, importId, info, projectId, reportPosition])

  const handleStop = useCallback(() => {
    engineRef.current?.stop()
    reportPosition(0)
  }, [reportPosition])

  if (infoError) {
    return (
      <div className="playback-error" role="alert">
        <p>Could not load source information: {infoError}</p>
        <button type="button" onClick={loadInfo}>
          Retry
        </button>
      </div>
    )
  }
  if (!info) {
    return (
      <p className="muted" role="status">
        Loading source…
      </p>
    )
  }

  return (
    <div className="playback-panel">
      <section className="source-info" aria-label="Source information">
        <h3>Source</h3>
        <dl>
          <dt>Sample rate</dt>
          <dd>{info.sampleRate} Hz</dd>
          <dt>Duration</dt>
          <dd>{formatTime(info.durationFrames, info.sampleRate)}</dd>
          <dt>Channels</dt>
          <dd>
            {info.channelCount}
            {info.channelLayout ? ` (${info.channelLayout})` : ''}
          </dd>
        </dl>
        <ul className="channel-labels" aria-label="Channel labels">
          {info.channelLabels.map((label, i) => (
            <li key={i}>{label}</li>
          ))}
        </ul>
      </section>

      {info.channelCount > 2 && (
        <section className="monitoring" aria-label="Monitoring mix">
          <h3>Monitoring</h3>
          {info.monitoring ? (
            <p>
              {info.monitoring.mode === 'standard_5_1'
                ? 'Standard 5.1 → stereo downmix'
                : `Manual: L = ${info.channelLabels[info.monitoring.leftChannel] ?? info.monitoring.leftChannel}, R = ${info.channelLabels[info.monitoring.rightChannel] ?? info.monitoring.rightChannel}`}
            </p>
          ) : (
            <>
              {isStandard51 ? (
                <p className="muted">A standard 5.1 → stereo downmix will be created.</p>
              ) : (
                <div className="monitoring-select">
                  <label>
                    Left
                    <select
                      value={leftCh}
                      onChange={(e) => setLeftCh(Number(e.target.value))}
                      disabled={mixState === 'working'}
                    >
                      {info.channelLabels.map((label, i) => (
                        <option key={i} value={i}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Right
                    <select
                      value={rightCh}
                      onChange={(e) => setRightCh(Number(e.target.value))}
                      disabled={mixState === 'working'}
                    >
                      {info.channelLabels.map((label, i) => (
                        <option key={i} value={i}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              )}
              <button type="button" onClick={handleCreateMix} disabled={mixState === 'working'}>
                {mixState === 'working' ? 'Creating monitoring mix…' : 'Create monitoring mix'}
              </button>
            </>
          )}
          {mixState === 'error' && mixError && (
            <p className="field-error" role="alert">
              {mixError}
            </p>
          )}
        </section>
      )}

      <section className="transport" aria-label="Playback transport">
        <div className="transport-buttons">
          <button
            type="button"
            onClick={handlePlayPause}
            disabled={preparing}
            aria-label={engineState === 'playing' ? 'Pause' : 'Play'}
          >
            {engineState === 'playing' ? 'Pause' : 'Play'}
          </button>
          <button
            type="button"
            onClick={handleStop}
            disabled={engineState === 'idle' || engineState === 'stopped'}
          >
            Stop
          </button>
        </div>
        <span className="time-readout">
          {formatTime(position, info.sampleRate)} /{' '}
          {formatTime(info.durationFrames, info.sampleRate)}
        </span>
        {preparing && (
          <p className="muted" role="status">
            Preparing playback…
          </p>
        )}
        {playError && (
          <p className="field-error" role="alert">
            {playError}
          </p>
        )}
      </section>
    </div>
  )
})

/**
 * Ready-project view (M1.10): transport panel + waveform editor + meta.
 * Owns the playhead frame so position updates re-render only this subtree
 * (and the editor's playhead layer), not the whole app.
 */
function ProjectView({ project }: { project: ProjectSummary }) {
  const [playheadFrame, setPlayheadFrame] = useState(0)
  return (
    <>
      <PlaybackPanel projectId={project.id} onPositionChange={setPlayheadFrame} />
      <WaveformEditor
        projectId={project.id}
        sourceAssetId={project.canonical_asset_id ?? null}
        playheadFrame={playheadFrame}
      />
      <dl className="project-meta">
        <dt>Status</dt>
        <dd>Ready</dd>
        <dt>Created</dt>
        <dd>{new Date(project.created_at).toLocaleString()}</dd>
        <dt>Updated</dt>
        <dd>{new Date(project.updated_at).toLocaleString()}</dd>
      </dl>
    </>
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

  const openProject = useCallback(async (id: string) => {
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
  }, [])

  const createProject = useCallback(async (name: string) => {
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
  }, [])

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
              {view.project.status === 'empty' ? (
                <ImportPanel projectId={view.project.id} onImported={loadProjects} />
              ) : (
                <ProjectView project={view.project} />
              )}
            </section>
          )}
        </main>

        <RuntimePanel appVersion={appVersion} />
      </div>
    </div>
  )
}
