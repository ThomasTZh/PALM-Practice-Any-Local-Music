import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'

const { mockClient, wf } = vi.hoisted(() => ({
  mockClient: {
    GET: vi.fn(),
    POST: vi.fn(),
    PUT: vi.fn(),
  },
  // Waveform API (M1.10): the editor renders its stable `missing` state in
  // these tests — no waveform cache, no live waveform job.
  wf: {
    getAssetMetadata: vi.fn(async () => ({ waveform: null })),
    getPeaksManifest: vi.fn(async () => null),
    getPeakTile: vi.fn(),
    getAssetPcm: vi.fn(),
    listProjectJobs: vi.fn(async () => []),
    createWaveformJob: vi.fn(),
    TileNotReadyError: class TileNotReadyError extends Error {},
    NoWaveformCacheError: class NoWaveformCacheError extends Error {},
    RangeOutOfBoundsError: class RangeOutOfBoundsError extends Error {},
  },
}))

vi.mock('../src/api/client', () => ({
  createApiClient: () => mockClient,
  errorMessage: (e: unknown, fallback: string) => {
    if (e && typeof e === 'object' && 'error' in e) {
      const inner = (e as { error: { message?: string } }).error
      if (inner?.message) return inner.message
    }
    return fallback
  },
}))

vi.mock('../src/api/waveform', () => wf)

function ok<T>(data: T) {
  return { response: { ok: true, status: 200 }, data }
}

const PROJECT_ID = '11111111-1111-1111-1111-111111111111'
const IMPORT_ID = '22222222-2222-2222-2222-222222222222'
const JOB_ID = '33333333-3333-3333-3333-333333333333'
const ASSET_ID = '44444444-4444-4444-4444-444444444444'

const READY_PROJECT = {
  schema_version: 1,
  id: PROJECT_ID,
  name: 'Ready Project',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  revision: 1,
  source_asset_id: ASSET_ID,
  canonical_asset_id: ASSET_ID,
  sample_rate: 48000,
  duration_samples: 48000,
  status: 'ready',
}

const SOURCE_INFO_STEREO = {
  sample_rate: 48000,
  duration_frames: 48000,
  duration_seconds: 1.0,
  channel_count: 2,
  channel_layout: 'stereo',
  channel_labels: ['L', 'R'],
  monitoring: null,
  playback_rates: [],
}

const SOURCE_INFO_51 = {
  sample_rate: 48000,
  duration_frames: 48000,
  duration_seconds: 1.0,
  channel_count: 6,
  channel_layout: '5.1',
  channel_labels: ['FL', 'FR', 'C', 'Ls', 'Rs', 'LFE'],
  monitoring: null,
  playback_rates: [],
}

const SOURCE_INFO_51_MIXED = {
  ...SOURCE_INFO_51,
  monitoring: {
    mode: 'standard_5_1',
    asset_id: ASSET_ID,
    left_channel: 0,
    right_channel: 1,
  },
}

const SOURCE_INFO_4CH = {
  sample_rate: 44100,
  duration_frames: 44100,
  duration_seconds: 1.0,
  channel_count: 4,
  channel_layout: null,
  channel_labels: ['Ch 0', 'Ch 1', 'Ch 2', 'Ch 3'],
  monitoring: null,
  playback_rates: [],
}

const PLAYBACK_TARGET = {
  asset_id: ASSET_ID,
  role: 'canonical',
  sample_rate: 48000,
  channel_count: 2,
  frame_count: 48000,
  byte_count: 384000,
  duration_seconds: 1.0,
}

const COMPLETED_JOB = {
  id: JOB_ID,
  state: 'completed',
  stage: 'ready',
  progress_fraction: 1,
  error_code: null,
  error: null,
}

/**
 * Minimal worklet node mimicking the real adapter (M1.13 v2 protocol): it
 * acknowledges enqueued channels with a `buffered` message, the same way
 * `worklet-processor.js` does after a successful enqueue.
 */
