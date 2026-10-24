import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchRhythmGrid, type RhythmGridData } from '../src/api/rhythm'
import { RhythmLanes } from '../src/rhythm/RhythmLanes'
import type { ViewSource } from '../src/waveform/WaveformEditor'

vi.mock('../src/api/rhythm', () => ({
  fetchRhythmGrid: vi.fn(),
}))

const fetchMock = vi.mocked(fetchRhythmGrid)

function grid(): RhythmGridData {
  return {
    project_id: 'project-1',
    revision: 6,
    branch_id: 'branch-1',
    branch_revision: 4,
    branch_validity: 'valid',
    source_sample_rate: 48_000,
    source_duration_frames: 240_000,
    tempo_anchors: [
      {
        id: 'a1',
        branch_id: 'branch-1',
        source_frame: 0,
        musical_position: { numerator: 0, denominator: 1 },
        origin: 'manual',
        lock_state: 'unlocked',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'a2',
        branch_id: 'branch-1',
        source_frame: 48_000,
        musical_position: { numerator: 2, denominator: 1 },
        origin: 'manual',
        lock_state: 'unlocked',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ],
    meter_regions: [
      {
        id: 'm1',
        branch_id: 'branch-1',
        start: { numerator: 0, denominator: 1 },
        numerator: 4,
        denominator: 4,
        grouping: [1, 1, 1, 1],
        display_tempo_unit: 'quarter',
        origin: 'manual',
        grid_validity: 'valid',
      },
    ],
    bar_origin: {
      first_numbered_bar_position: { numerator: 0, denominator: 1 },
      first_bar_number: 1,
    },
    pulses: [
      {
        id: 'p1',
        parent_id: 'branch-1',
        source_frame: 0,
        role: 'downbeat',
        acceptance: 'accepted',
        confidence: { kind: 'heuristic', value: 0.9, calibrated: false },
        origin: 'manual',
        review_state: 'unreviewed',
      },
      {
        id: 'p2',
        parent_id: 'branch-1',
        source_frame: 24_000,
        role: 'beat',
        acceptance: 'candidate',
        confidence: { kind: 'heuristic', value: 0.4, calibrated: false },
        origin: 'manual',
        review_state: 'unreviewed',
      },
    ],
    grid: {
      detail: 'primary',
      start: { numerator: 0, denominator: 1 },
      end: { numerator: 4, denominator: 1 },
      events: [
        {
          kind: 'bar',
          label: '1',
          musical_position: { numerator: 0, denominator: 1 },
          source_frame: 0,
          source_fraction: { numerator: 0, denominator: 1 },
          pickup: false,
        },
        {
          kind: 'primary',
          label: '1.1',
          musical_position: { numerator: 0, denominator: 1 },
          source_frame: 0,
          source_fraction: { numerator: 0, denominator: 1 },
          pickup: false,
        },
        {
          kind: 'primary',
          label: '1.2',
          musical_position: { numerator: 1, denominator: 1 },
          source_frame: 24_000,
          source_fraction: { numerator: 24_000, denominator: 1 },
          pickup: false,
        },
      ],
      gaps: [],
      unmapped_gap_detected: false,
      created_at: '2026-01-01T00:00:00Z',
    },
  } as unknown as RhythmGridData
}

function viewSource(): ViewSource {
  return {
    get: () => ({ startFrame: 0, fpp: 240, widthCssPx: 600 }),
  }
}

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockResolvedValue(grid())
})

describe('rhythm lanes (M3.11)', () => {
  it('renders bar/meter/pulse layers and fetches the visible grid', async () => {
    const { container } = render(<RhythmLanes projectId="project-1" viewSource={viewSource()} />)
    await waitFor(() => expect(screen.getByText('4/4 (1+1+1+1)')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalled()
    const request = fetchMock.mock.calls[0][1]
    expect(request.startFrame).toBeLessThanOrEqual(0)
    expect(request.endFrame).toBeGreaterThan(600 * 240)
    expect(container.querySelectorAll('.rhythm-pulse')).toHaveLength(2)
    expect(container.querySelectorAll('.rhythm-anchor')).toHaveLength(2)
    expect(container.querySelector('.rhythm-anchor.locked')).toBeNull()
  })

  it('seeks from a ruler click using source-frame mapping', async () => {
    const onSeek = vi.fn()
    const { container } = render(
      <RhythmLanes projectId="project-1" viewSource={viewSource()} onSeek={onSeek} />,
    )
    await waitFor(() => expect(screen.getByText('4/4 (1+1+1+1)')).toBeInTheDocument())
    const lanes = container.querySelector('.rhythm-lanes') as HTMLElement
    fireEvent.click(lanes, { clientX: 240 })
    expect(onSeek).toHaveBeenCalledWith(57600)
  })

  it('opens an inspector for a selected pulse or meter', async () => {
    const { container } = render(<RhythmLanes projectId="project-1" viewSource={viewSource()} />)
    await waitFor(() => expect(screen.getByText('4/4 (1+1+1+1)')).toBeInTheDocument())
    fireEvent.click(container.querySelectorAll('.rhythm-pulse')[1])
    expect(await screen.findByText('Beat pulse')).toBeInTheDocument()
    expect(screen.getByText(/review unreviewed/)).toBeInTheDocument()
    fireEvent.click(container.querySelector('.rhythm-meter-label') as HTMLElement)
    expect(await screen.findByText(/grouping 1\+1\+1\+1/)).toBeInTheDocument()
  })

  it('aligns the playhead to the shared source-frame viewport', async () => {
    const { container } = render(
      <RhythmLanes
        projectId="project-1"
        viewSource={viewSource()}
        playheadSource={{ getPosition: () => 48_000, isPlaying: () => true }}
      />,
    )
    await waitFor(() => expect(screen.getByText('4/4 (1+1+1+1)')).toBeInTheDocument())
    const playhead = container.querySelector('.rhythm-playhead') as HTMLElement
    await waitFor(() => expect(playhead.style.transform).toBe('translateX(200px)'))
  })

  it('requests coarser detail when zoomed out', async () => {
    const zoomedOut: ViewSource = {
      get: () => ({ startFrame: 0, fpp: 6, widthCssPx: 600 }),
    }
    render(<RhythmLanes projectId="project-1" viewSource={zoomedOut} />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(fetchMock.mock.calls[0][1].detail).toBe('quarter_beat')
  })

  it('highlights bars intersecting the waveform selection', async () => {
    const { container } = render(
      <RhythmLanes
        projectId="project-1"
        viewSource={viewSource()}
        selection={{ start: 0, end: 30_000 }}
      />,
    )
    await waitFor(() => expect(screen.getByText('4/4 (1+1+1+1)')).toBeInTheDocument())
    expect(container.querySelectorAll('.rhythm-selection-bar').length).toBeGreaterThan(0)
  })

  it('shows a no-grid state when the API has no active branch', async () => {
    fetchMock.mockResolvedValue(null)
    render(<RhythmLanes projectId="project-1" viewSource={viewSource()} />)
    await waitFor(() =>
      expect(screen.getByText('No rhythm grid for this project')).toBeInTheDocument(),
    )
  })
})
