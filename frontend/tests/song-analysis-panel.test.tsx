import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SongAnalysisPanel } from '../src/rhythm/SongAnalysisPanel'

const analyzeWithVamp = vi.fn()

vi.mock('../src/api/vamp', () => ({
  analyzeWithVamp: (...args: unknown[]) => analyzeWithVamp(...args),
}))

describe('SongAnalysisPanel', () => {
  beforeEach(() => {
    analyzeWithVamp.mockReset()
  })

  it('analyzes with the selected bpb and refreshes the project', async () => {
    analyzeWithVamp.mockResolvedValue({
      branchId: 'branch-1',
      beats: 45,
      bars: 11,
      cached: false,
      pluginKey: 'qm-vamp-plugins:qm-barbeattracker',
      pluginVersion: '3',
      bpb: 4,
    })
    const refresh = vi.fn().mockResolvedValue(undefined)
    render(<SongAnalysisPanel projectId="project-1" refresh={refresh} />)

    await userEvent.selectOptions(screen.getByLabelText('Beats per bar'), '4')
    await userEvent.click(screen.getByRole('button', { name: 'Analyze rhythm' }))

    await waitFor(() => expect(refresh).toHaveBeenCalledOnce())
    expect(analyzeWithVamp).toHaveBeenCalledWith('project-1', 4)
    expect(screen.getByRole('status').textContent).toContain('45 beats')
  })

  it('reports an analysis error', async () => {
    analyzeWithVamp.mockRejectedValue(new Error('Vamp host not found'))
    render(<SongAnalysisPanel projectId="project-1" refresh={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: 'Analyze rhythm' }))

    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain('Vamp host not found'),
    )
    expect(screen.getByRole('button', { name: 'Analyze rhythm' })).toBeEnabled()
  })
})
