import { useState } from "react";

import {
  addSection,
  deleteSection,
  draftSectionRange,
  renameSection,
  resizeSection,
  sectionAt,
  sectionBlocks,
  sectionLoopRange,
  splitSection,
  type BeatGrid,
  type Section,
  type SnapMode,
  type TimeRange,
} from "../../state/sections";
import type { StudioPlayer } from "../../state/player";
import type { Viewport } from "../waveform/viewport";
import { BarBeatOverlay } from "./BarBeatOverlay";

export interface SectionLaneProps {
  sections: Section[];
  grid: BeatGrid | null;
  viewport: Viewport;
  widthPx: number;
  durationSeconds: number;
  positionSeconds: number;
  /** Controlled snap mode; the lane falls back to its own state when omitted. */
  snapMode?: SnapMode;
  onSnapModeChange?: (mode: SnapMode) => void;
  selection?: TimeRange | null;
  onChange: (sections: Section[]) => void;
  onLoop: (section: Section) => void;
  onSeek?: (seconds: number) => void;
  /** Optional transport seam: looping a section also sets the real loop. */
  player?: Pick<StudioPlayer, "setLoopRange" | "setLoopEnabled">;
}

function edgeValue(seconds: number): number {
  return Number(seconds.toFixed(2));
}

/**
 * Manual section lane. Add and split snap to the nearest bar by default and
 * follow the bar/beat/free selector; looping a section never removes or locks
 * it, so the name and boundaries stay editable.
 */
export function SectionLane({
  sections,
  grid,
  viewport,
  widthPx,
  durationSeconds,
  positionSeconds,
  snapMode: controlledSnap,
  onSnapModeChange,
  selection = null,
  onChange,
  onLoop,
  onSeek,
  player,
}: SectionLaneProps) {
  const [innerSnap, setInnerSnap] = useState<SnapMode>("bar");
  const snapMode = controlledSnap ?? innerSnap;
  const current = sectionAt(sections, positionSeconds);
  const blocks = sectionBlocks(sections, viewport, widthPx);

  function changeSnap(mode: SnapMode): void {
    setInnerSnap(mode);
    onSnapModeChange?.(mode);
  }

  function handleAdd(): void {
    const range = draftSectionRange(
      positionSeconds,
      selection,
      snapMode,
      grid,
      durationSeconds,
    );
    if (range === null) {
      return;
    }
    onChange(addSection(sections, range, snapMode, grid, { durationSeconds }));
  }

  function handleLoop(section: Section): void {
    if (player) {
      player.setLoopRange(sectionLoopRange(section));
      player.setLoopEnabled(true);
    }
    onLoop(section);
  }

  function handleSplit(): void {
    if (current === null) {
      return;
    }
    onChange(
      splitSection(sections, current.id, positionSeconds, snapMode, grid),
    );
  }

  return (
    <section
      className="section-lane"
      data-testid="section-lane"
      aria-label="Sections"
    >
      <header className="panel-header">
        <h2>Sections</h2>
        <label className="snap-control">
          Snap
          <select
            aria-label="Snap"
            value={snapMode}
            onChange={(event) => changeSnap(event.target.value as SnapMode)}
          >
            <option value="bar">Bar</option>
            <option value="beat">Beat</option>
            <option value="free">Free</option>
          </select>
        </label>
        <button type="button" onClick={handleAdd}>
          Add section
        </button>
        <button
          type="button"
          aria-label="Split section at playhead"
          onClick={handleSplit}
          disabled={current === null}
        >
          Split
        </button>
      </header>

      <div className="section-timeline" style={{ width: widthPx }}>
        <BarBeatOverlay
          beats={grid?.beats ?? []}
          bpb={grid?.bpb ?? 4}
          viewport={viewport}
          widthPx={widthPx}
        />
        {sections.length === 0 ? (
          <p className="panel-empty">
            No sections yet. Add one to loop a passage.
          </p>
        ) : (
          blocks.map((block) => (
            <div
              key={block.section.id}
              className="section-block"
              data-testid={`section-block-${block.section.id}`}
              data-current={block.section.id === current?.id}
              style={{ left: block.leftPx, width: block.widthPx }}
              onClick={() => onSeek?.(block.section.startSeconds)}
            >
              <span className="section-block-name">{block.section.name}</span>
              <button
                type="button"
                aria-label={`Loop ${block.section.name}`}
                onClick={(event) => {
                  event.stopPropagation();
                  handleLoop(block.section);
                }}
              >
                Loop
              </button>
            </div>
          ))
        )}
      </div>

      <ul className="section-editor" aria-label="Section editor">
        {sections.map((section) => (
          <li key={section.id}>
            <input
              type="text"
              aria-label={`Section name ${section.id}`}
              value={section.name}
              onChange={(event) =>
                onChange(
                  renameSection(sections, section.id, event.target.value),
                )
              }
            />
            <label>
              Start
              <input
                type="number"
                aria-label={`Section start ${section.id}`}
                value={edgeValue(section.startSeconds)}
                step="0.1"
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (Number.isFinite(value)) {
                    onChange(
                      resizeSection(
                        sections,
                        section.id,
                        "start",
                        value,
                        snapMode,
                        grid,
                      ),
                    );
                  }
                }}
              />
            </label>
            <label>
              End
              <input
                type="number"
                aria-label={`Section end ${section.id}`}
                value={edgeValue(section.endSeconds)}
                step="0.1"
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (Number.isFinite(value)) {
                    onChange(
                      resizeSection(
                        sections,
                        section.id,
                        "end",
                        value,
                        snapMode,
                        grid,
                      ),
                    );
                  }
                }}
              />
            </label>
            <button
              type="button"
              aria-label={`Delete ${section.name}`}
              onClick={() => onChange(deleteSection(sections, section.id))}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
