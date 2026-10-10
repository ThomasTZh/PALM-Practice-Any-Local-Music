import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import {
  PcmTransport,
  type TransportContextLike,
  type TransportDiagnostics,
  type TransportState,
} from './playback/transport'
import { formatTime } from './playback/pcm'
import { WaveformEditor, type PlayheadSource } from './waveform/WaveformEditor'
import type { View as EditorView } from './waveform/viewport'
import { useProjectCommands } from './projects/useProjectCommands'
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

function defaultCreateAudioContext(): TransportContextLike {
  return new AudioContext() as unknown as TransportContextLike
}

const PlaybackPanel = memo(function PlaybackPanel({
  projectId,
  createAudioContext,
  registerSeek,
  registerPlayhead,
  initialVolume,
  onVolumeChange,
  onPositionReport,
  parkPosition,
}: {
  projectId: string
  createAudioContext?: () => TransportContextLike
  /** Registers a seek function the waveform editor can use for click-to-seek
   * and "Seek to selection start" (M1.11 §13.4); null on unmount. */
  registerSeek?: (seek: ((frame: number) => void) | null) => void
  /** Registers the audible playhead source the waveform editor reads at
   * display rate (M1.14 §16.5); null on unmount. */
  registerPlayhead?: (source: PlayheadSource | null) => void
  /**
   * Restored monitoring volume in percent, 0–200 (M1.15 §17.6). Applied
   * once when it first arrives; absent → the default 100 %.
   */
  initialVolume?: number
  /** Autosave the monitoring volume (percent) on explicit change. */
  onVolumeChange?: (percent: number) => void
  /**
   * Report the playhead position for autosave (M1.15 §17.5.3): the caller
   * applies the pause-immediate / 5 s-while-playing cadence.
   */
  onPositionReport?: (frame: number, playing: boolean) => void
  /**
   * Last saved playhead position (M1.15 §17.6.4): park the transport here
   * (staying paused) once it exists; absent → stay at zero.
   */
  parkPosition?: number
}) {
  const [info, setInfo] = useState<SourceInfo | null>(null)
  const [infoError, setInfoError] = useState<string | null>(null)
  const [importId, setImportId] = useState<string | null>(null)

  const [leftCh, setLeftCh] = useState(0)
  const [rightCh, setRightCh] = useState(1)
  const [mixState, setMixState] = useState<'idle' | 'working' | 'error'>('idle')
  const [mixError, setMixError] = useState<string | null>(null)

  const [transportState, setTransportState] = useState<TransportState>('unloaded')
  const [position, setPosition] = useState(0)
  const [playError, setPlayError] = useState<string | null>(null)
  const [volume, setVolume] = useState(100)
  // M1.13: browser suspension and underrun diagnostics. Context loss is
  // read directly from the transport in the recovery branch.
  const [suspended, setSuspended] = useState(false)
  const [diagnostics, setDiagnostics] = useState<TransportDiagnostics>({
    underruns: 0,
    lastUnderrunAt: null,
    droppedChunks: 0,
  })
  const transportRef = useRef<PcmTransport | null>(null)
  const assetIdRef = useRef<string | null>(null)
  const pendingContextRef = useRef<TransportContextLike | null>(null)
  const volumeRef = useRef(100)
  const sourceLoadedRef = useRef(false)
  const volumeSeededRef = useRef(false)
  const parkedRef = useRef(false)
  // The transport callbacks are created once; read the latest prop through
  // a ref so the closure never goes stale.
  const onPositionReportRef = useRef(onPositionReport)
  onPositionReportRef.current = onPositionReport

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

  const reportPosition = useCallback((frame: number) => {
    setPosition(frame)
    // The transport reports on pause too (preserved position); the playing
    // flag lets the caller pick the autosave cadence (M1.15 §17.5.3).
    const state = transportRef.current?.currentState
    const playing = state === 'playing' || state === 'seeking' || state === 'buffering'
    onPositionReportRef.current?.(frame, playing)
  }, [])

  // New project: drop any previous transport and source binding.
  useEffect(() => {
    transportRef.current?.dispose()
    transportRef.current = null
    sourceLoadedRef.current = false
    assetIdRef.current = null
    pendingContextRef.current = null
    setTransportState('unloaded')
    setPosition(0)
    setPlayError(null)
    setSuspended(false)
    setDiagnostics({ underruns: 0, lastUnderrunAt: null, droppedChunks: 0 })
    // The restored volume of the previous project no longer applies.
    volumeSeededRef.current = false
    volumeRef.current = 100
    setVolume(100)
    parkedRef.current = false
  }, [projectId])

  useEffect(() => {
    return () => {
      transportRef.current?.dispose()
      transportRef.current = null
    }
  }, [])

  // Expose the transport seek to the waveform editor (M1.11). Before the
  // transport exists (source still loading) the playhead parks locally.
  const seekFn = useCallback(
    (frame: number) => {
      const transport = transportRef.current
      if (transport) {
        transport.seek(frame)
        return
      }
      const duration = info?.durationFrames ?? 0
      reportPosition(Math.max(0, Math.min(Math.floor(frame), duration)))
    },
    [info, reportPosition],
  )

  useEffect(() => {
    registerSeek?.(seekFn)
    return () => registerSeek?.(null)
  }, [registerSeek, seekFn])

  // Expose the audible playhead to the waveform editor (M1.14 §16.5):
  // stable functions that read the transport on demand (display-only).
  const playheadSource = useMemo<PlayheadSource>(
    () => ({
      getPosition: () => transportRef.current?.getAudiblePosition() ?? 0,
      isPlaying: () => {
        const state = transportRef.current?.currentState
        return state === 'playing' || state === 'seeking'
      },
    }),
    [],
  )

  useEffect(() => {
    registerPlayhead?.(playheadSource)
    return () => registerPlayhead?.(null)
  }, [registerPlayhead, playheadSource])

  // Create the transport once the source info is known (M1.12). The
  // playback representation is resolved on first play, when the
  // AudioContext sample rate is known.
  useEffect(() => {
    if (!info || transportRef.current) return
    const transport = new PcmTransport({
      contextFactory: () => {
        const pending = pendingContextRef.current
        pendingContextRef.current = null
        if (pending && pending.state !== 'closed') return pending
        return (createAudioContext ?? defaultCreateAudioContext)()
      },
      fetchChunk: (assetId, start, end, signal) =>
        fetchAssetBytes(assetId, start, end, signal).then((r) => r.bytes),
      onState: (s) => {
        setTransportState(s)
        // Diagnostics surface on state changes (an underrun moves the
        // state to `buffering`).
        setDiagnostics(transport.diagnostics)
        if (s === 'error') setPlayError(transport.currentError ?? 'Playback failed')
      },
      onPosition: reportPosition,
      onSuspend: setSuspended,
    })
    transport.setOutputGain(volumeRef.current / 100)
    transportRef.current = transport
  }, [createAudioContext, info, reportPosition])

  // Apply the restored monitoring volume once when it arrives (M1.15
  // §17.6); the default 100 % stands when it never does. Declared after
  // the transport effect so a same-commit arrival still finds it.
  useEffect(() => {
    if (initialVolume === undefined || volumeSeededRef.current) return
    volumeSeededRef.current = true
    const clamped = Math.max(0, Math.min(200, Math.round(initialVolume)))
    volumeRef.current = clamped
    setVolume(clamped)
    transportRef.current?.setOutputGain(clamped / 100)
  }, [initialVolume])

  // Park the playhead at the last saved position (M1.15 §17.6.4): once
  // the transport exists, seek there. Playback stays paused (§17.6.5);
  // the transport applies a pre-target park on first play. Declared
  // after the transport effect so a same-commit arrival still finds it.
  useEffect(() => {
    if (parkPosition === undefined || parkedRef.current) return
    const transport = transportRef.current
    if (!transport) return
    parkedRef.current = true
    transport.seek(Math.min(parkPosition, info?.durationFrames ?? parkPosition))
  }, [parkPosition, info])

  // Tab visibility return (spec §15.5): redraw from the actual transport
  // state; `sync` also picks up a context that closed while the tab was
  // hidden.
  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState !== 'visible') return
      const transport = transportRef.current
      if (!transport) return
      const snap = transport.sync()
      setTransportState(snap.state)
      reportPosition(snap.position)
      setSuspended(snap.isSuspended)
      setDiagnostics(transport.diagnostics)
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [reportPosition])

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

  const handlePlayPause = useCallback(async () => {
    const transport = transportRef.current
    if (!transport || !info) return
    setPlayError(null)
    if (transport.contextLost) {
      // Audio-device-change recovery (spec §15.6): a fresh context, the
      // representation re-resolved at its rate, and `rebind` (which keeps
      // the retained position) before playing.
      try {
        const context = (createAudioContext ?? defaultCreateAudioContext)()
        const target = await ensurePlaybackTarget(projectId, importId, context.sampleRate)
        assetIdRef.current = target.assetId
        pendingContextRef.current = context
        transport.rebind({
          target,
          projectRate: info.sampleRate,
          projectDurationFrames: info.durationFrames,
        })
      } catch (err) {
        setPlayError(err instanceof Error ? err.message : String(err))
        return
      }
    } else if (
      suspended &&
      (transport.currentState === 'playing' ||
        transport.currentState === 'buffering' ||
        transport.currentState === 'seeking')
    ) {
      // Browser suspension (spec §15.5): `play` is the user gesture that
      // resumes the frozen context; no state change is needed.
      try {
        await transport.play()
      } catch (err) {
        setPlayError(err instanceof Error ? err.message : String(err))
      }
      return
    } else if (transport.currentState === 'playing' || transport.currentState === 'buffering') {
      transport.pause()
      return
    }
    if (!sourceLoadedRef.current) {
      try {
        const context = (createAudioContext ?? defaultCreateAudioContext)()
        await context.resume()
        const target = await ensurePlaybackTarget(projectId, importId, context.sampleRate)
        assetIdRef.current = target.assetId
        pendingContextRef.current = context
        await transport.loadSource({
          target,
          projectRate: info.sampleRate,
          projectDurationFrames: info.durationFrames,
        })
        sourceLoadedRef.current = true
      } catch (err) {
        setPlayError(err instanceof Error ? err.message : String(err))
        return
      }
    }
    try {
      await transport.play()
    } catch (err) {
      setPlayError(err instanceof Error ? err.message : String(err))
    }
  }, [createAudioContext, importId, info, projectId, suspended])

  const handleStop = useCallback(() => {
    transportRef.current?.stop()
  }, [])

  const handleVolumeChange = useCallback(
    (value: number) => {
      volumeRef.current = value
      setVolume(value)
      transportRef.current?.setOutputGain(value / 100)
      onVolumeChange?.(value)
    },
    [onVolumeChange],
  )

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

  const busy =
    transportState === 'preparing' || transportState === 'seeking' || transportState === 'buffering'
  // While suspended the button offers the resume gesture, not a pause.
  const showPause = (transportState === 'playing' || transportState === 'buffering') && !suspended
  const showSuspensionHint =
    suspended &&
    (transportState === 'playing' || transportState === 'buffering' || transportState === 'seeking')

  return (
    <div className="playback-panel">
      <section className="source-info" aria-label="Source information">
        <h3>Source</h3>
        <dl>
          <dt>Sample rate</dt>
          <dd>{info.sampleRate} Hz</dd>
          <dt>Duration</dt>
          <dd>{formatTime(info.durationFrames, info.sampleRate)}</dd>
          <dt>Frame</dt>
          <dd>{position}</dd>
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
            disabled={busy}
            aria-label={showPause ? 'Pause' : 'Play'}
          >
            {showPause ? 'Pause' : 'Play'}
          </button>
          <button type="button" onClick={handleStop} disabled={transportState === 'unloaded'}>
            Stop
          </button>
        </div>
        <span className="time-readout">
          {formatTime(position, info.sampleRate)} /{' '}
          {formatTime(info.durationFrames, info.sampleRate)}
        </span>
        <div className="playback-volume">
          <label>
            <span>Volume</span>
            <input
              type="range"
              min={0}
              max={200}
              step={5}
              value={volume}
              onChange={(e) => handleVolumeChange(Number(e.target.value))}
              aria-label="Monitoring volume"
            />
            <span className="volume-value">{volume}%</span>
          </label>
          {volume > 100 && (
            <span className="volume-clipping" role="status">
              May clip
            </span>
          )}
        </div>
        {busy && (
          <p className="muted" role="status">
            Preparing playback…
          </p>
        )}
        {showSuspensionHint && (
          <p className="suspension-hint" role="status">
            Browser suspended audio — click Play to resume
          </p>
        )}
        {diagnostics.underruns > 0 && (
          <p className="underrun-diagnostics muted">Underruns: {diagnostics.underruns}</p>
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
 * Holds the seek function (M1.11) and the audible playhead source (M1.14)
 * the transport panel registers for the editor; the editor reads the
 * playhead at display rate, so no per-update app state is needed.
 *
 * M1.15: owns the project-command hook — restores the server working
 * state into the editor and panel (viewport, selection, channel display,
 * follow, volume, playhead park) and autosaves changes back (debounced
 * view ops, position cadence, flush on unmount).
 */
function ProjectView({ project }: { project: ProjectSummary }) {
  const [seekFn, setSeekFn] = useState<((frame: number) => void) | null>(null)
  const [playheadSource, setPlayheadSource] = useState<PlayheadSource | null>(null)
  const handleRegisterSeek = useCallback(
    (fn: ((frame: number) => void) | null) => setSeekFn(fn),
    [],
  )
  const handleRegisterPlayhead = useCallback(
    (source: PlayheadSource | null) => setPlayheadSource(source),
    [],
  )

  const commands = useProjectCommands(project.id)
  // Read the latest hook functions through refs so the callbacks below
  // stay referentially stable (the panel is memoized; the editor keys
  // effects on callback identity).
  const scheduleViewRef = useRef(commands.scheduleView)
  scheduleViewRef.current = commands.scheduleView
  const notePositionRef = useRef(commands.notePosition)
  notePositionRef.current = commands.notePosition
  const flushRef = useRef(commands.flush)
  flushRef.current = commands.flush
  const sendRef = useRef(commands.send)
  sendRef.current = commands.send
  const undoRef = useRef(commands.undo)
  undoRef.current = commands.undo
  const redoRef = useRef(commands.redo)
  redoRef.current = commands.redo

  const handleViewportChange = useCallback((view: EditorView) => {
    scheduleViewRef.current({
      type: 'set_viewport',
      viewport: { start_frame: view.startFrame, frames_per_css_pixel: view.fpp },
    })
  }, [])
  const handleSelectionChange = useCallback((selection: { start: number; end: number } | null) => {
    // Both null clears the selection; present together otherwise.
    scheduleViewRef.current({
      type: 'set_selection',
      start_frames: selection?.start ?? null,
      end_frames: selection?.end ?? null,
    })
  }, [])
  const handleChannelDisplayChange = useCallback(
    (display: { linked: boolean; scales: number[] }) => {
      scheduleViewRef.current({ type: 'set_display', channel_display: display })
    },
    [],
  )
  const handleFollowChange = useCallback((follow: boolean) => {
    scheduleViewRef.current({ type: 'set_follow_playhead', follow_playhead: follow })
  }, [])
  const handleVolumeChange = useCallback((percent: number) => {
    scheduleViewRef.current({ type: 'set_monitoring_volume', volume: percent / 100 })
  }, [])
  const handlePositionReport = useCallback((frame: number, playing: boolean) => {
    notePositionRef.current(frame, playing)
  }, [])

  // Marker state (M1.15 §17.2). The selection is local UI state; the markers
  // themselves are authoritative server state (commands.markers).
  const [selectedMarkerId, setSelectedMarkerId] = useState<string | null>(null)
  const seekFnRef = useRef(seekFn)
  seekFnRef.current = seekFn

  // Reset the selection when the project changes or the marker disappears.
  useEffect(() => {
    setSelectedMarkerId(null)
  }, [project.id])
  useEffect(() => {
    if (selectedMarkerId && !commands.markers.some((m) => m.id === selectedMarkerId)) {
      setSelectedMarkerId(null)
    }
  }, [selectedMarkerId, commands.markers])

  const handleAddMarker = useCallback((frame: number) => {
    void sendRef.current({
      type: 'add_marker',
      label: 'Marker',
      color: '#e11d48',
      position_frames: frame,
    })
  }, [])
  const handleMoveMarker = useCallback((id: string, frame: number) => {
    void sendRef.current({ type: 'update_marker', marker_id: id, position_frames: frame })
  }, [])
  const handleUpdateMarker = useCallback(
    (id: string, patch: { label?: string; color?: string; positionFrames?: number }) => {
      const op: {
        type: 'update_marker'
        marker_id: string
        label?: string
        color?: string
        position_frames?: number
      } = { type: 'update_marker', marker_id: id }
      if (patch.label !== undefined) op.label = patch.label
      if (patch.color !== undefined) op.color = patch.color
      if (patch.positionFrames !== undefined) op.position_frames = patch.positionFrames
      void sendRef.current(op)
    },
    [],
  )
  const handleDeleteMarker = useCallback((id: string) => {
    void sendRef.current({ type: 'delete_marker', marker_id: id })
  }, [])
  const handleSelectMarker = useCallback((id: string | null) => {
    setSelectedMarkerId(id)
  }, [])
  const handleSeekToMarker = useCallback((frame: number) => {
    seekFnRef.current?.(frame)
  }, [])
  const handleUndo = useCallback(() => {
    void undoRef.current()
  }, [])
  const handleRedo = useCallback(() => {
    void redoRef.current()
  }, [])

  // Flush pending view ops on unmount (M1.15 §17.5.5). Project switches
  // are flushed inside the hook (armed ops go to the previous project).
  useEffect(() => {
    return () => {
      void flushRef.current()
    }
  }, [])

  // Restored working state (M1.15 §17.6). `undefined` until the snapshot
  // loads (legacy behavior in the meantime); `null` means the server
  // default → the legacy localStorage fallback.
  const ws = commands.workingState
  const display = ws.channel_display ?? { linked: true, scales: [] }
  const displayIsDefault = display.linked && (display.scales?.length ?? 0) === 0
  const initialViewport: EditorView | null | undefined = !commands.loaded
    ? undefined
    : ws.viewport
      ? { startFrame: ws.viewport.start_frame, fpp: ws.viewport.frames_per_css_pixel }
      : null
  const initialSelection = commands.loaded ? ws.selection : undefined
  const initialChannelDisplay =
    commands.loaded && !displayIsDefault
      ? { linked: display.linked, scales: display.scales ?? [] }
      : null
  const initialFollow = commands.loaded && !ws.follow_playhead ? false : null
  const initialVolume = commands.loaded ? Math.round(ws.monitoring_volume * 100) : undefined
  const parkPosition = commands.loaded ? ws.last_position_frames : undefined

  return (
    <>
      {commands.pending && (
        <p className="save-state" role="status">
          Saving…
        </p>
      )}
      {commands.staleNotice && (
        <p className="stale-notice" role="status">
          {commands.staleNotice}{' '}
          <button type="button" onClick={commands.clearStaleNotice}>
            Dismiss
          </button>
        </p>
      )}
      <PlaybackPanel
        projectId={project.id}
        registerSeek={handleRegisterSeek}
        registerPlayhead={handleRegisterPlayhead}
        initialVolume={initialVolume}
        onVolumeChange={handleVolumeChange}
        onPositionReport={handlePositionReport}
        parkPosition={parkPosition}
      />
      <WaveformEditor
        projectId={project.id}
        sourceAssetId={project.canonical_asset_id ?? null}
        playheadSource={playheadSource ?? undefined}
        onSeek={seekFn ?? undefined}
        initialViewport={initialViewport}
        initialSelection={initialSelection}
        initialChannelDisplay={initialChannelDisplay}
        initialFollow={initialFollow}
        onViewportChange={handleViewportChange}
        onSelectionChange={handleSelectionChange}
        onChannelDisplayChange={handleChannelDisplayChange}
        onFollowChange={handleFollowChange}
        markers={commands.markers}
        selectedMarkerId={selectedMarkerId}
        onAddMarker={handleAddMarker}
        onMoveMarker={handleMoveMarker}
        onUpdateMarker={handleUpdateMarker}
        onDeleteMarker={handleDeleteMarker}
        onSelectMarker={handleSelectMarker}
        onSeekToMarker={handleSeekToMarker}
        onUndo={handleUndo}
        onRedo={handleRedo}
        canUndo={commands.canUndo}
        canRedo={commands.canRedo}
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
