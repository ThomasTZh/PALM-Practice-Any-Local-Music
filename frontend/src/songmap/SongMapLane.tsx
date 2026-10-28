/**
 * Song Map section lane aligned with the shared waveform view.
 *
 * Sections are source-frame ranges persisted in PracticeState. The lane is
 * read-only; creation and edits go through SectionPanel commands.
 */

import { useEffect, useState } from 'react'

import type { PracticeState, SongSection } from '../api/commands'
import type { SharedView, ViewSource } from '../waveform/WaveformEditor'

export interface SongMapLaneProps {
  viewSource: ViewSource
  practiceState: PracticeState | null
  onSelect: (section: SongSection) => void
}

function frameToX(view: SharedView, frame: number): number {
  return (frame - view.startFrame) / view.fpp
}

export function SongMapLane({ viewSource, practiceState, onSelect }: SongMapLaneProps) {
  const [view, setView] = useState<SharedView | null>(() => viewSource.get())

  useEffect(() => {
    let frame = 0
    const tick = () => {
      const next = viewSource.get()
      if (next) {
        setView((current) =>
          current &&
          current.startFrame === next.startFrame &&
          current.fpp === next.fpp &&
          current.widthCssPx === next.widthCssPx
            ? current
            : next,
        )
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [viewSource])

  const sections = practiceState?.sections ?? []
  if (!view) return null
  return (
    <div className="songmap-lane" aria-label="Song Map">
      <div className="songmap-lane-label">Song Map</div>
      {sections.length === 0 ? (
        <p className="songmap-lane-empty muted">No sections yet. Select a range, then add one.</p>
      ) : (
        sections.map((section) => {
          const left = Math.max(0, frameToX(view, section.start_frames))
          const right = Math.min(view.widthCssPx, frameToX(view, section.end_frames))
          if (right <= 0 || left >= view.widthCssPx) return null
          return (
            <button
              key={section.id}
              type="button"
              className="songmap-section"
              style={{
                left,
                width: Math.max(2, right - left),
                borderColor: section.color,
                backgroundColor: `${section.color}33`,
              }}
              title={`${section.name} (${section.start_frames}-${section.end_frames})`}
              aria-label={`Song section ${section.name}`}
              onClick={() => onSelect(section)}
            >
              <span>{section.name}</span>
            </button>
          )
        })
      )}
    </div>
  )
}
