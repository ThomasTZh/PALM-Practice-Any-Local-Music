import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TrackStack, BASS_PAIR_ROLES, FOUR_STEM_ROLES } from '../src/tracks/TrackStack'
import { MixerStrip } from '../src/tracks/MixerStrip'
import { ModeSelector } from '../src/tracks/ModeSelector'
import { MonitoringPanel } from '../src/tracks/MonitoringPanel'
import { gainToDb, dbToGain, peakToDbFs, balanceLabel } from '../src/tracks/db'
import type { ResultSetDetail, ResultSetSummary } from '../src/api/result-sets'
import type { PracticeState } from '../src/api/commands'
import type { MixPeaks } from '../src/playback/transport'

const { fetchResultSetsMock } = vi.hoisted(() => ({
  fetchResultSetsMock: vi.fn(),
}))

vi.mock('../src/api/result-sets', () => ({
  fetchResultSets: fetchResultSetsMock,
  fetchResultSetDetail: vi.fn(),
}))

const PROJECT_ID = '11111111-1111-1111-1111-111111111111'

const SETS: ResultSetSummary[] = [
  {
    id: 'set-1',
    createdAt: '2026-01-01T00:00:00Z',
    validationStatus: 'valid',
    availableStemRoles: ['vocals', 'drums', 'bass', 'other'],
  },
  {
    id: 'set-2',
    createdAt: '2026-01-02T00:00:00Z',
    validationStatus: 'invalid',
    availableStemRoles: [],
  },
]

const DETAIL: ResultSetDetail = {
  id: 'set-1',
  createdAt: '2026-01-01T00:00:00Z',
  validationStatus: 'valid',
  engineVersion: '2.1.0',
  modelManifestId: 'abcdef1234567890',
  stems: [
    {
      role: 'vocals',
      displayName: 'Vocals',
      assetId: 'asset-voc',
      sampleRate: 48000,
      channelCount: 2,
      frameCount: 48000,
    },
    {
      role: 'drums',
      displayName: 'Drums',
      assetId: 'asset-drum',
      sampleRate: 48000,
      channelCount: 2,
      frameCount: 48000,
    },
    {
      role: 'bass',
      displayName: 'Bass',
      assetId: 'asset-bass',
      sampleRate: 48000,
      channelCount: 2,
      frameCount: 48000,
    },
    {
      role: 'other',
      displayName: 'Other',
      assetId: 'asset-oth',
      sampleRate: 48000,
      channelCount: 2,
      frameCount: 48000,
    },
  ],
}

const PRACTICE_STATE: PracticeState = {
  active_loop_id: null,
  active_result_set_id: 'set-1',
  loop_enabled: false,
  loops: null,
  master_gain: 1.0,
  monitoring_limiter: true,
  playback_mode: 'four_stems',
  playback_speed: 1.0,
  tracks: {
    vocals: {
      gain: 1.0,
      mute: false,
      solo: false,
      balance: 0,
      visible: true,
      display_height: 1.0,
      color: '#e11d48',
    },
    drums: {
      gain: 0.707,
      mute: true,
      solo: false,
      balance: 0.5,
      visible: true,
      display_height: 1.5,
      color: '#f59e0b',
    },
  },
}

const PEAKS: MixPeaks = {
  tracks: [0.8, 0.5, 0.3, 0.1],
  master: 0.9,
}

const noop = () => {}

