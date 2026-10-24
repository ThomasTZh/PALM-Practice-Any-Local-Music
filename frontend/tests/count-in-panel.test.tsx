import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { CountInPanel } from '../src/practice/CountInPanel'

describe('CountInPanel (M3.15)', () => {
  it('reports length and repetition changes', () => {
    const onChange = vi.fn()
    render(<CountInPanel mode="off" repetition="once" onChange={onChange} />)
    fireEvent.change(screen.getByLabelText('Count-in length'), {
      target: { value: 'two_bars' },
    })
    expect(onChange).toHaveBeenCalledWith({ mode: 'two_bars' })
    fireEvent.change(screen.getByLabelText('Count-in repetition'), {
      target: { value: 'every_repeat' },
    })
    expect(onChange).toHaveBeenCalledWith({ repetition: 'every_repeat' })
  })
})
