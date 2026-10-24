import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { MetronomePanel } from '../src/practice/MetronomePanel'

describe('MetronomePanel (M3.14 §16.11)', () => {
  it('reports enable, volume, accent, and subdivision changes', () => {
    const onChange = vi.fn()
    render(
      <MetronomePanel
        enabled={false}
        volume={0.5}
        accentDownbeats
        subdivision="primary"
        onChange={onChange}
      />,
    )
    fireEvent.click(screen.getByRole('checkbox', { name: 'Metronome' }))
    expect(onChange).toHaveBeenCalledWith({ enabled: true })
    fireEvent.change(screen.getByLabelText('Metronome volume'), {
      target: { value: '0.25' },
    })
    expect(onChange).toHaveBeenCalledWith({ volume: 0.25 })
    fireEvent.change(screen.getByLabelText('Metronome subdivision'), {
      target: { value: 'denominator' },
    })
    expect(onChange).toHaveBeenCalledWith({ subdivision: 'denominator' })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Accent downbeats' }))
    expect(onChange).toHaveBeenCalledWith({ accent_downbeats: false })
  })
})
