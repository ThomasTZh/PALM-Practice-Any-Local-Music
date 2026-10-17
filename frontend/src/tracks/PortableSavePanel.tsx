/**
 * Portable save panel (M2.15, spec §17.5).
 *
 * Shows the project's portable save state: the saved-through revision
 * and a download button for the latest archive, a note when the working
 * project is newer than the save, and the save button. The save is
 * synchronous (one request, one 201); no polling.
 */
import { useEffect, useState } from 'react'
import {
  downloadPortableSave,
  listPortableSaves,
  savePortableProject,
  type PortableSave,
} from '../api/portable'

export interface PortableSavePanelProps {
  projectId: string
  /** The project's current revision (command pipeline state). */
  currentRevision: number
}

function sizeLabel(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function PortableSavePanel({ projectId, currentRevision }: PortableSavePanelProps) {
  const [latest, setLatest] = useState<PortableSave | null>(null)
  const [saving, setSaving] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The latest saved archive, so the download survives a reload.
  useEffect(() => {
    const ctrl = new AbortController()
    listPortableSaves(projectId, ctrl.signal)
      .then((saves) => setLatest(saves[0] ?? null))
      .catch(() => {})
    return () => ctrl.abort()
  }, [projectId])

  const startSave = async () => {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      setLatest(await savePortableProject(projectId))
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setSaving(false)
    }
  }

  const downloadLatest = async () => {
    if (latest == null || downloading) return
    setDownloading(true)
    setError(null)
    try {
      await downloadPortableSave(latest)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setDownloading(false)
    }
  }

  const hasNewerChanges = latest != null && currentRevision > latest.savedRevision

  return (
    <div className="portable-save-panel">
      <h3 className="portable-save-title">Portable file</h3>
      {latest == null ? (
        <p className="portable-save-state">No portable file saved yet.</p>
      ) : (
        <>
          <p className="portable-save-state">
            Saved through revision {latest.savedRevision} · {sizeLabel(latest.byteSize)}
          </p>
          {hasNewerChanges && (
            <p className="portable-save-stale" role="status">
              Newer unsaved changes (revision {currentRevision}).
            </p>
          )}
        </>
      )}
      <div className="portable-save-actions">
        <button className="mode-btn" disabled={saving} onClick={() => void startSave()}>
          {saving ? 'Saving…' : 'Save portable project'}
        </button>
        {latest != null && (
          <button
            className="mode-btn"
            disabled={downloading || saving}
            onClick={() => void downloadLatest()}
          >
            {downloading ? 'Downloading…' : 'Download'}
          </button>
        )}
      </div>
      {error != null && (
        <p className="portable-save-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
