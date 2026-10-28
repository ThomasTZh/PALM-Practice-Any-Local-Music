import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SectionPanel } from '../src/songmap/SectionPanel'
import type { SongSection } from '../src/api/commands'

function section(overrides: Partial<SongSection> = {}): SongSection {
  return {
    id: 'section-1',
    name: 'Verse',
    start_frames: 0,
    end_frames: 48000,
    color: '#22c55e',
    created_at: '2026-10-25T00:00:00Z',
    updated_at: '2026-10-25T00:00:00Z',
    ...overrides,
  }
}

describe('SectionPanel', () => {
  it('adds a section from the current selection', async () => {
    const onAdd = vi.fn()
    render(
      <SectionPanel
        sections={[]}
        sampleRate={48000}
        selection={{ start: 0, end: 48000 }}
        activeSectionId={null}
        playheadFrame={null}
        onAdd={onAdd}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
        onSplit={vi.fn()}
        onLoop={vi.fn()}
        onSelect={vi.fn()}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Add section from selection' }))
    expect(onAdd).toHaveBeenCalledOnce()
  })

  it('renames, loops, and deletes an existing section', async () => {
    const onUpdate = vi.fn()
    const onLoop = vi.fn()
    const onDelete = vi.fn()
    render(
      <SectionPanel
        sections={[section()]}
        sampleRate={48000}
        selection={null}
        activeSectionId="section-1"
        playheadFrame={24000}
        onAdd={vi.fn()}
        onUpdate={onUpdate}
        onDelete={onDelete}
        onSplit={vi.fn()}
        onLoop={onLoop}
        onSelect={vi.fn()}
      />,
    )
    const name = screen.getByLabelText('Section name')
    await userEvent.clear(name)
    await userEvent.type(name, 'Chorus')
    await userEvent.tab()
    expect(onUpdate).toHaveBeenCalledWith('section-1', { name: 'Chorus' })
    await userEvent.click(screen.getByRole('button', { name: 'Loop' }))
    expect(onLoop).toHaveBeenCalledWith('section-1')
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onDelete).toHaveBeenCalledWith('section-1')
  })

  it('splits the active section at the playhead', async () => {
    const onSplit = vi.fn()
    render(
      <SectionPanel
        sections={[section()]}
        sampleRate={48000}
        selection={null}
        activeSectionId="section-1"
        playheadFrame={24000}
        onAdd={vi.fn()}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
        onSplit={onSplit}
        onLoop={vi.fn()}
        onSelect={vi.fn()}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Split at playhead' }))
    expect(onSplit).toHaveBeenCalledWith('section-1', 24000)
  })
})
