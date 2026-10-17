/**
 * Component tests for the practice loops panel (M2.11, spec §13.2).
 *
 * The panel is presentational: every test drives it through rendered
 * controls and asserts the callback payloads. Uncontrolled inputs
 * (name, boundaries, repeat count) are committed on Enter/blur; invalid
 * numeric entries are reverted locally and never reported (§13.3.5).
 */

import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { PracticeLoop } from '../src/api/commands'
import {
  LoopsPanel,
  MAX_LOOP_NAME_LENGTH,
  nextLoopColor,
  type LoopsPanelProps,
} from '../src/practice/LoopsPanel'

const SAMPLE_RATE = 48_000

function makeLoop(overrides: Partial<PracticeLoop> = {}): PracticeLoop {
  return {
    id: 'loop-1',
    name: 'Verse',
    start_frames: 4800,
    end_frames: 24_480,
    color: '#f59e0b',
    repeat_count: null,
    boundary_fade: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function setup(props: Partial<LoopsPanelProps> = {}) {
  const handlers = {
    onCreateFromSelection: vi.fn(),
    onUpdate: vi.fn(),
    onDuplicate: vi.fn(),
    onDelete: vi.fn(),
    onSelectActive: vi.fn(),
    onSetEnabled: vi.fn(),
  }
  render(
    <LoopsPanel
      loops={props.loops ?? [makeLoop()]}
      activeLoopId={props.activeLoopId !== undefined ? props.activeLoopId : 'loop-1'}
      loopEnabled={props.loopEnabled ?? false}
      selection={props.selection ?? null}
      sampleRate={props.sampleRate ?? SAMPLE_RATE}
      durationFrames={props.durationFrames ?? 48_000}
      notice={props.notice ?? null}
      {...handlers}
    />,
  )
  return handlers
}

describe('LoopsPanel (M2.11 §13.2)', () => {
  it('shows the empty hint without loops', () => {
    setup({ loops: [], activeLoopId: null })
    expect(screen.getByText(/No loops yet/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Loop list')).not.toBeInTheDocument()
  })

  it('lists name, seconds, duration, and exact frames', () => {
    setup()
    expect(screen.getByLabelText('Loop name')).toHaveValue('Verse')
    expect(screen.getByLabelText('Loop start (seconds)')).toHaveValue(0.1)
    expect(screen.getByLabelText('Loop end (seconds)')).toHaveValue(0.51)
    expect(screen.getByText('0:00.410')).toBeInTheDocument()
    expect(screen.getByText('4800–24480')).toBeInTheDocument()
  })

  it('creates from the selection only when one exists', async () => {
    const handlers = setup({ selection: { start: 9600, end: 19_200 } })
    const button = screen.getByRole('button', { name: 'Create from selection' })
    expect(button).toBeEnabled()
    await userEvent.click(button)
    expect(handlers.onCreateFromSelection).toHaveBeenCalledTimes(1)
  })

  it('disables Create from selection without a selection', () => {
    setup({ selection: null })
    expect(screen.getByRole('button', { name: 'Create from selection' })).toBeDisabled()
  })

  it('selects the active loop from a row click; action buttons do not select', async () => {
    const handlers = setup({ loops: [makeLoop(), makeLoop({ id: 'loop-2', name: 'Chorus' })] })
    const rows = within(screen.getByLabelText('Loop list')).getAllByRole('listitem')
    await userEvent.click(rows[1])
    expect(handlers.onSelectActive).toHaveBeenCalledWith('loop-2')
    // Duplicate and delete act on their own row without re-selecting.
    await userEvent.click(screen.getByRole('button', { name: 'Duplicate loop Verse' }))
    expect(handlers.onDuplicate).toHaveBeenCalledWith('loop-1')
    await userEvent.click(screen.getByRole('button', { name: 'Delete loop Verse' }))
    expect(handlers.onDelete).toHaveBeenCalledWith('loop-1')
    expect(handlers.onSelectActive).toHaveBeenCalledTimes(1)
  })

  it('commits an inline rename on blur', async () => {
    const handlers = setup()
    const name = screen.getByLabelText('Loop name')
    await userEvent.clear(name)
    await userEvent.type(name, 'Chorus')
    fireEvent.blur(name)
    expect(handlers.onUpdate).toHaveBeenCalledWith('loop-1', { name: 'Chorus' })
  })

  it('ignores an empty rename', async () => {
    const handlers = setup()
    const name = screen.getByLabelText('Loop name')
    await userEvent.clear(name)
    fireEvent.blur(name)
    expect(handlers.onUpdate).not.toHaveBeenCalled()
  })

  it('commits boundaries in seconds on Enter/blur', async () => {
    const handlers = setup()
    const start = screen.getByLabelText('Loop start (seconds)')
    await userEvent.clear(start)
    await userEvent.type(start, '0.500')
    fireEvent.blur(start)
    expect(handlers.onUpdate).toHaveBeenCalledWith('loop-1', { start_frames: 24_000 })

    const end = screen.getByLabelText('Loop end (seconds)')
    await userEvent.clear(end)
    await userEvent.type(end, '0.750')
    fireEvent.keyDown(end, { key: 'Enter' })
    expect(handlers.onUpdate).toHaveBeenCalledWith('loop-1', { end_frames: 36_000 })
  })

  it('reverts invalid boundaries without sending (never expands, §13.3.5)', async () => {
    const handlers = setup()
    const start = screen.getByLabelText('Loop start (seconds)')
    // Past the end boundary (0.510 s): invalid.
    await userEvent.clear(start)
    await userEvent.type(start, '0.900')
    fireEvent.blur(start)
    expect(handlers.onUpdate).not.toHaveBeenCalled()
    expect(start).toHaveValue(0.1)

    const end = screen.getByLabelText('Loop end (seconds)')
    await userEvent.clear(end)
    await userEvent.type(end, '10')
    fireEvent.blur(end)
    expect(handlers.onUpdate).not.toHaveBeenCalled()
    expect(end).toHaveValue(0.51)
  })

  it('commits repeat counts; blank means infinite; invalid reverts', async () => {
    const handlers = setup({ loops: [makeLoop({ repeat_count: 4 })] })
    const repeat = screen.getByLabelText('Repeat count')
    expect(repeat).toHaveValue(4)
    await userEvent.clear(repeat)
    fireEvent.blur(repeat)
    expect(handlers.onUpdate).toHaveBeenCalledWith('loop-1', { repeat_count: null })

    await userEvent.clear(repeat)
    await userEvent.type(repeat, '12')
    fireEvent.blur(repeat)
    expect(handlers.onUpdate).toHaveBeenCalledWith('loop-1', { repeat_count: 12 })

    // 0 passes and out-of-range values are rejected locally.
    await userEvent.clear(repeat)
    await userEvent.type(repeat, '0')
    fireEvent.blur(repeat)
    expect(repeat).toHaveValue(4)
  })

  it('toggles the boundary fade', async () => {
    const handlers = setup()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Boundary fade' }))
    expect(handlers.onUpdate).toHaveBeenCalledWith('loop-1', { boundary_fade: false })
  })

  it('cycles the swatch through the loop palette', async () => {
    const handlers = setup()
    const swatch = screen.getByRole('button', { name: 'Loop color #f59e0b' })
    await userEvent.click(swatch)
    expect(handlers.onUpdate).toHaveBeenCalledWith('loop-1', { color: nextLoopColor('#f59e0b') })
  })

  it('gates the looping toggle on an active loop and reports toggles', async () => {
    const handlers = setup({ activeLoopId: null, loopEnabled: false })
    const checkbox = screen.getByRole('checkbox', { name: 'Looping' })
    expect(checkbox).toBeDisabled()
    expect(handlers.onSetEnabled).not.toHaveBeenCalled()
  })

  it('reports a looping toggle from the checkbox', async () => {
    const handlers = setup({ loopEnabled: true })
    const checkbox = screen.getByRole('checkbox', { name: 'Looping' })
    expect(checkbox).toBeChecked()
    await userEvent.click(checkbox)
    expect(handlers.onSetEnabled).toHaveBeenCalledWith(false)
  })

  it('shows the notice and the too-short hint on the active loop', () => {
    setup({
      loops: [makeLoop({ end_frames: 4000, name: 'Short' })],
      notice: 'Loops shorter than 100 ms can be saved, but not repeated for practice.',
    })
    expect(screen.getByRole('alert')).toHaveTextContent('shorter than 100 ms')
    expect(screen.getByText(/Shorter than 100 ms — cannot repeat/)).toBeInTheDocument()
  })

  it('truncates an over-long rename to the server limit', async () => {
    const handlers = setup()
    const name = screen.getByLabelText('Loop name')
    const long = 'x'.repeat(MAX_LOOP_NAME_LENGTH + 20)
    await userEvent.clear(name)
    // Bypass the input maxLength the way a paste of a long value would.
    fireEvent.change(name, { target: { value: long } })
    fireEvent.blur(name)
    expect(handlers.onUpdate).toHaveBeenCalledWith('loop-1', {
      name: 'x'.repeat(MAX_LOOP_NAME_LENGTH),
    })
  })
})
