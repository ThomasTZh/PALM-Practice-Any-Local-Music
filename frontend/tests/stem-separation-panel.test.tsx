import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { StemSeparationPanel } from '../src/tracks/StemSeparationPanel'

const startSeparation = vi.fn()
const getMediaJob = vi.fn()
const fetchResultSets = vi.fn()

vi.mock('../src/api/separation', () => ({
  startSeparation: (...args: unknown[]) => startSeparation(...args),
  getMediaJob: (...args: unknown[]) => getMediaJob(...args),
}))

vi.mock('../src/api/result-sets', () => ({
  fetchResultSets: (...args: unknown[]) => fetchResultSets(...args),
}))

describe('StemSeparationPanel', () => {
  beforeEach(() => {
    startSeparation.mockReset()
    getMediaJob.mockReset()
    fetchResultSets.mockReset()
  })

  it('activates a cached result set immediately', async () => {
    fetchResultSets.mockResolvedValue([])
    startSeparation.mockResolvedValue({
      runId: 'run-1',
      jobId: null,
      resultSetId: 'set-1',
      cached: true,
    })
    const onActivate = vi.fn()
    render(<StemSeparationPanel projectId="project-1" onActivate={onActivate} />)

    await userEvent.click(screen.getByRole('button', { name: 'Separate stems' }))

    await waitFor(() => expect(onActivate).toHaveBeenCalledWith('set-1'))
    expect(startSeparation).toHaveBeenCalledWith('project-1')
  })

  it('polls the job and activates the newest valid result set', async () => {
    fetchResultSets.mockResolvedValueOnce([]).mockResolvedValueOnce([
      {
        id: 'set-0',
        createdAt: '2026-10-25T00:00:00Z',
        validationStatus: 'invalid',
        availableStemRoles: [],
      },
      {
        id: 'set-1',
        createdAt: '2026-10-25T00:01:00Z',
        validationStatus: 'valid',
        availableStemRoles: ['bass'],
      },
    ])
    startSeparation.mockResolvedValue({
      runId: 'run-1',
      jobId: 'job-1',
      resultSetId: null,
      cached: false,
    })
    getMediaJob.mockResolvedValue({
      id: 'job-1',
      state: 'completed',
      stage: 'ready',
      progress_fraction: 1,
      error: null,
    })
    const onActivate = vi.fn()
    render(<StemSeparationPanel projectId="project-1" onActivate={onActivate} />)

    await userEvent.click(screen.getByRole('button', { name: 'Separate stems' }))

    await waitFor(() => expect(onActivate).toHaveBeenCalledWith('set-1'))
    expect(getMediaJob).toHaveBeenCalledWith('job-1')
  })
})
