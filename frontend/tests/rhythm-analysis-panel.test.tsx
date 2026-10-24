import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RhythmAnalysisPanel } from '../src/rhythm/RhythmAnalysisPanel'

const startRhythmRun = vi.fn()
const getRhythmRun = vi.fn()

vi.mock('../src/api/rhythm', () => ({
  startRhythmRun: (...args: unknown[]) => startRhythmRun(...args),
  getRhythmRun: (...args: unknown[]) => getRhythmRun(...args),
}))

const running = {
  id: 'run-1',
  status: 'running',
  warnings: [],
} as never
const completed = {
  id: 'run-1',
  status: 'completed',
  warnings: [],
  decoded_result_id: 'result-1',
} as never

describe('RhythmAnalysisPanel', () => {
  beforeEach(() => {
    startRhythmRun.mockReset()
    getRhythmRun.mockReset()
  })

  it('starts a run, polls to completion, and refreshes the project', async () => {
    startRhythmRun.mockResolvedValue(running)
    getRhythmRun.mockResolvedValue(completed)
    const refresh = vi.fn().mockResolvedValue(undefined)
    render(<RhythmAnalysisPanel projectId="project-1" refresh={refresh} />)

    await userEvent.click(screen.getByRole('button', { name: 'Analyze rhythm' }))

    await waitFor(() => expect(refresh).toHaveBeenCalledOnce())
    expect(startRhythmRun).toHaveBeenCalledWith('project-1', { force_rerun: false })
    expect(getRhythmRun).toHaveBeenCalledWith('project-1', 'run-1')
    expect(screen.getByRole('status').textContent).toContain('completed')
  })

  it('keeps polling while activation is complete but the grid is not', async () => {
    startRhythmRun.mockResolvedValue(running)
    getRhythmRun
      .mockResolvedValueOnce({
        id: 'run-1',
        status: 'completed',
        decoded_result_id: null,
        warnings: [],
      } as never)
      .mockResolvedValue(completed)
    const refresh = vi.fn().mockResolvedValue(undefined)
    render(<RhythmAnalysisPanel projectId="project-1" refresh={refresh} />)

    await userEvent.click(screen.getByRole('button', { name: 'Analyze rhythm' }))

    await waitFor(() => expect(refresh).toHaveBeenCalledOnce(), { timeout: 4000 })
    expect(getRhythmRun).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('status').textContent).toContain('completed')
  })

  it('reports a failed run warning', async () => {
    startRhythmRun.mockResolvedValue(running)
    getRhythmRun.mockResolvedValue({
      id: 'run-1',
      status: 'failed',
      warnings: ['model unavailable'],
    } as never)
    render(<RhythmAnalysisPanel projectId="project-1" refresh={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: 'Analyze rhythm' }))

    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain('model unavailable'),
    )
  })
})
