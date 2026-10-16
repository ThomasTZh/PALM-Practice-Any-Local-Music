/**
 * Playback speed control tests (M2.9, spec §11.6/§11.7.8).
 *
 * Covers the clamp, the gesture coalescing (slider drag updates only the
 * local display; one commit on release / Enter / preset / reset), and the
 * invalid-entry rule (the current value is preserved).
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { clampSpeed, SpeedControl } from '../src/tracks/SpeedControl'

describe('clampSpeed', () => {
  it('keeps in-range values', () => {
    expect(clampSpeed(1.0)).toBe(1.0)
    expect(clampSpeed(0.25)).toBe(0.25)
    expect(clampSpeed(2.0)).toBe(2.0)
    expect(clampSpeed(1.37)).toBe(1.37)
  })

  it('clamps out-of-range values to the spec bounds', () => {
    expect(clampSpeed(0.1)).toBe(0.25)
    expect(clampSpeed(3.0)).toBe(2.0)
  })

  it('falls back to 1x for non-finite input', () => {
    expect(clampSpeed(Number.NaN)).toBe(1.0)
    expect(clampSpeed(Number.POSITIVE_INFINITY)).toBe(1.0)
  })
})

describe('SpeedControl', () => {
  it('renders the slider, entry, presets, and reset', () => {
    render(<SpeedControl speed={1.0} onCommit={() => {}} />)
    expect(screen.getByRole('slider', { name: 'Playback speed slider' })).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: 'Playback speed value' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '0.25×' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '2×' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reset speed to 1×' })).toBeInTheDocument()
  })

  it('coalesces a slider drag: input updates the display, release commits once', () => {
    const onCommit = vi.fn()
    render(<SpeedControl speed={1.0} onCommit={onCommit} />)
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '1.5' } })
    // The gesture is in flight: only the local display moved.
    expect(onCommit).not.toHaveBeenCalled()
    expect(screen.getByText('1.50×')).toBeInTheDocument()
    fireEvent.pointerUp(slider)
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith(1.5)
  })

  it('commits the slider draft on key-up (arrow keys)', () => {
    const onCommit = vi.fn()
    render(<SpeedControl speed={1.0} onCommit={onCommit} />)
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '0.75' } })
    fireEvent.keyUp(slider)
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith(0.75)
  })

  it('commits the slider draft on blur', () => {
    const onCommit = vi.fn()
    render(<SpeedControl speed={1.0} onCommit={onCommit} />)
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '1.25' } })
    fireEvent.blur(slider)
    expect(onCommit).toHaveBeenCalledWith(1.25)
  })

  it('does not commit a release without a draft', () => {
    const onCommit = vi.fn()
    render(<SpeedControl speed={1.0} onCommit={onCommit} />)
    fireEvent.pointerUp(screen.getByRole('slider'))
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('commits the numeric entry on Enter and clamps out-of-range', () => {
    const onCommit = vi.fn()
    render(<SpeedControl speed={1.0} onCommit={onCommit} />)
    const entry = screen.getByRole('spinbutton')
    fireEvent.change(entry, { target: { value: '3' } })
    fireEvent.keyDown(entry, { key: 'Enter' })
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith(2.0)
  })

  it('preserves the current value for an invalid entry', () => {
    const onCommit = vi.fn()
    const { container } = render(<SpeedControl speed={1.25} onCommit={onCommit} />)
    const entry = screen.getByRole('spinbutton')
    fireEvent.change(entry, { target: { value: '' } })
    fireEvent.keyDown(entry, { key: 'Enter' })
    expect(onCommit).not.toHaveBeenCalled()
    // The display falls back to the committed value.
    expect(container.querySelector('.mixer-field-value')).toHaveTextContent('1.25×')
  })

  it('commits a preset on click', () => {
    const onCommit = vi.fn()
    render(<SpeedControl speed={1.0} onCommit={onCommit} />)
    fireEvent.click(screen.getByRole('button', { name: '1.5×' }))
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith(1.5)
  })

  it('commits 1x on reset', () => {
    const onCommit = vi.fn()
    render(<SpeedControl speed={1.75} onCommit={onCommit} />)
    fireEvent.click(screen.getByRole('button', { name: 'Reset speed to 1×' }))
    expect(onCommit).toHaveBeenCalledWith(1.0)
  })

  it('marks the committed speed preset as active', () => {
    render(<SpeedControl speed={1.5} onCommit={() => {}} />)
    expect(screen.getByRole('button', { name: '1.5×' }).className).toContain('active')
  })
})
