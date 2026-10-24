/** Auto-result/edited-branch selector (M3.17 §19.4/§19.6). */

import { useEffect, useState } from 'react'

import {
  listRhythmBranches,
  listRhythmResults,
  type RhythmBranchSummary,
  type RhythmResultSummary,
} from '../api/rhythm'

export interface RhythmVersionSelectorProps {
  projectId: string
  activeResultId: string | null
  activeBranchId: string | null
  refreshKey?: number
  onSelectResult: (id: string | null) => void
  onSelectBranch: (id: string | null) => void
}

export function RhythmVersionSelector({
  projectId,
  activeResultId,
  activeBranchId,
  refreshKey = 0,
  onSelectResult,
  onSelectBranch,
}: RhythmVersionSelectorProps) {
  const [results, setResults] = useState<RhythmResultSummary[]>([])
  const [branches, setBranches] = useState<RhythmBranchSummary[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      listRhythmResults(projectId, controller.signal),
      listRhythmBranches(projectId, controller.signal),
    ])
      .then(([nextResults, nextBranches]) => {
        setResults(nextResults)
        setBranches(nextBranches)
        setError(null)
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : 'Rhythm versions unavailable')
        }
      })
    return () => controller.abort()
  }, [projectId, refreshKey])

  return (
    <div className="rhythm-version-selector" aria-label="Rhythm version selector">
      <label>
        Automatic
        <select
          aria-label="Active automatic rhythm result"
          value={activeResultId ?? ''}
          onChange={(event) => onSelectResult(event.target.value || null)}
        >
          <option value="">None</option>
          {results.map((result) => (
            <option key={result.id} value={result.id}>
              {new Date(result.created_at).toLocaleString()} · {result.accepted_count} pulses
            </option>
          ))}
        </select>
      </label>
      <label>
        Edited
        <select
          aria-label="Active editable rhythm branch"
          value={activeBranchId ?? ''}
          onChange={(event) => onSelectBranch(event.target.value || null)}
        >
          <option value="">None</option>
          {branches.map((branch) => (
            <option key={branch.id} value={branch.id}>
              r{branch.revision} · {branch.grid_validity} · {branch.pulse_count} pulses
            </option>
          ))}
        </select>
      </label>
      {error ? <span role="status">{error}</span> : null}
    </div>
  )
}