class TestWorkletNode {
  port: {
    postMessage: (message: { type: string; [key: string]: unknown }) => void
    onmessage: ((event: { data: unknown }) => void) | null
  }
  connectedTo: unknown[] = []
  disconnected = false
  constructor() {
    this.port = {
      postMessage: (message) => {
        if (message.type === 'channels') {
          queueMicrotask(() => {
            this.port.onmessage?.({
              data: {
                type: 'buffered',
                frames: message.frames as number,
                queuedFrames: 0,
                generation: (message.generation as number | undefined) ?? 0,
              },
            })
          })
        }
      },
      onmessage: null,
    }
  }
  connect(destination: unknown): void {
    this.connectedTo.push(destination)
  }
  disconnect(): void {
    this.disconnected = true
  }
  /** Simulate the worklet reporting a consumed position (M1.13). */
  postAnchor(frame: number, generation = 0): void {
    this.port.onmessage?.({
      data: { type: 'anchor', frame, time: 0, generation },
    })
  }
  /** Simulate a ring underrun (M1.13). */
  postUnderrun(generation = 0): void {
    this.port.onmessage?.({ data: { type: 'underrun', generation } })
  }
}

class TestGainNode {
  gain = { value: 1, setTargetAtTime: () => {} }
  connectedTo: unknown[] = []
  connect(destination: unknown): void {
    this.connectedTo.push(destination)
  }
  disconnect(): void {}
}

class TestAudioContext {
  static instances: TestAudioContext[] = []
  currentTime = 0
  sampleRate = 48000
  state: 'suspended' | 'running' | 'closed' = 'running'
  onstatechange: ((event: { type: string }) => void) | null = null
  readonly destination = {}
  readonly audioWorklet = { addModule: async () => {} }
  nodes: TestWorkletNode[] = []
  constructor() {
    TestAudioContext.instances.push(this)
  }
  /** Like a real context, state transitions fire `statechange`. */
  fireStateChange(): void {
    this.onstatechange?.({ type: 'statechange' })
  }
  resume(): Promise<void> {
    this.state = 'running'
    this.fireStateChange()
    return Promise.resolve()
  }
  close(): Promise<void> {
    this.state = 'closed'
    this.fireStateChange()
    return Promise.resolve()
  }
  createWorkletNode(): TestWorkletNode {
    const node = new TestWorkletNode()
    this.nodes.push(node)
    return node
  }
  createGain(): TestGainNode {
    return new TestGainNode()
  }
}

function pcmResponse(byteLength: number): Response {
  return new Response(new ArrayBuffer(byteLength), {
    status: 200,
    headers: { 'content-length': String(byteLength) },
  })
}

interface ReadyMockOverrides {
  sourceInfo?: Record<string, unknown>
  /** Return a 404 NO_PLAYBACK_REPRESENTATION for the first N resolutions. */
  missingPlaybackResolutions?: number
  /** Complete import records for the project. */
  imports?: Array<Record<string, unknown>>
  /** Mutate state when the job is polled (e.g. flip source info). */
  onJobPoll?: () => void
  /** M2.12 §14.4: the optional runtime block on GET /api/v1/system. */
  runtime?: Record<string, unknown> | null
}