beforeEach(() => {
  vi.clearAllMocks()
  fetchResultSetsMock.mockResolvedValue(SETS)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('db helpers', () => {
  it('converts gain to dB and back', () => {
    expect(gainToDb(1.0)).toBeCloseTo(0)
    expect(gainToDb(10 ** (12 / 20))).toBeCloseTo(12)
    expect(gainToDb(0)).toBe(-60)
    expect(gainToDb(0.001)).toBeCloseTo(-60)
    expect(dbToGain(0)).toBeCloseTo(1.0)
    expect(dbToGain(12)).toBeCloseTo(10 ** 0.6)
    expect(dbToGain(-60)).toBeCloseTo(0.001)
  })

  it('converts peak to dBFS', () => {
    expect(peakToDbFs(null)).toBeNull()
    expect(peakToDbFs(0)).toBeNull()
    expect(peakToDbFs(1.0)).toBeCloseTo(0)
    expect(peakToDbFs(0.5)).toBeCloseTo(-6.02)
  })

  it('labels balance', () => {
    expect(balanceLabel(0)).toBe('C')
    expect(balanceLabel(-1)).toBe('L')
    expect(balanceLabel(1)).toBe('R')
    expect(balanceLabel(-0.5)).toBe('L50')
    expect(balanceLabel(0.3)).toBe('R30')
  })
})

describe('ModeSelector', () => {
  it('renders three mode buttons with correct aria-pressed', () => {
    render(
      <ModeSelector
        mode="four_stems"
        sets={SETS}
        activeSetId="set-1"
        onMode={noop}
        onSelectSet={noop}
        notice={null}
      />,
    )
    expect(screen.getByRole('button', { name: 'Original' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(screen.getByRole('button', { name: 'Bass pair' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(screen.getByRole('button', { name: 'Four stems' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('lists result sets with valid ones selectable', () => {
    render(
      <ModeSelector
        mode="original"
        sets={SETS}
        activeSetId="set-1"
        onMode={noop}
        onSelectSet={noop}
        notice={null}
      />,
    )
    const select = screen.getByRole('combobox', { name: 'Result set' })
    const options = select.querySelectorAll('option')
    expect(options.length).toBe(3) // placeholder + 2 sets
    expect(options[1]).not.toBeDisabled()
    expect(options[2]).toBeDisabled()
  })

  it('shows a notice when provided', () => {
    render(
      <ModeSelector
        mode="original"
        sets={null}
        activeSetId={null}
        onMode={noop}
        onSelectSet={noop}
        notice="Select a separation result set first."
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Select a separation result set first.')
  })

  it('calls onMode when a button is clicked', async () => {
    const onMode = vi.fn()
    render(
      <ModeSelector
        mode="original"
        sets={null}
        activeSetId={null}
        onMode={onMode}
        onSelectSet={noop}
        notice={null}
      />,
    )
    await userEvent.setup().click(screen.getByRole('button', { name: 'Four stems' }))
    expect(onMode).toHaveBeenCalledWith('four_stems')
  })
})

describe('MonitoringPanel', () => {
  it('renders master gain, limiter, and peak meter', () => {
    render(
      <MonitoringPanel
        masterPeak={0.5}
        masterGain={1.0}
        limiterEnabled={true}
        onMasterGain={noop}
        onLimiter={noop}
      />,
    )
    expect(screen.getByRole('group', { name: 'Monitoring' })).toBeInTheDocument()
    expect(screen.getByLabelText('Master gain')).toBeInTheDocument()
    expect(screen.getByLabelText('Limiter')).toBeChecked()
    // Peak in dBFS
    expect(screen.getByText('-6.0')).toBeInTheDocument()
  })

  it('shows −∞ when no peak', () => {
    render(
      <MonitoringPanel
        masterPeak={null}
        masterGain={1.0}
        limiterEnabled={false}
        onMasterGain={noop}
        onLimiter={noop}
      />,
    )
    expect(screen.getByText('−∞')).toBeInTheDocument()
    expect(screen.getByLabelText('Limiter')).not.toBeChecked()
  })

  it('calls onMasterGain with linear value when slider changes', () => {
    const onMasterGain = vi.fn()
    render(
      <MonitoringPanel
        masterPeak={null}
        masterGain={1.0}
        limiterEnabled={true}
        onMasterGain={onMasterGain}
        onLimiter={noop}
      />,
    )
    const slider = screen.getByLabelText('Master gain')
    fireEvent.change(slider, { target: { value: '6' } })
    expect(onMasterGain).toHaveBeenCalledWith(dbToGain(6))
  })

  it('calls onLimiter when toggled', async () => {
    const onLimiter = vi.fn()
    render(
      <MonitoringPanel
        masterPeak={null}
        masterGain={1.0}
        limiterEnabled={true}
        onMasterGain={noop}
        onLimiter={onLimiter}
      />,
    )
    await userEvent.setup().click(screen.getByLabelText('Limiter'))
    expect(onLimiter).toHaveBeenCalledWith(false)
  })
})

describe('MixerStrip', () => {
  const settings = {
    gain: 1.0,
    mute: false,
    solo: false,
    balance: 0,
    visible: true,
    display_height: 1.0,
    color: '#e11d48',
  }

  it('renders M/S buttons with correct aria-pressed', () => {
    render(<MixerStrip label="Vocals" settings={settings} peak={null} onPatch={noop} />)
    expect(screen.getByRole('button', { name: 'Mute Vocals' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(screen.getByRole('button', { name: 'Solo Vocals' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('shows active state for muted track', () => {
    render(
      <MixerStrip
        label="Drums"
        settings={{ ...settings, mute: true }}
        peak={null}
        onPatch={noop}
      />,
    )
    expect(screen.getByRole('button', { name: 'Mute Drums' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('calls onPatch with mute toggle', async () => {
    const onPatch = vi.fn()
    render(<MixerStrip label="Vocals" settings={settings} peak={null} onPatch={onPatch} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Mute Vocals' }))
    expect(onPatch).toHaveBeenCalledWith({ mute: true })
  })

  it('calls onPatch with solo toggle', async () => {
    const onPatch = vi.fn()
    render(<MixerStrip label="Vocals" settings={settings} peak={null} onPatch={onPatch} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Solo Vocals' }))
    expect(onPatch).toHaveBeenCalledWith({ solo: true })
  })

  it('calls onPatch with gain in linear when slider changes', () => {
    const onPatch = vi.fn()
    render(<MixerStrip label="Vocals" settings={settings} peak={null} onPatch={onPatch} />)
    const slider = screen.getByLabelText('Vocals gain')
    fireEvent.change(slider, { target: { value: '6' } })
    expect(onPatch).toHaveBeenCalledWith({ gain: dbToGain(6) })
  })

  it('calls onPatch with balance when slider changes', () => {
    const onPatch = vi.fn()
    render(<MixerStrip label="Vocals" settings={settings} peak={null} onPatch={onPatch} />)
    const slider = screen.getByLabelText('Vocals balance')
    fireEvent.change(slider, { target: { value: '0.5' } })
    expect(onPatch).toHaveBeenCalledWith({ balance: 0.5 })
  })

  it('calls onPatch with visible toggle', async () => {
    const onPatch = vi.fn()
    render(<MixerStrip label="Vocals" settings={settings} peak={null} onPatch={onPatch} />)
    await userEvent.setup().click(screen.getByLabelText('Show Vocals waveform'))
    expect(onPatch).toHaveBeenCalledWith({ visible: false })
  })

  it('calls onPatch with color change', () => {
    const onPatch = vi.fn()
    render(<MixerStrip label="Vocals" settings={settings} peak={null} onPatch={onPatch} />)
    const colorInput = screen.getByLabelText('Vocals color')
    fireEvent.change(colorInput, { target: { value: '#00ff00' } })
    expect(onPatch).toHaveBeenCalledWith({ color: '#00ff00' })
  })

  it('shows peak meter dBFS value', () => {
    render(<MixerStrip label="Vocals" settings={settings} peak={0.5} onPatch={noop} />)
    expect(screen.getByText('-6.0')).toBeInTheDocument()
  })

  it('shows −∞ when no peak', () => {
    render(<MixerStrip label="Vocals" settings={settings} peak={null} onPatch={noop} />)
    expect(screen.getByText('−∞')).toBeInTheDocument()
  })
})

describe('TrackStack', () => {
  const baseProps = {
    projectId: PROJECT_ID,
    viewSource: null,
    playheadSource: undefined,
    practiceState: PRACTICE_STATE,
    detail: DETAIL,
    peaks: PEAKS,
    onTrackSettings: noop,
    onMasterGain: noop,
    onLimiter: noop,
    onMode: noop,
    onSelectSet: noop,
  }

  it('renders stem lanes in canonical order for four_stems mode', () => {
    render(<TrackStack {...baseProps} />)
    // All four stems should be present
    expect(screen.getByText('Vocals')).toBeInTheDocument()
    expect(screen.getByText('Drums')).toBeInTheDocument()
    expect(screen.getByText('Bass')).toBeInTheDocument()
    expect(screen.getByText('Other')).toBeInTheDocument()
  })

  it('renders only bass + others for bass_pair mode', () => {
    const bassPairState: PracticeState = {
      ...PRACTICE_STATE,
      playback_mode: 'bass_pair',
    }
    const bassPairDetail: ResultSetDetail = {
      ...DETAIL,
      stems: [
        DETAIL.stems[2], // bass
        {
          role: 'others',
          displayName: 'Others',
          assetId: 'asset-others',
          sampleRate: 48000,
          channelCount: 2,
          frameCount: 48000,
        },
      ],
    }
    render(<TrackStack {...baseProps} practiceState={bassPairState} detail={bassPairDetail} />)
    expect(screen.getByText('Bass')).toBeInTheDocument()
    expect(screen.getByText('Others')).toBeInTheDocument()
    expect(screen.queryByText('Vocals')).not.toBeInTheDocument()
    expect(screen.queryByText('Drums')).not.toBeInTheDocument()
  })

  it('renders no lanes in original mode', () => {
    const originalState: PracticeState = {
      ...PRACTICE_STATE,
      playback_mode: 'original',
    }
    render(<TrackStack {...baseProps} practiceState={originalState} />)
    expect(screen.queryByText('Vocals')).not.toBeInTheDocument()
    expect(screen.queryByText('Drums')).not.toBeInTheDocument()
  })

  it('shows provenance line with engine version and model hash', () => {
    render(<TrackStack {...baseProps} />)
    // Provenance appears in every stem lane
    const provenanceLines = screen.getAllByText('2.1.0 · model abcdef12')
    expect(provenanceLines.length).toBe(4)
  })

  it('applies track color to the label', () => {
    render(<TrackStack {...baseProps} />)
    const vocalsLabel = screen.getByText('Vocals')
    expect(vocalsLabel).toHaveStyle({ color: '#e11d48' })
  })

  it('applies display_height to lane height', () => {
    render(<TrackStack {...baseProps} />)
    // Drums has display_height 1.5, base is 48 → 72px
    const drumsLane = screen.getByLabelText('Drums waveform')
    expect(drumsLane).toHaveStyle({ height: '72px' })
  })

  it('shows hidden state when visible is false', () => {
    const hiddenState: PracticeState = {
      ...PRACTICE_STATE,
      tracks: {
        ...PRACTICE_STATE.tracks,
        vocals: { ...PRACTICE_STATE.tracks!.vocals, visible: false },
      },
    }
    render(<TrackStack {...baseProps} practiceState={hiddenState} />)
    expect(screen.getByText('Hidden (audio still plays)')).toBeInTheDocument()
  })

  it('shows mode notice when stem mode selected without active set', async () => {
    const noSetState: PracticeState = {
      ...PRACTICE_STATE,
      active_result_set_id: null,
      playback_mode: 'four_stems',
    }
    const onMode = vi.fn()
    render(
      <TrackStack
        {...baseProps}
        practiceState={{ ...noSetState, playback_mode: 'original' }}
        detail={null}
        onMode={onMode}
      />,
    )
    // Click Four stems without an active set
    await userEvent.setup().click(screen.getByRole('button', { name: 'Four stems' }))
    expect(onMode).not.toHaveBeenCalled()
    expect(screen.getByRole('status')).toHaveTextContent('Select a separation result set first.')
  })

  it('calls onMode when active set exists', async () => {
    const onMode = vi.fn()
    render(<TrackStack {...baseProps} onMode={onMode} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Bass pair' }))
    expect(onMode).toHaveBeenCalledWith('bass_pair')
  })

  it('calls onTrackSettings when a mixer control changes', async () => {
    const onTrackSettings = vi.fn()
    render(<TrackStack {...baseProps} onTrackSettings={onTrackSettings} />)
    // Click mute on Vocals
    await userEvent.setup().click(screen.getByRole('button', { name: 'Mute Vocals' }))
    expect(onTrackSettings).toHaveBeenCalledWith('vocals', { mute: true })
  })

  it('calls onMasterGain from the monitoring panel', () => {
    const onMasterGain = vi.fn()
    render(<TrackStack {...baseProps} onMasterGain={onMasterGain} />)
    const slider = screen.getByLabelText('Master gain')
    fireEvent.change(slider, { target: { value: '3' } })
    expect(onMasterGain).toHaveBeenCalledWith(dbToGain(3))
  })

  it('calls onLimiter from the monitoring panel', async () => {
    const onLimiter = vi.fn()
    render(<TrackStack {...baseProps} onLimiter={onLimiter} />)
    await userEvent.setup().click(screen.getByLabelText('Limiter'))
    expect(onLimiter).toHaveBeenCalledWith(false)
  })

  it('calls onSelectSet when the dropdown changes', async () => {
    const onSelectSet = vi.fn()
    render(<TrackStack {...baseProps} onSelectSet={onSelectSet} />)
    // Wait for the async sets list to load
    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Result set' })).toHaveValue('set-1')
    })
    const select = screen.getByRole('combobox', { name: 'Result set' })
    // Verify the select has the active set as its value
    expect(select).toHaveValue('set-1')
  })

  it('renders peak meters per track', () => {
    render(<TrackStack {...baseProps} />)
    // Vocals peak = 0.8 → -1.94 dBFS
    expect(screen.getByText('-1.9')).toBeInTheDocument()
    // Master peak = 0.9 → -0.92 dBFS
    expect(screen.getByText('-0.9')).toBeInTheDocument()
  })
})

describe('canonical stem orders', () => {
  it('bass_pair is [bass, others]', () => {
    expect(BASS_PAIR_ROLES).toEqual(['bass', 'others'])
  })

  it('four_stems is [vocals, drums, bass, other]', () => {
    expect(FOUR_STEM_ROLES).toEqual(['vocals', 'drums', 'bass', 'other'])
  })
})
