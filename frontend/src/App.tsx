import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createApiClient, errorMessage } from './api/client'
import {
  createJob,
  decodeCanonicalImport,
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
import { fetchResultSetDetail, type ResultSetDetail, type StemRole } from './api/result-sets'
import type { PracticeLoop, PracticeState } from './api/commands'
import {
  initialTransportDiagnostics,
  PcmTransport,
  type MixPeaks,
  type SourceSpec,
  type TransportContextLike,
  type TransportDiagnostics,
  type TransportLoopSpec,
  type TransportState,
} from './playback/transport'
import { formatTime } from './playback/pcm'
import { useSystemRuntime, type RuntimeStatus } from './system/useSystemRuntime'
import { WaveformEditor, type PlayheadSource, type ViewSource } from './waveform/WaveformEditor'
import { RhythmAnalysisPanel } from './rhythm/RhythmAnalysisPanel'
import { RhythmLanes } from './rhythm/RhythmLanes'
import { RhythmVersionSelector } from './rhythm/RhythmVersionSelector'
import { fetchMetronomeSchedule } from './api/metronome'
import { fetchCountInPlan } from './api/countIn'
import { fetchRhythmGrid, type RhythmGridData } from './api/rhythm'
import { musicalReadout } from './music/readout'
import { musicalAtSource } from './music/tempoGrid'
import type { View as EditorView } from './waveform/viewport'
import { OpenProjectPanel } from './projects/OpenProjectPanel'
import { useProjectCommands } from './projects/useProjectCommands'
import { LoopsPanel, MIN_REPEATABLE_LOOP_SECONDS, type LoopPatch } from './practice/LoopsPanel'
import { MetronomePanel, type MetronomePatch } from './practice/MetronomePanel'
import { CountInPanel, type CountInPatch } from './practice/CountInPanel'
import { PortableSavePanel } from './tracks/PortableSavePanel'
import type { ConnectionState, ProjectSummary } from './types'
import {
  BASS_PAIR_ROLES,
  FOUR_STEM_ROLES,
  TrackStack,
  type PlaybackMode,
} from './tracks/TrackStack'
import type { TrackSettingsPatch } from './tracks/MixerStrip'
import type { PlaybackTarget } from './api/playback'

/** A mix source plus the stem role it plays (UI-layer mapping). */
export type StemSource = SourceSpec & { role: string }

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
  sample_rate?: number | null
}): ProjectSummary {
  return {
    id: p.id,
    name: p.name,
    status: p.status === 'ready' ? 'ready' : 'empty',
    created_at: p.created_at,
    updated_at: p.updated_at,
    canonical_asset_id: p.canonical_asset_id ?? null,
    sample_rate: p.sample_rate ?? null,
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

function ImportPanel({
  projectId,
  hasCanonicalAudio,
  onImported,
}: {
  projectId: string
  hasCanonicalAudio: boolean
  onImported: () => void
}) {
  const [uploadState, setUploadState] = useState<UploadState>({ kind: 'idle' })
  const [pendingDecode, setPendingDecode] = useState<string | null>(null)
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

  useEffect(() => {
    if (hasCanonicalAudio) {
      setPendingDecode(null)
      return
    }
    let cancelled = false
    latestCompletedImportId(projectId)
      .then((importId) => {
        if (!cancelled) setPendingDecode(importId)
      })
      .catch(() => {
        if (!cancelled) setPendingDecode(null)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, hasCanonicalAudio, uploadState.kind])

  /**
   * Decode the completed transfer into the project's canonical audio.
   * The upload alone only creates a complete import row; without this
   * durable job the project stays empty and no waveform/playback panel
   * can load.
   */
  const finalizeImport = useCallback(
    async (importId: string, controller: AbortController) => {
      setUploadState({ kind: 'completing' })
      try {
        await decodeCanonicalImport(projectId, importId, controller.signal)
        onImported()
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
          await finalizeImport(result.importId, controller)
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
    [projectId, finalizeImport],
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
        const controller = abortRef.current ?? new AbortController()
        setStreamChoice(null)
        await finalizeImport(streamChoice.importId, controller)
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
    [streamChoice, finalizeImport],
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

      {pendingDecode && uploadState.kind === 'idle' && !hasCanonicalAudio && (
        <div className="import-recovery" role="status">
          <p>An uploaded file is waiting to be prepared as project audio.</p>
          <button
            type="button"
            onClick={() => {
              const controller = new AbortController()
              abortRef.current = controller
              void finalizeImport(pendingDecode, controller)
            }}
          >
            Prepare audio
          </button>
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

function defaultCreateAudioContext(sampleRate?: number): TransportContextLike {
  // Stem-mode playback runs at the project rate (spec §10.5.1): the stems
  // are stored at the project rate and the transport never resamples.
  const context = sampleRate ? new AudioContext({ sampleRate }) : new AudioContext()
  return context as unknown as TransportContextLike
}

/** The transport loop spec for the practice state's active loop (M2.11 §13). */
function loopSpecOf(practice: PracticeState | null | undefined): TransportLoopSpec | null {
  if (!practice) return null
  const loop = (practice.loops ?? []).find((l) => l.id === practice.active_loop_id)
  if (!loop) return null
  return {
    startFrame: loop.start_frames,
    endFrame: loop.end_frames,
    repeatCount: loop.repeat_count ?? null,
    boundaryFade: loop.boundary_fade,
  }
}

/** Change key for the loop spec: `setLoop` is not idempotent while playing. */
function loopKeyOf(spec: TransportLoopSpec | null): string {
  if (!spec) return 'none'
  return `${spec.startFrame}:${spec.endFrame}:${spec.repeatCount ?? 'inf'}:${spec.boundaryFade ? 1 : 0}`
}

/** MiB with one decimal (runtime diagnostics sizes). */
function formatMiB(bytes: number | null | undefined): string {
  if (bytes == null) return '—'
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
}

/** One runtime row per available §14.4 figure (null blocks are skipped). */
function RuntimeRows({ runtime }: { runtime: RuntimeStatus }) {
  const worker = runtime.media_worker
  const gpu = runtime.gpu
  const job = runtime.job
  return (
    <>
      {worker && (
        <li>
          Media worker: {formatMiB(worker.rss_bytes)}
          {worker.cpu_seconds != null ? `, ${worker.cpu_seconds.toFixed(1)} s CPU` : ''}
        </li>
      )}
      {gpu?.peak_used_bytes != null && <li>GPU peak: {formatMiB(gpu.peak_used_bytes)}</li>}
      {job?.job_type && (
        <li>
          Job: {job.job_type}
          {job.stage ? ` (${job.stage})` : ''}
          {job.progress_fraction != null ? ` ${Math.round(job.progress_fraction * 100)}%` : ''}
          {job.queued > 0 ? `, ${job.queued} queued` : ''}
        </li>
      )}
      {runtime.separation_elapsed_seconds != null && (
        <li>Separation: {runtime.separation_elapsed_seconds.toFixed(1)} s</li>
      )}
    </>
  )
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
  practiceState,
  stemSources,
  onPeaks,
  onLoopDisabled,
  metronomeEnabled,
  metronomeVolume,
  rhythmGridAvailable,
  countInEnabled,
  countInMode,
  countInRepetition,
  onToggleMetronome,
  onRhythmGrid,
}: {
  projectId: string
  createAudioContext?: (sampleRate?: number) => TransportContextLike
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
  /** The project's mixer/practice state (M2.8); null before first load. */
  practiceState?: PracticeState | null
  /**
   * The active group's mix sources (M2.8, spec §10.4.5): the stems for a
   * stem mode, null/absent for original mode (the source mix plays alone).
   */
  stemSources?: StemSource[] | null
  /** Per-quantum peak meters from the transport (spec §10.3.7). */
  onPeaks?: (peaks: MixPeaks) => void
  /**
   * The transport disabled looping because a seek left the active loop
   * (M2.11 §13.4.5): the caller persists `loop_enabled = false`.
   */
  onLoopDisabled?: () => void
  metronomeEnabled?: boolean
  metronomeVolume?: number
  rhythmGridAvailable?: boolean
  countInEnabled?: boolean
  countInMode?: 'off' | 'one_bar' | 'two_bars'
  countInRepetition?: 'once' | 'every_repeat'
  onToggleMetronome?: () => void
  onRhythmGrid?: (grid: RhythmGridData | null) => void
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
  const [diagnostics, setDiagnostics] = useState<TransportDiagnostics>(initialTransportDiagnostics)
  // M2.12 §14.4: the local runtime figures poll while the project panel
  // is open (it only mounts for an open project).
  const runtime = useSystemRuntime(true)
  const transportRef = useRef<PcmTransport | null>(null)
  const metronomeSettingsRef = useRef<{ enabled: boolean; volume: number } | null>(null)
  const rhythmGridAvailableRef = useRef(false)
  // Upcoming clicks keyed by source frame. Keeping the first computed
  // render frame for a source click prevents jitter and dropped beats
  // when overlapping lookahead fetches return the same click.
  const metronomePendingRef = useRef<
    Map<number, { frame: number; strength: 'downbeat' | 'beat' | 'grouping' | 'subdivision' }>
  >(new Map())
  const metronomeFetchAtRef = useRef(0)
  const onRhythmGridRef = useRef(onRhythmGrid)
  onRhythmGridRef.current = onRhythmGrid
  const lastReportedFrameRef = useRef<number | null>(null)
  const lastPlaybackRateRef = useRef<number | null>(null)
  const countInTimerRef = useRef<number | null>(null)
  const countInTickRef = useRef<number | null>(null)
  const countInActiveRef = useRef(false)
  const cancelCountInRef = useRef<(() => void) | null>(null)
  const countInStartedAtRef = useRef(0)
  const beginCountInRef = useRef<
    ((transport: PcmTransport, targetFrame: number) => Promise<boolean>) | null
  >(null)
  const [rhythmGrid, setRhythmGrid] = useState<RhythmGridData | null>(null)
  const [countInStatus, setCountInStatus] = useState<{
    totalFrames: number
    remainingFrames: number
    label: string
    offGrid: boolean
  } | null>(null)
  metronomeSettingsRef.current = metronomeEnabled
    ? { enabled: true, volume: metronomeVolume ?? 0.5 }
    : null
  rhythmGridAvailableRef.current = Boolean(rhythmGridAvailable)
  const assetIdRef = useRef<string | null>(null)
  const pendingContextRef = useRef<TransportContextLike | null>(null)
  const volumeRef = useRef(100)
  const sourceLoadedRef = useRef(false)
  const volumeSeededRef = useRef(false)
  const parkedRef = useRef(false)
  // M2.8: the last resolved original-mode target (for mode-switch rebinds)
  // and the latest mixer props (the transport is created once).
  const targetRef = useRef<PlaybackTarget | null>(null)
  const practiceStateRef = useRef(practiceState ?? null)
  practiceStateRef.current = practiceState ?? null
  const stemSourcesRef = useRef(stemSources ?? null)
  stemSourcesRef.current = stemSources ?? null
  // The transport callbacks are created once; read the latest prop through
  // a ref so the closure never goes stale.
  const onPositionReportRef = useRef(onPositionReport)
  onPositionReportRef.current = onPositionReport
  const onPeaksRef = useRef(onPeaks)
  onPeaksRef.current = onPeaks
  const onLoopDisabledRef = useRef(onLoopDisabled)
  onLoopDisabledRef.current = onLoopDisabled
  // M2.11 §13: the loop state last applied to the transport. `setLoop`
  // while playing is a controlled transition, so an unrelated practice
  // change must not re-send an unchanged spec.
  const loopKeyRef = useRef('none')
  const loopEnabledRef = useRef(false)

  /** Apply the practice state's active loop to the transport (M2.11 §13). */
  const applyLoop = useCallback(() => {
    const transport = transportRef.current
    const ps = practiceStateRef.current
    if (!transport || !ps) return
    const spec = loopSpecOf(ps)
    const key = loopKeyOf(spec)
    const enabled = ps.loop_enabled && spec !== null
    if (key !== loopKeyRef.current) {
      loopKeyRef.current = key
      transport.setLoop(spec)
    }
    if (enabled !== loopEnabledRef.current) {
      loopEnabledRef.current = enabled
      transport.setLoopEnabled(enabled)
    }
  }, [])

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

  const reportPosition = useCallback(
    (frame: number) => {
      setPosition(frame)
      // The transport reports on pause too (preserved position); the playing
      // flag lets the caller pick the autosave cadence (M1.15 §17.5.3).
      const transport = transportRef.current
      const state = transport?.currentState
      const playing = state === 'playing' || state === 'seeking' || state === 'buffering'
      onPositionReportRef.current?.(frame, playing)
      if (!transport) return
      const settings = metronomeSettingsRef.current
      if (!playing || !settings?.enabled || !rhythmGridAvailableRef.current) {
        if (metronomePendingRef.current.size > 0) {
          metronomePendingRef.current.clear()
          transport.scheduleMetronome([])
        }
        return
      }
      const now = performance.now()
      if (now - metronomeFetchAtRef.current < 500) return
      metronomeFetchAtRef.current = now
      const contextTime = transport.contextTime
      const contextRate = transport.contextRate
      if (contextTime == null || contextRate == null) return
      const rate = transport.playbackRate
      const projectRate = info?.sampleRate ?? contextRate
      const previousFrame = lastReportedFrameRef.current
      const previousRate = lastPlaybackRateRef.current
      lastReportedFrameRef.current = frame
      lastPlaybackRateRef.current = rate
      if (
        (previousFrame !== null && Math.abs(frame - previousFrame) > 0.25 * contextRate) ||
        (previousRate !== null && previousRate !== rate)
      ) {
        metronomePendingRef.current.clear()
        transport.scheduleMetronome([])
        metronomeFetchAtRef.current = 0
        const loop = practiceStateRef.current?.loops?.find(
          (item) => item.id === practiceStateRef.current?.active_loop_id,
        )
        if (
          countInEnabled &&
          countInRepetition === 'every_repeat' &&
          practiceStateRef.current?.loop_enabled &&
          loop &&
          !countInActiveRef.current &&
          previousFrame !== null &&
          frame < previousFrame
        ) {
          transport.pause()
          void beginCountInRef.current?.(transport, loop.start_frames)
          return
        }
      }
      const current = transport.getAudiblePosition()
      const duration = info?.durationFrames ?? null
      const windowEnd = Math.min(
        duration ?? frame + rate * 2 * contextRate,
        frame + Math.max(contextRate, rate * 2 * contextRate),
      )
      fetchMetronomeSchedule(projectId, Math.max(0, Math.floor(current)), Math.ceil(windowEnd))
        .then((schedule) => {
          const nowRender = Math.round((transport.contextTime ?? contextTime) * contextRate)
          const scheduled = metronomePendingRef.current
          // Keep the first frame computed for a source click; later
          // overlapping windows must not move or drop it.
          for (const click of schedule.clicks ?? []) {
            if (scheduled.has(click.source_frame)) continue
            const frame = Math.round(
              (contextTime + (click.source_frame - current) / (projectRate * rate)) * contextRate,
            )
            if (frame <= nowRender + Math.round(0.03 * contextRate)) continue
            scheduled.set(click.source_frame, {
              frame,
              strength: click.strength as 'downbeat' | 'beat' | 'grouping' | 'subdivision',
            })
          }
          for (const [sourceFrame, click] of scheduled) {
            if (click.frame < nowRender - contextRate) scheduled.delete(sourceFrame)
          }
          const next = [...scheduled.values()]
            .sort((left, right) => left.frame - right.frame)
            .slice(0, 512)
          transport.scheduleMetronome(next, settings.volume)
        })
        .catch(() => {
          // A missing/invalid grid leaves the metronome silent.
        })
    },
    [info?.durationFrames, info?.sampleRate, projectId],
  )

  // New project: drop any previous transport and source binding.
  useEffect(() => {
    transportRef.current?.dispose()
    transportRef.current = null
    sourceLoadedRef.current = false
    assetIdRef.current = null
    targetRef.current = null
    pendingContextRef.current = null
    setTransportState('unloaded')
    setPosition(0)
    setPlayError(null)
    setSuspended(false)
    setDiagnostics(initialTransportDiagnostics())
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
      cancelCountInRef.current?.()
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

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable)
      ) {
        return
      }
      if (event.shiftKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
        const bars = rhythmGrid?.grid.events
          .filter((item) => item.kind === 'bar')
          .slice()
          .sort((left, right) => left.source_frame - right.source_frame)
        if (!bars || bars.length === 0) {
          event.preventDefault()
          setPlayError('No musical grid is available for bar navigation')
          return
        }
        const current = transportRef.current?.getAudiblePosition() ?? 0
        const targetBar =
          event.key === 'ArrowRight'
            ? bars.find((bar) => bar.source_frame > current)
            : bars
                .slice()
                .reverse()
                .find((bar) => bar.source_frame < current)
        if (!targetBar) {
          event.preventDefault()
          setPlayError('No further mapped bar in that direction')
          return
        }
        event.preventDefault()
        transportRef.current?.seek(targetBar.source_frame)
        reportPosition(targetBar.source_frame)
      } else if (
        event.key.toLowerCase() === 'm' &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey
      ) {
        event.preventDefault()
        if (!rhythmGrid) {
          setPlayError('The metronome needs an active musical grid')
          return
        }
        onToggleMetronome?.()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onToggleMetronome, reportPosition, rhythmGrid])

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
      // M2.11 §13.4.5: a seek outside the active loop disables looping;
      // the caller persists `loop_enabled = false`.
      onLoopDisabled: () => onLoopDisabledRef.current?.(),
      // M2.8 monitoring (spec §10.6): limiter default-on; the live toggle
      // arrives through `setLimiter` once the practice state is known.
      limiter: practiceStateRef.current?.monitoring_limiter ?? true,
      onPeaks: (peaks) => onPeaksRef.current?.(peaks),
    })
    transport.setOutputGain(volumeRef.current / 100)
    transportRef.current = transport
    // M2.11: seed the restored loop state now that the transport exists
    // (`applyLoop` is a no-op while `transportRef` is still empty, so an
    // enable-on-load is applied here instead). Enabling while stopped is
    // state-only (§13.4.1); the next play applies it.
    loopKeyRef.current = 'none'
    loopEnabledRef.current = false
    applyLoop()
  }, [createAudioContext, info, reportPosition, applyLoop])

  // Re-apply the loop when the practice state changes (M2.11 §13):
  // enable/disable plus spec edits, guarded so an unrelated practice
  // change never triggers a needless loop transition.
  useEffect(() => {
    applyLoop()
  }, [applyLoop, practiceState])

  // M2.8 mixer state → live transport (spec §10.3): master gain, limiter,
  // and one `setSourceParams` per stem in mix order. M2.9 adds the
  // playback speed (spec §11): `setRate` is remembered and applies to a
  // fresh graph. Safe before the graph exists (no-ops).
  const applyMix = useCallback(() => {
    const transport = transportRef.current
    const ps = practiceStateRef.current
    if (!transport || !ps) return
    transport.setMasterGain(ps.master_gain)
    transport.setLimiter(ps.monitoring_limiter)
    transport.setRate(ps.playback_speed)
    const stems = stemSourcesRef.current
    if (stems && stems.length > 0) {
      stems.forEach((s, i) => {
        const t = ps.tracks?.[s.role]
        if (t) {
          transport.setSourceParams(i, {
            gain: t.gain,
            balance: t.balance,
            mute: t.mute,
            solo: t.solo,
          })
        }
      })
    }
  }, [])

  // Re-apply the mixer whenever the practice state or the mix group
  // changes (and once when the transport first exists).
  useEffect(() => {
    applyMix()
  }, [applyMix, practiceState, stemSources])

  // M2.8 mode switch (spec §10.4.5): the groups are mutually exclusive,
  // so a loaded transport is rebound to the new group's sources (the
  // retained position is kept; the next play builds a fresh graph).
  const modeKey = useMemo(
    () =>
      stemSources && stemSources.length > 0
        ? `stems:${stemSources.map((s) => s.assetId).join(',')}`
        : 'original',
    [stemSources],
  )
  useEffect(() => {
    const transport = transportRef.current
    if (!transport || !info || !sourceLoadedRef.current) return
    transport.pause()
    const stems = stemSourcesRef.current
    if (stems && stems.length > 0) {
      transport.rebind({
        sources: stems,
        projectRate: info.sampleRate,
        projectDurationFrames: info.durationFrames,
      })
      sourceLoadedRef.current = false
      setTransportState('unloaded')
    } else if (targetRef.current) {
      transport.rebind({
        target: targetRef.current,
        projectRate: info.sampleRate,
        projectDurationFrames: info.durationFrames,
      })
      sourceLoadedRef.current = false
      setTransportState('unloaded')
    } else {
      // No original target has been resolved yet: resolve it now (at the
      // live context's rate) and rebind, keeping the retained position.
      const rate = transport.contextRate ?? info.sampleRate
      void ensurePlaybackTarget(projectId, importId, rate)
        .then((target) => {
          targetRef.current = target
          transport.rebind({
            target,
            projectRate: info.sampleRate,
            projectDurationFrames: info.durationFrames,
          })
          sourceLoadedRef.current = false
          setTransportState('unloaded')
        })
        .catch((err) => {
          sourceLoadedRef.current = false
          setPlayError(err instanceof Error ? err.message : String(err))
        })
    }
  }, [modeKey, info, importId, projectId])

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

  useEffect(() => {
    if (!rhythmGridAvailable || !info) {
      setRhythmGrid(null)
      return
    }
    const controller = new AbortController()
    fetchRhythmGrid(
      projectId,
      { startFrame: 0, endFrame: info.durationFrames, detail: 'bars' },
      controller.signal,
    )
      .then((data) => {
        setRhythmGrid(data)
        onRhythmGridRef.current?.(data)
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setRhythmGrid(null)
          onRhythmGridRef.current?.(null)
        }
      })
    return () => controller.abort()
  }, [info, projectId, rhythmGridAvailable])

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

  const cancelCountIn = useCallback(() => {
    countInActiveRef.current = false
    if (countInTimerRef.current !== null) {
      window.clearTimeout(countInTimerRef.current)
      countInTimerRef.current = null
    }
    if (countInTickRef.current !== null) {
      window.clearInterval(countInTickRef.current)
      countInTickRef.current = null
    }
    setCountInStatus(null)
    transportRef.current?.scheduleMetronome([])
  }, [])
  cancelCountInRef.current = cancelCountIn

  const beginCountIn = useCallback(
    async (transport: PcmTransport, targetFrame: number): Promise<boolean> => {
      if (
        !countInEnabled ||
        countInMode === undefined ||
        countInMode === 'off' ||
        !rhythmGridAvailableRef.current
      ) {
        return false
      }
      try {
        const plan = await fetchCountInPlan(
          projectId,
          Math.max(0, Math.floor(targetFrame)),
          transport.playbackRate,
        )
        const contextTime = transport.contextTime
        const sampleRate = transport.contextRate
        if (
          !plan.available ||
          plan.total_frames <= 0 ||
          contextTime == null ||
          sampleRate == null
        ) {
          return false
        }
        const baseFrame = Math.round(contextTime * sampleRate)
        transport.scheduleMetronome(
          (plan.clicks ?? []).map((click) => ({
            frame: baseFrame + click.offset_frames,
            strength: click.strength,
          })),
          metronomeVolume ?? 0.5,
        )
        countInActiveRef.current = true
        countInStartedAtRef.current = performance.now()
        setCountInStatus({
          totalFrames: plan.total_frames,
          remainingFrames: plan.total_frames,
          label: `${plan.bars} bar${plan.bars === 1 ? '' : 's'}`,
          offGrid: plan.off_grid,
        })
        const update = () => {
          const elapsedMs = performance.now() - countInStartedAtRef.current
          const remaining = Math.max(0, plan.total_frames - (elapsedMs / 1000) * sampleRate)
          setCountInStatus((current) =>
            current ? { ...current, remainingFrames: remaining } : current,
          )
        }
        countInTickRef.current = window.setInterval(update, 100)
        countInTimerRef.current = window.setTimeout(
          () => {
            countInTimerRef.current = null
            countInActiveRef.current = false
            if (countInTickRef.current !== null) {
              window.clearInterval(countInTickRef.current)
              countInTickRef.current = null
            }
            setCountInStatus(null)
            transport.seek(targetFrame)
            void transport.play()
          },
          (plan.total_frames / sampleRate) * 1000,
        )
        return true
      } catch {
        return false
      }
    },
    [countInEnabled, countInMode, metronomeVolume, projectId],
  )
  beginCountInRef.current = beginCountIn

  const handlePlayPause = useCallback(async () => {
    if (countInActiveRef.current) {
      cancelCountIn()
      return
    }
    const transport = transportRef.current
    if (!transport || !info) return
    setPlayError(null)
    const stems = stemSourcesRef.current
    const stemMode = stems !== null && stems.length > 0
    // Spec §10.5.1: stem playback runs at the project rate (the stems are
    // stored there and the transport never resamples); original mode keeps
    // the M1 behavior (context at the device rate, converted target).
    const makeContext = async (): Promise<TransportContextLike> => {
      const context = (createAudioContext ?? defaultCreateAudioContext)(
        stemMode ? info.sampleRate : undefined,
      )
      await context.resume()
      return context
    }
    if (transport.contextLost) {
      // Audio-device-change recovery (spec §15.6): a fresh context, the
      // sources re-bound at their rates, and `rebind` (which keeps the
      // retained position) before playing.
      try {
        const context = await makeContext()
        pendingContextRef.current = context
        if (stemMode) {
          assetIdRef.current = stems[0].assetId
          transport.rebind({
            sources: stems,
            projectRate: info.sampleRate,
            projectDurationFrames: info.durationFrames,
          })
        } else {
          const target = await ensurePlaybackTarget(projectId, importId, context.sampleRate)
          targetRef.current = target
          assetIdRef.current = target.assetId
          transport.rebind({
            target,
            projectRate: info.sampleRate,
            projectDurationFrames: info.durationFrames,
          })
        }
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
      cancelCountIn()
      return
    }
    if (countInTimerRef.current !== null) {
      window.clearTimeout(countInTimerRef.current)
      countInTimerRef.current = null
      transport.scheduleMetronome([])
    }
    if (!sourceLoadedRef.current) {
      try {
        const context = await makeContext()
        pendingContextRef.current = context
        if (stemMode) {
          assetIdRef.current = stems[0].assetId
          await transport.loadSource({
            sources: stems,
            projectRate: info.sampleRate,
            projectDurationFrames: info.durationFrames,
          })
        } else {
          const target = await ensurePlaybackTarget(projectId, importId, context.sampleRate)
          targetRef.current = target
          assetIdRef.current = target.assetId
          await transport.loadSource({
            target,
            projectRate: info.sampleRate,
            projectDurationFrames: info.durationFrames,
          })
        }
        sourceLoadedRef.current = true
      } catch (err) {
        setPlayError(err instanceof Error ? err.message : String(err))
        return
      }
    }
    let countInStarted = false
    const activeLoop = practiceState?.loops?.find(
      (loop) => loop.id === practiceState.active_loop_id,
    )
    const targetFrame =
      practiceState?.loop_enabled && activeLoop
        ? activeLoop.start_frames
        : transport.getAudiblePosition()
    countInStarted = await beginCountIn(transport, targetFrame)
    if (!countInStarted) {
      try {
        await transport.play()
      } catch (err) {
        setPlayError(err instanceof Error ? err.message : String(err))
        return
      }
    }
    // The fresh graph starts at defaults: apply the current mixer state
    // (spec §10.3) now that the worklet node exists.
    applyMix()
  }, [
    applyMix,
    beginCountIn,
    cancelCountIn,
    createAudioContext,
    importId,
    info,
    projectId,
    suspended,
  ])

  useEffect(() => () => cancelCountIn(), [cancelCountIn])

  const handleStop = useCallback(() => {
    cancelCountIn()
    transportRef.current?.stop()
  }, [cancelCountIn])

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
        {countInStatus ? (
          <span className="count-in-status" role="status">
            Count-in {countInStatus.label} ·{' '}
            {(countInStatus.remainingFrames / info.sampleRate).toFixed(1)} s
            {countInStatus.offGrid ? ' · off-grid start' : ''}
          </span>
        ) : null}
        <span className="time-readout">
          {formatTime(position, info.sampleRate)} /{' '}
          {formatTime(info.durationFrames, info.sampleRate)}
        </span>
        <span className="musical-readout" aria-live="off">
          {musicalReadout(rhythmGrid, position)}
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
        {(diagnostics.underruns > 0 ||
          diagnostics.stemBufferedFrames.length > 0 ||
          runtime !== null) && (
          <section className="runtime-diagnostics muted" aria-label="Runtime diagnostics">
            <ul>
              <li>Underruns: {diagnostics.underruns}</li>
              {diagnostics.stemBufferedFrames.length > 0 && (
                <li>Stems buffered: {diagnostics.stemBufferedFrames.join(' / ')} frames</li>
              )}
              {diagnostics.capacityFrames > 0 && (
                <li>
                  Buffer: {formatMiB(diagnostics.bufferedBytes)} /{' '}
                  {formatMiB(diagnostics.budgetBytes)}
                  {diagnostics.pinnedBytes > 0 && `, pinned ${formatMiB(diagnostics.pinnedBytes)}`}
                </li>
              )}
              {diagnostics.callbackDurationMs != null && (
                <li>Callback: {diagnostics.callbackDurationMs.toFixed(1)} ms</li>
              )}
              {diagnostics.stretcher && (
                <li>
                  Stretcher: {diagnostics.stretcher.rate.toFixed(2)}×
                  {diagnostics.stretcher.bypass ? ' (bypass)' : ''}
                </li>
              )}
              {runtime && <RuntimeRows runtime={runtime} />}
            </ul>
          </section>
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

  // M2.8: the editor's shared view (drives the stem lanes, spec §10.1.4)
  // and the transport's per-quantum peaks (spec §10.3.7).
  const [viewSource, setViewSource] = useState<ViewSource | null>(null)
  const handleRegisterView = useCallback((source: ViewSource | null) => setViewSource(source), [])
  const [peaks, setPeaks] = useState<MixPeaks | null>(null)
  const [projectRhythmGrid, setProjectRhythmGrid] = useState<RhythmGridData | null>(null)
  const handlePeaks = useCallback((p: MixPeaks) => setPeaks(p), [])

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

  // M2.11 practice loops (spec §13.2): the active loop, the live
  // waveform selection (seeded from the restored working state, then kept
  // up to date by the editor — the source for "Create from selection"),
  // and one-shot notices (the 100 ms minimum explanation, failed edits).
  const [liveSelection, setLiveSelection] = useState<{ start: number; end: number } | null>(null)
  const [loopNotice, setLoopNotice] = useState<string | null>(null)
  const selectionSeededRef = useRef(false)
  const practiceLiveRef = useRef(commands.practiceState)
  practiceLiveRef.current = commands.practiceState
  const selectionRef = useRef(liveSelection)
  selectionRef.current = liveSelection
  const sampleRateRef = useRef(project.sample_rate ?? 0)
  sampleRateRef.current = project.sample_rate ?? 0
  const activeLoop = useMemo(() => {
    const ps = commands.practiceState
    if (!ps) return null
    return (ps.loops ?? []).find((l) => l.id === ps.active_loop_id) ?? null
  }, [commands.practiceState])
  const activeLoopRef = useRef<PracticeLoop | null>(activeLoop)
  activeLoopRef.current = activeLoop
  const loopRange = useMemo(
    () =>
      activeLoop
        ? { start: activeLoop.start_frames, end: activeLoop.end_frames, color: activeLoop.color }
        : null,
    [activeLoop],
  )

  const handleViewportChange = useCallback((view: EditorView) => {
    scheduleViewRef.current({
      type: 'set_viewport',
      viewport: { start_frame: view.startFrame, frames_per_css_pixel: view.fpp },
    })
  }, [])
  const handleSelectionChange = useCallback((selection: { start: number; end: number } | null) => {
    // Mirror the live selection for the loop panel (M2.11 §13.2.1) ...
    setLiveSelection(selection)
    // ... and autosave it as the view-state selection.
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

  // M2.8 track stack (spec §10): the active set's detail feeds the stem
  // lanes (provenance, spec §10.1.6) and the transport's mix sources
  // (spec §10.4.5: the groups are mutually exclusive).
  const practiceState = commands.practiceState
  const mode: PlaybackMode = practiceState?.playback_mode ?? 'original'
  const activeSetId = practiceState?.active_result_set_id ?? null
  const [detail, setDetail] = useState<ResultSetDetail | null>(null)
  useEffect(() => {
    if (mode === 'original' || !activeSetId) {
      setDetail(null)
      return
    }
    const ctrl = new AbortController()
    fetchResultSetDetail(project.id, activeSetId, ctrl.signal)
      .then(setDetail)
      .catch(() => setDetail(null))
    return () => ctrl.abort()
  }, [project.id, mode, activeSetId])

  const stemSources = useMemo<StemSource[] | null>(() => {
    if (mode === 'original' || !detail) return null
    const order = mode === 'bass_pair' ? BASS_PAIR_ROLES : FOUR_STEM_ROLES
    const byRole = new Map(detail.stems.map((s) => [s.role, s]))
    return order
      .filter((role) => byRole.has(role))
      .map((role) => {
        const s = byRole.get(role)!
        return {
          role: s.role,
          assetId: s.audioAssetId,
          sampleRate: s.sampleRate,
          channelCount: s.channelCount,
          frameCount: s.frameCount,
        }
      })
  }, [mode, detail])

  const handleMode = useCallback((m: PlaybackMode) => {
    void sendRef.current({ type: 'set_playback_mode', mode: m })
  }, [])
  const handleSelectSet = useCallback((resultSetId: string) => {
    void sendRef.current({ type: 'set_active_result_set', result_set_id: resultSetId })
  }, [])
  const handleTrackSettings = useCallback((role: StemRole, patch: TrackSettingsPatch) => {
    const op = { type: 'set_track_settings', stem_role: role } as {
      type: 'set_track_settings'
      stem_role: StemRole
    } & Partial<TrackSettingsPatch>
    if (patch.gain !== undefined) op.gain = patch.gain
    if (patch.mute !== undefined) op.mute = patch.mute
    if (patch.solo !== undefined) op.solo = patch.solo
    if (patch.balance !== undefined) op.balance = patch.balance
    if (patch.visible !== undefined) op.visible = patch.visible
    if (patch.display_height !== undefined) op.display_height = patch.display_height
    if (patch.color !== undefined) op.color = patch.color
    void sendRef.current(op)
  }, [])
  const handleMasterGain = useCallback((linear: number) => {
    void sendRef.current({ type: 'set_master_gain', gain: linear })
  }, [])
  const handleLimiter = useCallback((enabled: boolean) => {
    void sendRef.current({ type: 'set_monitoring_limiter', enabled })
  }, [])
  const handlePlaybackSpeed = useCallback((speed: number) => {
    void sendRef.current({ type: 'set_playback_speed', speed })
  }, [])

  // Marker state (M1.15 §17.2). The selection is local UI state; the markers
  // themselves are authoritative server state (commands.markers).
  const [selectedMarkerId, setSelectedMarkerId] = useState<string | null>(null)
  const seekFnRef = useRef(seekFn)
  seekFnRef.current = seekFn

  // Reset the selection when the project changes or the marker disappears.
  useEffect(() => {
    setSelectedMarkerId(null)
    setLoopNotice(null)
    setLiveSelection(null)
    selectionSeededRef.current = false
  }, [project.id])
  useEffect(() => {
    if (selectedMarkerId && !commands.markers.some((m) => m.id === selectedMarkerId)) {
      setSelectedMarkerId(null)
    }
  }, [selectedMarkerId, commands.markers])

  // Seed the live selection from the restored working state once (M1.15
  // §17.6); the editor's autosave callback keeps it current afterwards
  // (it does not echo the restored value back).
  useEffect(() => {
    if (!commands.loaded || selectionSeededRef.current) return
    selectionSeededRef.current = true
    setLiveSelection(commands.workingState.selection ?? null)
  }, [commands.loaded, commands.workingState.selection])

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

  // --- M2.11 loop commands (spec §13.2) ------------------------------------

  const handleCreateMusicalLoopFromSelection = useCallback(() => {
    const selection = selectionRef.current
    if (!selection || !projectRhythmGrid) {
      setLoopNotice('No active musical grid for the selection.')
      return
    }
    try {
      const anchors = projectRhythmGrid.tempo_anchors.map((anchor) => ({
        sourceFrame: anchor.source_frame,
        musical: anchor.musical_position,
      }))
      const start = musicalAtSource(anchors, selection.start)
      const end = musicalAtSource(anchors, selection.end)
      if (end.numerator * start.denominator <= start.numerator * end.denominator) {
        setLoopNotice('The selection is too short for a musical loop.')
        return
      }
      const known = new Set((practiceLiveRef.current?.loops ?? []).map((loop) => loop.id))
      void (async () => {
        const res = await sendRef.current({
          type: 'add_musical_loop',
          start_musical: start,
          end_musical: end,
          boundary_fade: true,
        })
        if (!res) {
          setLoopNotice('Could not create the musical loop.')
          return
        }
        setLoopNotice(null)
        const created = (res.practiceState?.loops ?? []).find((loop) => !known.has(loop.id))
        if (created) void sendRef.current({ type: 'set_active_loop', loop_id: created.id })
      })()
    } catch {
      setLoopNotice('The selection is outside the active musical grid.')
    }
  }, [projectRhythmGrid])

  const handleCreateLoopFromSelection = useCallback(() => {
    const sel = selectionRef.current
    if (!sel) return
    // Snapshot the known loop ids before the send: the response's state
    // arrives with the created loop already in it.
    const known = new Set((practiceLiveRef.current?.loops ?? []).map((l) => l.id))
    void (async () => {
      const res = await sendRef.current({
        type: 'add_loop',
        start_frames: sel.start,
        end_frames: sel.end,
        boundary_fade: true,
      })
      if (!res) {
        setLoopNotice('Could not create the loop.')
        return
      }
      setLoopNotice(null)
      // Make the new loop active so its overlay shows immediately.
      const created = (res.practiceState?.loops ?? []).find((l) => !known.has(l.id))
      if (created) void sendRef.current({ type: 'set_active_loop', loop_id: created.id })
    })()
  }, [])

  const handleLoopConvert = useCallback((id: string, target: 'source' | 'musical') => {
    void (async () => {
      if (
        target === 'musical' &&
        !window.confirm(
          'Convert this loop to follow the musical grid? Its current boundaries will become musical positions.',
        )
      ) {
        return
      }
      const res = await sendRef.current({
        type: 'convert_loop',
        loop_id: id,
        target,
        confirm_off_grid: target === 'musical',
      })
      if (!res)
        setLoopNotice('Could not convert the loop; the active rhythm grid may be unavailable.')
    })()
  }, [])

  const handleMetronomeChange = useCallback((patch: MetronomePatch) => {
    void sendRef.current({ type: 'set_metronome', ...patch })
  }, [])

  const handleCountInChange = useCallback((patch: CountInPatch) => {
    void sendRef.current({ type: 'set_count_in', ...patch })
  }, [])

  const handleToggleMetronome = useCallback(() => {
    const enabled = commands.rhythmState?.metronome?.enabled ?? false
    void sendRef.current({ type: 'set_metronome', enabled: !enabled })
  }, [commands.rhythmState?.metronome?.enabled])

  const handleLoopUpdate = useCallback((id: string, patch: LoopPatch) => {
    const op: {
      type: 'update_loop'
      loop_id: string
      name?: string
      color?: string
      start_frames?: number
      end_frames?: number
      repeat_count?: number | null
      boundary_fade?: boolean
    } = { type: 'update_loop', loop_id: id }
    if (patch.name !== undefined) op.name = patch.name
    if (patch.color !== undefined) op.color = patch.color
    if (patch.start_frames !== undefined) op.start_frames = patch.start_frames
    if (patch.end_frames !== undefined) op.end_frames = patch.end_frames
    if (patch.boundary_fade !== undefined) op.boundary_fade = patch.boundary_fade
    // Present key (even null) = set; absent = unchanged (§13.1).
    if ('repeat_count' in patch) op.repeat_count = patch.repeat_count ?? null
    void sendRef.current(op)
  }, [])

  const handleLoopDuplicate = useCallback((id: string) => {
    void sendRef.current({ type: 'duplicate_loop', loop_id: id })
  }, [])

  const handleLoopDelete = useCallback((id: string) => {
    void sendRef.current({ type: 'delete_loop', loop_id: id })
  }, [])

  const handleLoopSelectActive = useCallback((id: string) => {
    if (practiceLiveRef.current?.active_loop_id === id) return
    void sendRef.current({ type: 'set_active_loop', loop_id: id })
  }, [])

  /** Waveform overlay drag committed (M2.11 §13.2.3–4, §13.8). */
  const handleLoopRangeChange = useCallback((start: number, end: number) => {
    const loop = activeLoopRef.current
    if (!loop || (loop.start_frames === start && loop.end_frames === end)) return
    void sendRef.current({
      type: 'update_loop',
      loop_id: loop.id,
      start_frames: start,
      end_frames: end,
    })
  }, [])

  /**
   * Enable/disable looping (the checkbox and `L` share this path). The
   * 100 ms minimum is validated here so the explanation shows without a
   * server round trip (spec §13.3.3–4); the server re-validates.
   */
  const handleSetLoopEnabled = useCallback((enabled: boolean) => {
    const ps = practiceLiveRef.current
    if (!ps) return
    if (enabled) {
      const loop = (ps.loops ?? []).find((l) => l.id === ps.active_loop_id) ?? null
      if (!loop) {
        setLoopNotice('Select a loop before enabling looping.')
        return
      }
      const sr = sampleRateRef.current
      if (sr > 0 && loop.end_frames - loop.start_frames < MIN_REPEATABLE_LOOP_SECONDS * sr) {
        setLoopNotice(
          'Loops shorter than 100 ms can be saved, but not repeated for practice. Lengthen the loop to enable it.',
        )
        return
      }
    }
    setLoopNotice(null)
    if (ps.loop_enabled === enabled) return
    void sendRef.current({ type: 'set_loop_enabled', enabled })
  }, [])

  /** Transport-side loop disable after a seek outside (§13.4.5): persist. */
  const handleLoopDisabled = useCallback(() => {
    void sendRef.current({ type: 'set_loop_enabled', enabled: false })
  }, [])

  // `L` toggles looping (spec §13.2.10): ignored while typing in an input
  // or with modifiers; a no-op without an active loop.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key !== 'l' && e.key !== 'L') return
      const target = e.target as HTMLElement | null
      if (target) {
        const tag = target.tagName
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable) {
          return
        }
      }
      const ps = practiceLiveRef.current
      if (!ps || !ps.active_loop_id) return
      e.preventDefault()
      handleSetLoopEnabled(!ps.loop_enabled)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [handleSetLoopEnabled])

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
        practiceState={practiceState}
        metronomeEnabled={commands.rhythmState?.metronome?.enabled ?? false}
        metronomeVolume={commands.rhythmState?.metronome?.volume ?? 0.5}
        rhythmGridAvailable={Boolean(commands.rhythmState?.active_branch_id)}
        countInEnabled={(commands.rhythmState?.count_in?.mode ?? 'off') !== 'off'}
        countInMode={commands.rhythmState?.count_in?.mode ?? 'off'}
        countInRepetition={commands.rhythmState?.count_in?.repetition ?? 'once'}
        onToggleMetronome={handleToggleMetronome}
        onRhythmGrid={setProjectRhythmGrid}
        stemSources={stemSources}
        onPeaks={handlePeaks}
        onLoopDisabled={handleLoopDisabled}
      />
      <RhythmAnalysisPanel projectId={project.id} refresh={commands.refresh} />
      {commands.rhythmState?.active_branch_id ||
      commands.rhythmState?.active_automatic_result_id ? (
        <RhythmVersionSelector
          projectId={project.id}
          activeResultId={commands.rhythmState?.active_automatic_result_id ?? null}
          activeBranchId={commands.rhythmState?.active_branch_id ?? null}
          refreshKey={commands.revision}
          onSelectResult={(id) =>
            void sendRef.current({ type: 'select_rhythm_result', result_id: id })
          }
          onSelectBranch={(id) =>
            void sendRef.current({ type: 'select_rhythm_branch', branch_id: id })
          }
        />
      ) : null}
      {viewSource && commands.rhythmState?.active_branch_id ? (
        <RhythmLanes
          projectId={project.id}
          viewSource={viewSource}
          playheadSource={playheadSource ?? undefined}
          onSeek={seekFn ?? undefined}
          refreshKey={commands.revision}
          selection={liveSelection}
        />
      ) : null}
      <TrackStack
        projectId={project.id}
        viewSource={viewSource}
        playheadSource={playheadSource ?? undefined}
        practiceState={practiceState}
        detail={detail}
        peaks={peaks}
        onTrackSettings={handleTrackSettings}
        onMasterGain={handleMasterGain}
        onLimiter={handleLimiter}
        onMode={handleMode}
        onSelectSet={handleSelectSet}
        onPlaybackSpeed={handlePlaybackSpeed}
      />
      <CountInPanel
        mode={commands.rhythmState?.count_in?.mode ?? 'off'}
        repetition={commands.rhythmState?.count_in?.repetition ?? 'once'}
        onChange={handleCountInChange}
      />
      <MetronomePanel
        enabled={commands.rhythmState?.metronome?.enabled ?? false}
        volume={commands.rhythmState?.metronome?.volume ?? 0.5}
        accentDownbeats={commands.rhythmState?.metronome?.accent_downbeats ?? true}
        subdivision={commands.rhythmState?.metronome?.subdivision ?? 'primary'}
        onChange={handleMetronomeChange}
      />
      <LoopsPanel
        loops={commands.practiceState?.loops ?? []}
        activeLoopId={commands.practiceState?.active_loop_id ?? null}
        loopEnabled={commands.practiceState?.loop_enabled ?? false}
        selection={liveSelection}
        sampleRate={project.sample_rate ?? 0}
        durationFrames={commands.durationFrames ?? 0}
        notice={loopNotice}
        onCreateFromSelection={handleCreateLoopFromSelection}
        onCreateMusicalFromSelection={handleCreateMusicalLoopFromSelection}
        onUpdate={handleLoopUpdate}
        onDuplicate={handleLoopDuplicate}
        onDelete={handleLoopDelete}
        onSelectActive={handleLoopSelectActive}
        onSetEnabled={handleSetLoopEnabled}
        onConvert={handleLoopConvert}
      />
      <div className="original-track-label">
        <span className="track-name">Original</span>
      </div>
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
        loop={loopRange}
        onLoopRangeChange={handleLoopRangeChange}
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
        registerView={handleRegisterView}
      />
      <PortableSavePanel projectId={project.id} currentRevision={commands.revision} />
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

              <OpenProjectPanel onOpened={openProject} />

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
                <ImportPanel
                  projectId={view.project.id}
                  hasCanonicalAudio={view.project.canonical_asset_id != null}
                  onImported={loadProjects}
                />
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