/** Wire mockClient.GET to serve a ready project with the given overrides. */
function mockReadyProject(overrides: ReadyMockOverrides = {}) {
  const state = {
    sourceInfo: overrides.sourceInfo ?? SOURCE_INFO_STEREO,
    resolutions: 0,
    missing: overrides.missingPlaybackResolutions ?? 0,
    imports: overrides.imports ?? [
      {
        id: IMPORT_ID,
        filename: 'test.wav',
        declared_byte_count: 1000,
        received_byte_count: 1000,
        transfer_state: 'complete',
      },
    ],
  }
  mockClient.GET.mockImplementation((path: string) => {
    switch (path) {
      case '/api/v1/system':
        return Promise.resolve(
          ok({
            app_version: '0.1.0-dev',
            api_version: 1,
            ready: true,
            runtime: overrides.runtime ?? null,
          }),
        )
      case '/api/v1/projects':
        return Promise.resolve(ok({ projects: [READY_PROJECT] }))
      case '/api/v1/projects/{project_id}':
        return Promise.resolve(ok(READY_PROJECT))
      case '/api/v1/projects/{project_id}/source-info':
        return Promise.resolve(ok(state.sourceInfo))
      case '/api/v1/projects/{project_id}/imports':
        return Promise.resolve(ok({ imports: state.imports }))
      case '/api/v1/projects/{project_id}/playback':
        state.resolutions += 1
        if (state.resolutions <= state.missing) {
          return Promise.resolve({
            response: { ok: false, status: 404 },
            error: {
              error: {
                code: 'NO_PLAYBACK_REPRESENTATION',
                message: 'No playback representation',
              },
            },
          })
        }
        return Promise.resolve(ok(PLAYBACK_TARGET))
      case '/api/v1/jobs/{job_id}':
        overrides.onJobPoll?.()
        return Promise.resolve(ok(COMPLETED_JOB))
      default:
        return Promise.resolve(ok({}))
    }
  })
  return state
}

beforeEach(() => {
  vi.clearAllMocks()
  TestAudioContext.instances = []
  sessionStorage.clear()
  sessionStorage.setItem('basseparate.sessionToken', 'test-token')
  window.history.replaceState(null, '', '/')
  vi.stubGlobal('AudioContext', TestAudioContext)
  // A fresh Response per call: the fill loop fetches many chunks and a
  // Response body can only be read once.
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(pcmResponse(480))),
  )
  // jsdom has no Blob URL support; the transport creates one for the
  // worklet module and the fake addModule ignores it.
  vi.spyOn(URL, 'createObjectURL').mockImplementation(() => 'blob:test-worklet')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  mockClient.POST.mockImplementation((path: string) => {
    if (path === '/api/v1/projects/{project_id}/jobs') {
      return Promise.resolve({ response: { ok: true, status: 201 }, data: COMPLETED_JOB })
    }
    return Promise.resolve(ok({}))
  })
  mockClient.PUT.mockImplementation(() => Promise.resolve(ok(READY_PROJECT)))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function openReadyProject() {
  render(<App />)
  const link = await screen.findByRole('button', { name: /Ready Project/ })
  await userEvent.setup().click(link)
  return screen.findByText('Source')
}

describe('playback panel: source info', () => {
  it('shows rate, duration, and channel labels for a ready stereo project', async () => {
    mockReadyProject({ sourceInfo: SOURCE_INFO_STEREO })
    await openReadyProject()
    expect(await screen.findByText('48000 Hz')).toBeInTheDocument()
    expect(screen.getByText('0:01.000')).toBeInTheDocument()
    // Exact-frame readout (M1.14 §16.3): the current position in frames.
    expect(screen.getByText('Frame')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.getByText('2 (stereo)')).toBeInTheDocument()
    expect(screen.getByText('L')).toBeInTheDocument()
    expect(screen.getByText('R')).toBeInTheDocument()
  })

  it('hides the monitoring section for stereo sources', async () => {
    mockReadyProject({ sourceInfo: SOURCE_INFO_STEREO })
    await openReadyProject()
    expect(screen.queryByText('Monitoring')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument()
  })
})

describe('playback panel: monitoring mix', () => {
  it('creates a standard 5.1 mix without channel selection', async () => {
    const user = userEvent.setup()
    const state = mockReadyProject({
      sourceInfo: SOURCE_INFO_51,
      onJobPoll: () => {
        state.sourceInfo = SOURCE_INFO_51_MIXED
      },
    })
    await openReadyProject()
    expect(screen.getByText('A standard 5.1 → stereo downmix will be created.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Create monitoring mix' }))

    expect(await screen.findByText('Standard 5.1 → stereo downmix')).toBeInTheDocument()
    expect(mockClient.POST).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/jobs',
      expect.objectContaining({
        body: { import_id: IMPORT_ID, job_type: 'monitoring_downmix' },
      }),
    )
    // No manual channel selection was sent for the standard layout.
    expect(mockClient.PUT).not.toHaveBeenCalled()
  })

  it('selects manual L/R channels for unknown layouts', async () => {
    const user = userEvent.setup()
    mockReadyProject({ sourceInfo: SOURCE_INFO_4CH })
    await openReadyProject()

    expect(screen.getByLabelText('Left')).toBeInTheDocument()
    expect(screen.getByLabelText('Right')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Left'), '2')
    await user.selectOptions(screen.getByLabelText('Right'), '3')
    await user.click(screen.getByRole('button', { name: 'Create monitoring mix' }))

    expect(mockClient.PUT).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/monitoring-channels',
      expect.objectContaining({ body: { left: 2, right: 3 } }),
    )
    expect(mockClient.POST).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/jobs',
      expect.objectContaining({
        body: expect.objectContaining({ job_type: 'monitoring_downmix' }),
      }),
    )
    // The mix job completes; the panel re-queries source info.
    expect(await screen.findByText('44100 Hz')).toBeInTheDocument()
  })
})

