import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RhythmBranchStore, type RhythmBranchQuery } from '../src/rhythm/branchStore'
import type { RhythmGridData } from '../src/api/rhythm'

const fetchRhythmGrid = vi.fn()

vi.mock('../src/api/rhythm', () => ({
  fetchRhythmGrid: (...args: unknown[]) => fetchRhythmGrid(...args),
}))

const query: RhythmBranchQuery = { startFrame: 0, endFrame: 1000, detail: 'primary' }

describe('RhythmBranchStore', () => {
  beforeEach(() => {
    fetchRhythmGrid.mockReset()
  })

  it('coalesces identical loads and notifies subscribers', async () => {
    const grid = { branch_id: 'branch-1' } as unknown as RhythmGridData
    fetchRhythmGrid.mockResolvedValue(grid)
    const store = new RhythmBranchStore()
    const seen: unknown[] = []
    const unsubscribe = store.subscribe((snapshot) => seen.push(snapshot))

    const [first, second] = await Promise.all([
      store.load('project-1', query),
      store.load('project-1', query),
    ])

    expect(fetchRhythmGrid).toHaveBeenCalledOnce()
    expect(first).toBe(second)
    expect(store.getSnapshot()?.grid).toBe(grid)
    expect(seen).toHaveLength(1)
    unsubscribe()
  })

  it('invalidates a snapshot so a revision change refetches', async () => {
    fetchRhythmGrid
      .mockResolvedValueOnce({ branch_id: 'old' } as unknown as RhythmGridData)
      .mockResolvedValueOnce({ branch_id: 'new' } as unknown as RhythmGridData)
    const store = new RhythmBranchStore()

    await store.load('project-1', query)
    store.invalidate()
    expect(store.getSnapshot()).toBeNull()
    const next = await store.load('project-1', query)

    expect(fetchRhythmGrid).toHaveBeenCalledTimes(2)
    expect((next.grid as { branch_id?: string } | null)?.branch_id).toBe('new')
  })

  it('does not publish an aborted request result', async () => {
    const controller = new AbortController()
    fetchRhythmGrid.mockImplementation(async () => {
      controller.abort()
      return { branch_id: 'aborted' } as unknown as RhythmGridData
    })
    const store = new RhythmBranchStore()

    const snapshot = await store.load('project-1', query, controller.signal)

    expect(snapshot.grid).not.toBeNull()
    expect(store.getSnapshot()).toBeNull()
  })
})
