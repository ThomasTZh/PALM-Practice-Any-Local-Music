/**
 * Export panel (M2.13, spec §15).
 *
 * Inline in the track mode bar: stem checkboxes, format and rate
 * selects, linked peak normalization, the export button with job
 * progress, and the delivered artifacts with their download buttons.
 * Exports are raw — the monitoring state never affects the files.
 */
import { useEffect, useState } from 'react'
import {
  createExport,
  downloadExport,
  listExports,
  type ExportArtifact,
  type ExportFormat,
  type ExportNormalization,
} from '../api/exports'
import { waitForJob, type JobState } from '../api/playback'
import type { ResultSetDetail } from '../api/result-sets'

export interface ExportPanelProps {
  projectId: string
  /** The active set's detail (stems + provenance); null when none. */
  detail: ResultSetDetail | null
}

type ExportSampleRate = 44100 | 48000 | null

const STAGE_LABELS: Record<string, string> = {
  verifying_stems: 'Verifying stems…',
  encoding: 'Encoding…',
  verifying_export: 'Verifying export…',
}

function stageLabel(job: JobState): string {
  if (job.stage && STAGE_LABELS[job.stage]) return STAGE_LABELS[job.stage]
  if (job.state === 'queued') return 'Queued…'
  return 'Working…'
}

function formatLabel(format: ExportFormat): string {
  if (format === 'wav16') return '16-bit'
  if (format === 'wav32f') return '32-bit float'
  return '24-bit'
}

function sizeLabel(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function ExportPanel({ projectId, detail }: ExportPanelProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [format, setFormat] = useState<ExportFormat>('wav24')
  const [sampleRate, setSampleRate] = useState<ExportSampleRate>(null)
  const [normalize, setNormalize] = useState<ExportNormalization>('off')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<JobState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [artifacts, setArtifacts] = useState<ExportArtifact[] | null>(null)
  const [downloadingId, setDownloadingId] = useState<string | null>(null)

  // A new set re-selects all of its stems (the spec default, §15.1).
  useEffect(() => {
    setSelected(new Set((detail?.stems ?? []).map((s) => s.audioAssetId)))
    setArtifacts(null)
    setError(null)
  }, [detail?.id])

  // Delivered artifacts, so completed exports stay re-downloadable.
  useEffect(() => {
    const ctrl = new AbortController()
    listExports(projectId, ctrl.signal)
      .then(setArtifacts)
      .catch(() => {})
    return () => ctrl.abort()
  }, [projectId])

  const toggleStem = (assetId: string, on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (on) next.add(assetId)
      else next.delete(assetId)
      return next
    })
  }

  const startExport = async () => {
    if (!detail || selected.size === 0 || busy) return
    setBusy(true)
    setError(null)
    setProgress(null)
    try {
      const job = await createExport(projectId, {
        resultSetId: detail.id,
        assetIds: [...selected],
        format,
        sampleRate,
        normalize,
      })
      setProgress(job)
      await waitForJob(job.id, {
        timeoutMs: 10 * 60_000,
        onProgress: setProgress,
      })
      setArtifacts(await listExports(projectId))
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
      setProgress(null)
    }
  }

  const downloadOne = async (artifact: ExportArtifact) => {
    if (downloadingId) return
    setDownloadingId(artifact.artifactId)
    setError(null)
    try {
      await downloadExport(artifact)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setDownloadingId(null)
    }
  }

  const pct =
    progress?.progressFraction != null ? ` ${Math.round(progress.progressFraction * 100)}%` : ''
  const canExport = !busy && detail != null && selected.size > 0

  return (
    <details className="export-panel">
      <summary className="export-summary">Export</summary>
      <div className="export-body">
        {detail == null ? (
          <p className="export-empty">Select a separation result set to export its stems.</p>
        ) : (
          <>
            <div className="export-stems" role="group" aria-label="Stems to export">
              {detail.stems.map((stem) => (
                <label key={stem.id} className="export-stem">
                  <input
                    type="checkbox"
                    checked={selected.has(stem.audioAssetId)}
                    disabled={busy}
                    onChange={(e) => toggleStem(stem.audioAssetId, e.target.checked)}
                  />
                  <span>{stem.displayName}</span>
                </label>
              ))}
            </div>
            <div className="export-options">
              <label className="mixer-field">
                <span className="mixer-field-label">Format</span>
                <select
                  className="mode-set-select"
                  value={format}
                  disabled={busy}
                  onChange={(e) => setFormat(e.target.value as ExportFormat)}
                >
                  <option value="wav16">16-bit WAV</option>
                  <option value="wav24">24-bit WAV</option>
                  <option value="wav32f">32-bit float WAV</option>
                </select>
              </label>
              <label className="mixer-field">
                <span className="mixer-field-label">Rate</span>
                <select
                  className="mode-set-select"
                  value={sampleRate == null ? '' : String(sampleRate)}
                  disabled={busy}
                  onChange={(e) =>
                    setSampleRate(
                      e.target.value === '' ? null : (Number(e.target.value) as 44100 | 48000),
                    )
                  }
                >
                  <option value="">Source rate</option>
                  <option value="44100">44.1 kHz</option>
                  <option value="48000">48 kHz</option>
                </select>
              </label>
              <label className="mixer-field mixer-field-inline">
                <input
                  type="checkbox"
                  className="monitoring-limiter"
                  checked={normalize === 'linked_peak'}
                  disabled={busy}
                  onChange={(e) => setNormalize(e.target.checked ? 'linked_peak' : 'off')}
                />
                <span>Normalize to −1 dBFS</span>
              </label>
            </div>
            <div className="export-actions">
              <button className="mode-btn" disabled={!canExport} onClick={() => void startExport()}>
                {busy ? `Exporting${pct}…` : 'Export WAV'}
              </button>
              {busy && progress != null && (
                <span className="export-progress" role="status">
                  {stageLabel(progress)}
                </span>
              )}
            </div>
            {error != null && (
              <p className="export-error" role="alert">
                {error}
              </p>
            )}
            {artifacts != null && artifacts.length > 0 && (
              <ul className="export-artifacts">
                {artifacts.map((artifact) => (
                  <li key={artifact.artifactId} className="export-artifact">
                    <span className="export-artifact-name">{artifact.downloadFilename}</span>
                    <span className="export-artifact-meta">
                      {formatLabel(artifact.format)} · {artifact.sampleRate / 1000} kHz ·{' '}
                      {sizeLabel(artifact.byteSize)}
                      {artifact.normalized && artifact.gainDb != null
                        ? ` · +${artifact.gainDb.toFixed(1)} dB`
                        : ''}
                    </span>
                    <button
                      className="mode-btn"
                      disabled={downloadingId != null}
                      onClick={() => void downloadOne(artifact)}
                    >
                      {downloadingId === artifact.artifactId ? 'Downloading…' : 'Download'}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </details>
  )
}