describe('playback panel: transport', () => {
  it('plays at the context rate when a representation exists', async () => {
    const user = userEvent.setup()
    mockReadyProject({ sourceInfo: SOURCE_INFO_STEREO })
    await openReadyProject()

    await user.click(screen.getByRole('button', { name: 'Play' }))
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()
    // The raw PCM was fetched for the resolved asset.
    const fetchMock = vi.mocked(fetch)
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/assets/${ASSET_ID}/bytes`,
      expect.objectContaining({
        headers: expect.objectContaining({ Range: expect.stringMatching(/^bytes=\d+-\d+$/) }),
      }),
    )
  })

  it('creates and awaits a playback_rate job when no representation exists', async () => {
    const user = userEvent.setup()
    mockReadyProject({ sourceInfo: SOURCE_INFO_STEREO, missingPlaybackResolutions: 1 })
    await openReadyProject()
    await user.click(screen.getByRole('button', { name: 'Play' }))

    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()
    expect(mockClient.POST).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/jobs',
      expect.objectContaining({
        body: {
          import_id: IMPORT_ID,
          job_type: 'playback_rate',
          target_sample_rate: 48000,
        },
      }),
    )
    expect(mockClient.GET).toHaveBeenCalledWith(
      '/api/v1/jobs/{job_id}',
      expect.objectContaining({ params: { path: { job_id: JOB_ID } } }),
    )
  })

  it('surfaces a playback error when resolution fails permanently', async () => {
    const user = userEvent.setup()
    mockReadyProject({
      sourceInfo: SOURCE_INFO_STEREO,
      missingPlaybackResolutions: 999,
      imports: [],
    })
    await openReadyProject()
    await user.click(screen.getByRole('button', { name: 'Play' }))
    expect(
      await screen.findByText('No completed import to derive a playback representation from'),
    ).toBeInTheDocument()
  })

  it('shows the suspension hint and resumes playback with Play', async () => {
    const user = userEvent.setup()
    mockReadyProject({ sourceInfo: SOURCE_INFO_STEREO })
    await openReadyProject()
    await user.click(screen.getByRole('button', { name: 'Play' }))
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()

    const context = TestAudioContext.instances[0]
    context.state = 'suspended'
    context.fireStateChange()

    expect(
      await screen.findByText('Browser suspended audio — click Play to resume'),
    ).toBeInTheDocument()
    // While suspended the button offers the resume gesture, not a pause.
    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Play' }))
    expect(context.state).toBe('running')
    expect(
      screen.queryByText('Browser suspended audio — click Play to resume'),
    ).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()
  })

  it('recovers from context loss by re-resolving and playing the retained position', async () => {
    const user = userEvent.setup()
    mockReadyProject({ sourceInfo: SOURCE_INFO_STEREO })
    await openReadyProject()
    await user.click(screen.getByRole('button', { name: 'Play' }))
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()

    const context = TestAudioContext.instances[0]
    context.nodes[0].postAnchor(24_000)
    expect(await screen.findByText('0:00.500 / 0:01.000')).toBeInTheDocument()

    // The audio device is lost: the context closes.
    context.close()
    expect(
      await screen.findByText('The audio context was closed (the audio device may have changed)'),
    ).toBeInTheDocument()
    // The playhead is retained.
    expect(screen.getByText('0:00.500 / 0:01.000')).toBeInTheDocument()

    const resolutionsBefore = mockClient.GET.mock.calls.filter(
      (c) => c[0] === '/api/v1/projects/{project_id}/playback',
    ).length

    await user.click(screen.getByRole('button', { name: 'Play' }))
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()

    // A fresh context is created and the representation is re-resolved.
    expect(TestAudioContext.instances).toHaveLength(2)
    expect(
      mockClient.GET.mock.calls.filter((c) => c[0] === '/api/v1/projects/{project_id}/playback')
        .length,
    ).toBe(resolutionsBefore + 1)
    // Playback continues from the retained position.
    expect(screen.getByText('0:00.500 / 0:01.000')).toBeInTheDocument()
  })

  it('shows the underrun diagnostics line after an underrun', async () => {
    const user = userEvent.setup()
    mockReadyProject({ sourceInfo: SOURCE_INFO_STEREO })
    await openReadyProject()
    await user.click(screen.getByRole('button', { name: 'Play' }))
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()
    expect(screen.queryByText(/Underruns:/)).not.toBeInTheDocument()

    TestAudioContext.instances[0].nodes[0].postUnderrun()
    expect(await screen.findByText('Underruns: 1')).toBeInTheDocument()
  })

  it('shows the polled runtime diagnostics from /system (M2.12 §14.4)', async () => {
    mockReadyProject({
      runtime: {
        api: { rss_bytes: 32 * 1024 * 1024, cpu_seconds: 1.5 },
        media_worker: { rss_bytes: 64 * 1024 * 1024, cpu_seconds: 2.5 },
        gpu: {
          total_bytes: 8 * 1024 * 1024 * 1024,
          free_bytes: 4 * 1024 * 1024 * 1024,
          peak_used_bytes: 1024 * 1024 * 1024,
        },
        job: {
          job_id: JOB_ID,
          job_type: 'waveform',
          stage: 'peaks',
          progress_fraction: 0.5,
          queued: 2,
        },
        separation_elapsed_seconds: 12.5,
      },
    })
    await openReadyProject()
    expect(await screen.findByText('Media worker: 64.0 MiB, 2.5 s CPU')).toBeInTheDocument()
    expect(screen.getByText('GPU peak: 1024.0 MiB')).toBeInTheDocument()
    expect(screen.getByText('Job: waveform (peaks) 50%, 2 queued')).toBeInTheDocument()
    expect(screen.getByText('Separation: 12.5 s')).toBeInTheDocument()
    // The transport rows share the expanded block (no underrun yet).
    expect(screen.getByText('Underruns: 0')).toBeInTheDocument()
  })

  it('redraws the position from sync() on tab visibility return', async () => {
    const user = userEvent.setup()
    mockReadyProject({ sourceInfo: SOURCE_INFO_STEREO })
    await openReadyProject()
    await user.click(screen.getByRole('button', { name: 'Play' }))
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()

    // Context time advances while the UI stays stale.
    TestAudioContext.instances[0].currentTime = 1.0
    document.dispatchEvent(new Event('visibilitychange'))

    expect(await screen.findByText('0:01.000 / 0:01.000')).toBeInTheDocument()
  })
})
