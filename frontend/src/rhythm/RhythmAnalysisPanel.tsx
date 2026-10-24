/**
 * Analyze Rhythm trigger (M3.17 §19.2-§19.3).
 *
 * Starts the durable rhythm run, polls its status, and refreshes the
 * project snapshot once the automatic branch is active so the ruler and
 * lanes appear without a manual reload.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { getRhythmRun, startRhythmRun, type RhythmRunSummary } from '../api/rhythm'

const POLL_MS = 1000

export interface RhythmAnalysisPanelProps {
  projectId: string
  refresh: () => Promise<void>
}

export function RhythmAnalysisPanel({ projectId, refresh }: RhythmAnalysisPanelProps) {
  const [run, setRun] = useState<RhythmRunSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef<number | null>(null)

  const stopTimer = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current)
      timer.current = null
    }
  }, [])

  useEffect(() => stopTimer, [projectId, stopTimer])

  const poll = useCallback(
    (runId: string) => {
      const tick = async () => {
        try {
          const next = await getRhythmRun(projectId, runId)
          setRun(next)
          // Activation completes before decode/tempo/meter/branch
          // publication; only a decoded result means the grid is ready.
          if (next.status === 'completed' && next.decoded_result_id) {
            setBusy(false)
            await refresh()
            return
          }
          if (
            next.status === 'failed' ||
            next.status === 'cancelled' ||
            next.status === 'interrupted'
          ) {
            setBusy(false)
            setError(next.warnings[0] ?? `Rhythm analysis ${next.status}`)
            return
          }
          timer.current = window.setTimeout(() => void tick(), POLL_MS)
        } catch (caught) {
          setBusy(false)
          setError(caught instanceof Error ? caught.message : 'Rhythm analysis status failed')
        }
      }
      void tick()
    },
    [projectId, refresh],
  )

  const start = useCallback(
    async (force = false) => {
      setBusy(true)
      setError(null)
      setRun(null)
      try {
        const started = await startRhythmRun(projectId, { force_rerun: force })
        setRun(started)
        poll(started.id)
      } catch (caught) {
        setBusy(false)
        setError(caught instanceof Error ? caught.message : 'Rhythm analysis could not start')
      }
    },
    [poll, projectId],
  )

  const status =
    run?.status === 'completed' && !run.decoded_result_id ? 'finalizing' : (run?.status ?? 'idle')
  return (
    <section className="rhythm-analysis" aria-label="Rhythm analysis">
      <h2>Musical analysis</h2>
      <button type="button" onClick={() => void start(false)} disabled={busy}>
        Analyze rhythm
      </button>
      <button type="button" onClick={() => void start(true)} disabled={busy}>
        Re-analyze
      </button>
      <p className="rhythm-analysis-hint muted">
        Re-analyze rebuilds the tempo/meter grid after an algorithm fix.
      </p>
      <p className="rhythm-analysis-status" role="status">
        {status === 'idle' ? 'No automatic analysis started' : `Status: ${status}`}
      </p>
      {error ? (
        <p className="rhythm-analysis-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  )
}
