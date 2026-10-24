import { describe, expect, it } from 'vitest'

import {
  detailForZoom,
  hitTestHandles,
  suppressOverlappingLabels,
  visibleGridEvents,
  type GridLikeEvent,
  type RulerHandle,
} from '../src/music/ruler'

function event(kind: GridLikeEvent['kind'], frame: number, label: string): GridLikeEvent {
  return { kind, source_frame: frame, label }
}

const events = [
  event('bar', 0, '1'),
  event('primary', 24_000, '1.2'),
  event('denominator', 12_000, '1.2'),
  event('bar', 48_000, '2'),
  event('primary', 72_000, '2.2'),
  event('bar', 96_000, '3'),
]

describe('zoom-dependent ruler detail (M3.11 §13.3)', () => {
  it('selects coarser detail as zoom decreases', () => {
    expect(detailForZoom(4)).toBe('bars')
    expect(detailForZoom(24)).toBe('primary')
    expect(detailForZoom(80)).toBe('denominator')
    expect(detailForZoom(200)).toBe('half_beat')
    expect(detailForZoom(600)).toBe('quarter_beat')
  })

  it('filters by detail and visible source range', () => {
    expect(visibleGridEvents(events, 0, 96_000, 'bars').map((e) => e.label)).toEqual([
      '1',
      '2',
      '3',
    ])
    expect(visibleGridEvents(events, 20_000, 50_000, 'primary').map((e) => e.label)).toEqual([
      '1.2',
      '2',
    ])
  })

  it('suppresses labels that would overlap at a given scale', () => {
    const close = suppressOverlappingLabels(events, 0.01, 44)
    expect(close.length).toBe(events.length)
    const zoomedOut = suppressOverlappingLabels(events, 0.0001, 44)
    expect(zoomedOut.length).toBeLessThan(events.length)
    expect(zoomedOut[0].label).toBe('1')
  })
})

describe('ruler hit testing (M3.11 §13.7)', () => {
  const handles: RulerHandle[] = [
    { id: 'wave', kind: 'waveform', x: 100, width: 20 },
    { id: 'pulse', kind: 'pulse', x: 100, width: 4 },
    { id: 'meter', kind: 'meter_boundary', x: 101, width: 4 },
    { id: 'anchor', kind: 'tempo_anchor', x: 102, width: 4 },
    { id: 'drag', kind: 'drag', x: 103, width: 4 },
  ]

  it('honours the documented priority order near overlaps', () => {
    expect(hitTestHandles(handles, 101)?.id).toBe('drag')
    expect(hitTestHandles(handles.slice(0, 4), 101)?.id).toBe('anchor')
    expect(hitTestHandles(handles.slice(0, 3), 101)?.id).toBe('meter')
    expect(hitTestHandles(handles.slice(0, 2), 100)?.id).toBe('pulse')
    expect(hitTestHandles([handles[0]], 100)?.id).toBe('wave')
  })

  it('uses a minimum practical handle width and misses empty space', () => {
    expect(hitTestHandles([handles[1]], 104, 8)?.id).toBe('pulse')
    expect(hitTestHandles([handles[1]], 110, 8)).toBeNull()
  })
})
