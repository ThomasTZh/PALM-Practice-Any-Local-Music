/**
 * Song analysis trigger for the local Vamp grid.
 *
 * The endpoint is synchronous from the browser's point of view: it returns
 * once the cached/real analysis has published a branch and the project
 * snapshot has been refreshed.
 */

import { useCallback, useState } from 'react'

import { analyzeWithVamp, type VampAnalysisResult } from '../api/vamp'

export interface SongAnalysisPanelProps {
  projectId: string
  refresh: () => Promise<void>
}

const BPB_OPTIONS = [2, 3, 4, 6, 7] as const

export function SongAnalysisPanel({ projectId, refresh }: SongAnalysisPanelProps) {
  const [bpb, setBpb] = useState(4)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<VampAnalysisResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const analyze = useCallback(async () => {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const analysis = await analyzeWithVamp(projectId, bpb)
      setResult(analysis)
      await refresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Vamp analysis could not start')
    } finally {
      setBusy(false)
    }
  }, [bpb, projectId, refresh])

  return (
    <section className="rhythm-analysis" aria-label="Musical analysis">
      <h2>Musical analysis</h2>
      <label className="rhythm-analysis-bpb">
        Beats per bar
        <select
          aria-label="Beats per bar"
          value={bpb}
          onChange={(event) => setBpb(Number(event.target.value))}
          disabled={busy}
        >
          {BPB_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      <button type="button" onClick={() => void analyze()} disabled={busy}>
        Analyze rhythm
      </button>
      <button type="button" onClick={() => void analyze()} disabled={busy}>
        Re-analyze
      </button>
      <p className="rhythm-analysis-hint muted">
        Local Vamp QM bar and beat tracker. Re-analyze rebuilds the grid from the source.
      </p>
      <p className="rhythm-analysis-status" role="status">
        {busy
          ? 'Status: analyzing'
          : result
            ? `Status: completed (${result.beats} beats, ${result.bars} bars${result.cached ? ', cached' : ''})`
            : 'No analysis yet'}
      </p>
      {error ? (
        <p className="rhythm-analysis-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  )
}
