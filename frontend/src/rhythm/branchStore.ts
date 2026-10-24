/**
 * Non-React owner of the active rhythm branch data (M3.17 §19.7).
 *
 * The editor lanes, ruler, inspector, and selection previews read the
 * same fetched grid snapshot instead of each re-fetching and
 * re-deriving mapping state. Loading is keyed by project, range, and
 * detail so redundant requests are coalesced; revisions invalidate the
 * snapshot without guessing at partial updates.
 */

import { fetchRhythmGrid, type RhythmGridData, type RhythmGridDetail } from '../api/rhythm'

export interface RhythmBranchQuery {
  startFrame: number
  endFrame: number
  detail: RhythmGridDetail
}

export interface RhythmBranchSnapshot {
  projectId: string
  queryKey: string
  grid: RhythmGridData | null
}

export type RhythmBranchListener = (snapshot: RhythmBranchSnapshot | null) => void

function queryKey(projectId: string, query: RhythmBranchQuery): string {
  return `${projectId}:${query.startFrame}:${query.endFrame}:${query.detail}`
}

export class RhythmBranchStore {
  private snapshot: RhythmBranchSnapshot | null = null
  private readonly listeners = new Set<RhythmBranchListener>()
  private readonly pending = new Map<string, Promise<RhythmBranchSnapshot>>()

  getSnapshot(): RhythmBranchSnapshot | null {
    return this.snapshot
  }

  subscribe(listener: RhythmBranchListener): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  clear(): void {
    this.snapshot = null
    this.emit()
  }

  /** Drop the snapshot so the next load re-fetches at the current range. */
  invalidate(): void {
    this.clear()
  }

  async load(
    projectId: string,
    query: RhythmBranchQuery,
    signal?: AbortSignal,
  ): Promise<RhythmBranchSnapshot> {
    const key = queryKey(projectId, query)
    if (this.snapshot?.queryKey === key) return this.snapshot
    const inFlight = this.pending.get(key)
    if (inFlight) return inFlight
    const request = fetchRhythmGrid(projectId, query, signal)
      .then((grid) => {
        const next: RhythmBranchSnapshot = { projectId, queryKey: key, grid }
        // A request aborted by a newer range must not publish its result.
        if (signal?.aborted) return next
        this.snapshot = next
        this.emit()
        return next
      })
      .finally(() => {
        this.pending.delete(key)
      })
    this.pending.set(key, request)
    return request
  }

  private emit(): void {
    for (const listener of this.listeners) listener(this.snapshot)
  }
}
