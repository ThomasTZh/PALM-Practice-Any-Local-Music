/**
 * Open a portable project (M2.16, spec §18.1).
 *
 * The entry point on a clean installation: a `.basseparate` file can be
 * picked or dropped here from the project list. The panel streams the
 * archive with progress, shows an "Opening…" phase while the server
 * validates and imports it, and reports failures inline (damaged or
 * incomplete archives, version mismatches, ID conflicts, disk space).
 * On success it hands the new project id to the caller, which opens it.
 */

import { useCallback, useRef, useState } from 'react'

import { cancelOpenSession, describeOpenError, uploadArchive, type OpenProgress } from '../api/open'

const ARCHIVE_SUFFIX = '.basseparate'

type PanelState =
  | { kind: 'idle' }
  | { kind: 'uploading'; filename: string; progress: OpenProgress }
  | { kind: 'opening'; filename: string }
  | { kind: 'error'; message: string }

export function OpenProjectPanel({ onOpened }: { onOpened: (projectId: string) => void }) {
  const [state, setState] = useState<PanelState>({ kind: 'idle' })
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const sessionRef = useRef<string | null>(null)

  const start = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(ARCHIVE_SUFFIX)) {
        setState({ kind: 'error', message: 'Choose a .basseparate project file.' })
        return
      }
      const controller = new AbortController()
      abortRef.current = controller
      sessionRef.current = null
      setState({
        kind: 'uploading',
        filename: file.name,
        progress: { bytesUploaded: 0, totalBytes: file.size },
      })
      try {
        const project = await uploadArchive({
          file,
          signal: controller.signal,
          onSession: (sessionId) => {
            sessionRef.current = sessionId
          },
          onProgress: (progress) => setState({ kind: 'uploading', filename: file.name, progress }),
          onOpening: () => setState({ kind: 'opening', filename: file.name }),
        })
        setState({ kind: 'idle' })
        onOpened(project.projectId)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          setState({ kind: 'idle' })
          return
        }
        setState({ kind: 'error', message: describeOpenError(err) })
      } finally {
        abortRef.current = null
        sessionRef.current = null
      }
    },
    [onOpened],
  )

  const handleCancel = useCallback(() => {
    abortRef.current?.abort()
    const sessionId = sessionRef.current
    if (sessionId) {
      // Best effort: the server removes only this session's files.
      void cancelOpenSession(sessionId).catch(() => undefined)
    }
    setState({ kind: 'idle' })
  }, [])

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0]
      if (file) void start(file)
    },
    [start],
  )

  const busy = state.kind === 'uploading' || state.kind === 'opening'
  const percent =
    state.kind === 'uploading' && state.progress.totalBytes > 0
      ? Math.round((state.progress.bytesUploaded / state.progress.totalBytes) * 100)
      : 0

  return (
    <div className="import-panel open-panel" aria-label="Open a portable project">
      <div className="list-header">
        <h2>Open a portable project</h2>
      </div>

      {state.kind === 'error' && (
        <div className="import-error" role="alert">
          <p>Could not open the project: {state.message}</p>
          <button type="button" onClick={() => setState({ kind: 'idle' })}>
            Try again
          </button>
        </div>
      )}

      {!busy && state.kind !== 'error' && (
        <div
          className={`import-dropzone ${dragOver ? 'drag-over' : ''}`}
          onDragOver={(event) => {
            event.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragOver(false)
            handleFiles(event.dataTransfer.files)
          }}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              inputRef.current?.click()
            }
          }}
          onClick={() => inputRef.current?.click()}
          aria-label="Drop a project archive here or click to browse"
        >
          <p>Drop a .basseparate project file here</p>
          <p className="muted">or click to browse</p>
          <input
            ref={inputRef}
            type="file"
            accept={ARCHIVE_SUFFIX}
            aria-label="Project archive file"
            style={{ display: 'none' }}
            onChange={(event) => {
              handleFiles(event.target.files)
              event.target.value = ''
            }}
          />
        </div>
      )}

      {busy && (
        <div className="import-progress" role="status" aria-live="polite">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${percent}%` }} />
          </div>
          <p>
            {state.kind === 'opening'
              ? `Opening ${state.filename}…`
              : `Uploading ${state.filename}… ${percent}%`}
          </p>
          <button type="button" onClick={handleCancel}>
            Cancel
          </button>
        </div>
      )}
    </div>
  )
}
