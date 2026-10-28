/**
 * Start stem separation and activate the completed result set.
 *
 * Demucs runs through the existing analysis worker and durable job. On
 * completion the newest result set is selected so TrackStack can render the
 * mixer lanes without a reload.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchResultSets } from '../api/result-sets'
import { getMediaJob, startSeparation, type MediaJob } from '../api/separation'

const POLL_MS = 1000

export interface StemSeparationPanelProps {
  projectId: string
  onActivate: (resultSetId: string) => void
}

export function StemSeparationPanel({ projectId, onActivate }: StemSeparationPanelProps) {
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState<MediaJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [resultCount, setResultCount] = useState(0)
  const timer = useRef<number | null>(null)

  const stopTimer = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current)
      timer.current = null
    }
  }, [])

  useEffect(() => {
    const ctrl = new AbortController()
    fetchResultSets(projectId, ctrl.signal)
      .then((sets) => setResultCount(sets.filter((set) => set.validationStatus === 'valid').length))
      .catch(() => setResultCount(0))
    return () => {
      ctrl.abort()
      stopTimer()
    }
  }, [projectId, stopTimer])

  const finish = useCallback(async () => {
    const sets = await fetchResultSets(projectId)
    const valid = sets.filter((set) => set.validationStatus === 'valid')
    setResultCount(valid.length)
    const newest = valid.at(-1)
    if (!newest) throw new Error('separation completed without a valid result set')
    onActivate(newest.id)
    setBusy(false)
    setJob(null)
  }, [onActivate, projectId])

  const poll = useCallback(
    (jobId: string) => {
      const tick = async () => {
        try {
          const next = await getMediaJob(jobId)
          setJob(next)
          if (next.state === 'completed') {
            await finish()
            return
          }
          if (['failed', 'cancelled', 'interrupted'].includes(next.state)) {
            setBusy(false)
            setError(next.error ?? `Separation ${next.state}`)
            return
          }
          timer.current = window.setTimeout(() => void tick(), POLL_MS)
        } catch (caught) {
          setBusy(false)
          setError(caught instanceof Error ? caught.message : 'Separation status failed')
        }
      }
      void tick()
    },
    [finish],
  )

  const start = useCallback(async () => {
    setBusy(true)
    setError(null)
    setJob(null)
    try {
      const run = await startSeparation(projectId)
      if (run.resultSetId) {
        onActivate(run.resultSetId)
        setBusy(false)
        return
      }
      if (!run.jobId) throw new Error('separation did not return a job')
      poll(run.jobId)
    } catch (caught) {
      setBusy(false)
      setError(caught instanceof Error ? caught.message : 'Separation could not start')
    }
  }, [onActivate, poll, projectId])

  const progress = job?.progress_fraction ?? null
  return (
    <section className="separation-panel" aria-label="Stem separation">
      <h2>Stems</h2>
      <button type="button" onClick={() => void start()} disabled={busy}>
        Separate stems
      </button>
      <p className="separation-status" role="status">
        {busy
          ? job
            ? `Separating: ${job.stage ?? job.state}${
                progress !== null ? ` (${Math.round(progress * 100)}%)` : ''
              }`
            : 'Starting separation'
          : resultCount > 0
            ? `${resultCount} stem result set${resultCount === 1 ? '' : 's'} available`
            : 'No stems yet'}
      </p>
      {error ? (
        <p className="separation-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  )
}
