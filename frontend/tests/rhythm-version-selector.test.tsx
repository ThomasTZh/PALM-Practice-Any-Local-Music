import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listRhythmBranches, listRhythmResults } from '../src/api/rhythm'
import { RhythmVersionSelector } from '../src/rhythm/RhythmVersionSelector'

vi.mock('../src/api/rhythm', () => ({
  listRhythmResults: vi.fn(),
  listRhythmBranches: vi.fn(),
}))
const resultsMock = vi.mocked(listRhythmResults)
const branchesMock = vi.mocked(listRhythmBranches)

beforeEach(() => {
  resultsMock.mockResolvedValue([
    {
      id: 'result-1',
      run_id: 'run-1',
      activation_artifact_id: 'artifact-1',
      stage: 'decoded',
      status: 'decoded',
      decoder_profile_id: 'beat-this-minimal-v1',
      accepted_count: 11,
      candidate_count: 0,
      created_at: '2026-01-01T00:00:00Z',
    },
  ])
  branchesMock.mockResolvedValue([
    {
      id: 'branch-1',
      revision: 3,
      parent_automatic_result_id: 'result-1',
      grid_validity: 'valid',
      pulse_count: 11,
      tempo_anchor_count: 11,
      meter_region_count: 1,
      updated_at: '2026-01-01T00:00:00Z',
    },
  ])
})

describe('RhythmVersionSelector (M3.17)', () => {
  it('lists automatic results and editable branches', async () => {
    render(
      <RhythmVersionSelector
        projectId="project-1"
        activeResultId={null}
        activeBranchId={null}
        onSelectResult={vi.fn()}
        onSelectBranch={vi.fn()}
      />,
    )
    await waitFor(() =>
      expect(screen.getAllByRole('option', { name: /11 pulses/ }).length).toBeGreaterThan(0),
    )
    expect(screen.getByRole('option', { name: /r3 · valid · 11 pulses/ })).toBeInTheDocument()
  })
})
