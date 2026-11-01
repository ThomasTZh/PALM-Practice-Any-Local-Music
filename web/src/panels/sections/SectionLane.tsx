import { useEffect, useRef, useState } from "react";

import {
  addSection,
  deleteSection,
  draftSectionEndingAt,
  draftSectionRange,
  moveSectionRange,
  nextBoundary,
  renameSection,
  resizeSection,
  sectionAt,
  sectionBlocks,
  sectionChainRange,
  sectionLoopRange,
  snapRange,
  snapTime,
  splitSection,
  type BeatGrid,
  type Section,
  type SectionBlock,
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
  onLoopChain?: (range: TimeRange, count: number) => void;
  onClearLoop?: () => void;
  onSeek?: (seconds: number) => void;
  onActionError?: (message: string) => void;
  /** Optional transport seam: looping a section also sets the real loop. */
  player?: Pick<StudioPlayer, "setLoopRange" | "setLoopEnabled">;
}

type Interaction =
  | {
      kind: "create";
      startX: number;
      startSeconds: number;
      currentSeconds: number;
      moved: boolean;
    }
  | {
      kind: "resize";
      sectionId: string;
      edge: "start" | "end";
      startX: number;
      startSeconds: number;
      currentSeconds: number;
      moved: boolean;
    }
  | {
      kind: "move";
      sectionId: string;
      startX: number;
      startSeconds: number;
      currentSeconds: number;
      moved: boolean;
    };

const DRAG_THRESHOLD_PX = 4;
const FREE_MIN_SECONDS = 0.1;

function edgeValue(seconds: number): number {
  return Number(seconds.toFixed(2));
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function barBoundaryTimes(grid: BeatGrid): number[] {
  const boundaries: number[] = [];
  for (let index = 0; index < grid.beats.length; index += grid.bpb) {
    boundaries.push(grid.beats[index]);
  }
  if (grid.beats.length >= 2 && grid.beats.length % grid.bpb === 0) {
    const beatSeconds =
      (grid.beats[grid.beats.length - 1] - grid.beats[0]) /
      (grid.beats.length - 1);
    if (beatSeconds > 0) {
      boundaries.push(grid.beats[grid.beats.length - 1] + beatSeconds);
    }
  }
  return boundaries;
}

function beatSpan(grid: BeatGrid): number {
  return grid.beats.length >= 2
    ? Math.max(0.01, grid.beats[1] - grid.beats[0])
    : 1;
}

function unitSpan(mode: SnapMode, grid: BeatGrid): number {
  return mode === "bar" ? beatSpan(grid) * grid.bpb : beatSpan(grid);
}

/** Largest snapped start that still leaves at least one snap unit. */
function maximumStart(
  endSeconds: number,
  mode: SnapMode,
  grid: BeatGrid | null,
): number {
  if (grid === null || mode === "free") {
    return Math.max(0, endSeconds - FREE_MIN_SECONDS);
  }
  const candidates =
    mode === "bar" ? barBoundaryTimes(grid) : grid.beats.slice();
  const limit = endSeconds - unitSpan(mode, grid);
  let best = 0;
  for (const candidate of candidates) {
    if (candidate <= limit + 1e-9) {
      best = candidate;
    }
  }
  return best;
}

/** One snap unit after the section start; free time falls back to 100 ms. */
function minimumEnd(
  startSeconds: number,
  mode: SnapMode,
  grid: BeatGrid | null,
  durationSeconds: number,
): number {
  if (grid === null || mode === "free") {
    return Math.min(durationSeconds, startSeconds + FREE_MIN_SECONDS);
  }
  const anchor = snapTime(startSeconds, mode, grid);
  const next = nextBoundary(anchor, mode, grid);
  return Math.min(
    durationSeconds,
    next ??
      anchor +
        (grid.beats.length >= 2
          ? Math.max(0.01, grid.beats[1] - grid.beats[0])
          : 1),
  );
}

/**
 * Manual section lane. Add and split snap to the nearest bar by default and
 * follow the bar/beat/free selector; dragging empty space creates a section,
 * dragging an edge resizes it, and a plain click seeks. Looping a section never
 * removes or locks it, so the name and boundaries stay editable.
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
  onLoopChain,
  onClearLoop,
  onSeek,
  onActionError,
  player,
}: SectionLaneProps) {
  const [innerSnap, setInnerSnap] = useState<SnapMode>("bar");
  const [interaction, setInteraction] = useState<Interaction | null>(null);
  const [selectedChainIds, setSelectedChainIds] = useState<string[]>([]);
  const [chainNotice, setChainNotice] = useState<string | null>(null);
  const suppressClickRef = useRef(false);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const snapMode = controlledSnap ?? innerSnap;
  const current = sectionAt(sections, positionSeconds);
  const blocks = sectionBlocks(sections, viewport, widthPx);
  const laidBlocks: Array<SectionBlock & { lane: number }> = [];
  const laneEnds: number[] = [];
  for (const block of [...blocks].sort(
    (left, right) => left.section.startSeconds - right.section.startSeconds,
  )) {
    let lane = laneEnds.findIndex(
      (end) => block.section.startSeconds >= end - 1e-9,
    );
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(block.section.endSeconds);
    } else {
      laneEnds[lane] = block.section.endSeconds;
    }
    laidBlocks.push({ ...block, lane });
  }
  const maxLane = laidBlocks.reduce(
    (maximum, block) => Math.max(maximum, block.lane),
    0,
  );
  const sortedSections = [...sections].sort((left, right) => {
    const byStart = left.startSeconds - right.startSeconds;
    return byStart !== 0 ? byStart : left.id.localeCompare(right.id);
  });
  const chainSections = sortedSections.filter((section) =>
    selectedChainIds.includes(section.id),
  );
  const chainRange = sectionChainRange(chainSections);
  const chainSummary =
    chainRange === null
      ? "Select at least two sections."
      : chainSections.length < 2
        ? `1 section selected, ${chainRange.startSeconds.toFixed(1)}-${chainRange.endSeconds.toFixed(1)} s`
        : `${chainSections.length} sections, ${chainRange.startSeconds.toFixed(1)}-${chainRange.endSeconds.toFixed(1)} s`;
  const sectionById = new Map(sections.map((section) => [section.id, section]));

  function timeAt(clientX: number): number {
    const rect = timelineRef.current?.getBoundingClientRect();
    const left = rect?.left ?? 0;
    return clamp(
      viewport.startSeconds + (clientX - left) * viewport.secondsPerPixel,
      0,
      durationSeconds,
    );
  }

  function capturePointer(
    target: HTMLElement,
    pointerId: number | undefined,
  ): void {
    if (pointerId === undefined) {
      return;
    }
    if (typeof target.setPointerCapture === "function") {
      target.setPointerCapture(pointerId);
    }
  }

  function changeSnap(mode: SnapMode): void {
    setInnerSnap(mode);
    onSnapModeChange?.(mode);
  }

  function handleAdd(): void {
    if (
      selection !== null &&
      selection.endSeconds - selection.startSeconds > 1e-9
    ) {
      const range = draftSectionRange(
        positionSeconds,
        selection,
        snapMode,
        grid,
        durationSeconds,
      );
      if (range !== null) {
        onChange(
          addSection(sections, range, snapMode, grid, { durationSeconds }),
        );
      }
      return;
    }
    const draft = draftSectionEndingAt(
      positionSeconds,
      snapMode,
      grid,
      durationSeconds,
      sections,
    );
    if (draft.range === null) {
      onActionError?.(
        draft.reason ?? "No room to add a section at the playhead.",
      );
      return;
    }
    // The end is already snapped and the start clamped; free mode keeps the
    // exact range instead of snapping the clamped boundary again.
    onChange(
      addSection(sections, draft.range, "free", grid, { durationSeconds }),
    );
  }

  function handleLoop(section: Section): void {
    if (player) {
      player.setLoopRange(sectionLoopRange(section));
      player.setLoopEnabled(true);
    }
    onLoop(section);
  }

  function toggleChainSection(sectionId: string): void {
    setChainNotice(null);
    setSelectedChainIds((current) =>
      current.includes(sectionId)
        ? current.filter((id) => id !== sectionId)
        : [...current, sectionId],
    );
  }

  function handleLoopChain(): void {
    if (chainSections.length < 2 || chainRange === null) {
      return;
    }
    if (player) {
      player.setLoopRange(chainRange);
      player.setLoopEnabled(true);
    }
    const summary = `${chainSections.length} sections, ${chainRange.startSeconds.toFixed(1)}-${chainRange.endSeconds.toFixed(1)} s`;
    setChainNotice(summary);
    onLoopChain?.(chainRange, chainSections.length);
  }

  function handleClearLoop(): void {
    setSelectedChainIds([]);
    setChainNotice("Loop cleared");
    if (player) {
      player.setLoopRange(null);
      player.setLoopEnabled(false);
    }
    onClearLoop?.();
  }

  function handleSplit(): void {
    if (current === null) {
      return;
    }
    onChange(
      splitSection(sections, current.id, positionSeconds, snapMode, grid),
    );
  }

  function createDraftRange(draft: Interaction): TimeRange | null {
    if (draft.kind !== "create") {
      return null;
    }
    return snapRange(
      {
        startSeconds: Math.min(draft.startSeconds, draft.currentSeconds),
        endSeconds: Math.max(draft.startSeconds, draft.currentSeconds),
      },
      snapMode,
      grid,
      durationSeconds,
    );
  }

  function resizeDraftRange(draft: Interaction): TimeRange | null {
    if (draft.kind !== "resize") {
      return null;
    }
    const section = sectionById.get(draft.sectionId);
    if (section === undefined) {
      return null;
    }
    if (draft.edge === "end") {
      const minimum = minimumEnd(
        section.startSeconds,
        snapMode,
        grid,
        durationSeconds,
      );
      const snapped = snapTime(draft.currentSeconds, snapMode, grid);
      return {
        startSeconds: section.startSeconds,
        endSeconds: clamp(
          Math.max(snapped, minimum),
          section.startSeconds + 0.001,
          durationSeconds,
        ),
      };
    }
    const maximum = maximumStart(section.endSeconds, snapMode, grid);
    const snapped = snapTime(draft.currentSeconds, snapMode, grid);
    return {
      startSeconds: clamp(
        Math.min(snapped, maximum),
        0,
        section.endSeconds - 0.001,
      ),
      endSeconds: section.endSeconds,
    };
  }

  function moveDraftRange(draft: Interaction): TimeRange | null {
    if (draft.kind !== "move") {
      return null;
    }
    const section = sectionById.get(draft.sectionId);
    if (section === undefined) {
      return null;
    }
    return moveSectionRange(
      section,
      draft.currentSeconds,
      snapMode,
      grid,
      durationSeconds,
    );
  }

  const draftRange =
    interaction !== null && interaction.moved
      ? interaction.kind === "create"
        ? createDraftRange(interaction)
        : interaction.kind === "resize"
          ? resizeDraftRange(interaction)
          : moveDraftRange(interaction)
      : null;

  useEffect(() => {
    if (interaction === null) {
      return;
    }
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        event.preventDefault();
        setInteraction(null);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [interaction]);

  function beginCreate(event: React.PointerEvent<HTMLDivElement>): void {
    if (event.button !== 0) {
      return;
    }
    if ((event.target as HTMLElement).closest(".section-block") !== null) {
      return;
    }
    const seconds = timeAt(event.clientX);
    setInteraction({
      kind: "create",
      startX: event.clientX,
      startSeconds: seconds,
      currentSeconds: seconds,
      moved: false,
    });
    capturePointer(event.currentTarget, event.pointerId);
  }

  function beginResize(
    event: React.PointerEvent<HTMLDivElement>,
    section: Section,
    edge: "start" | "end",
  ): void {
    event.preventDefault();
    event.stopPropagation();
    const seconds =
      edge === "start" ? section.startSeconds : section.endSeconds;
    setInteraction({
      kind: "resize",
      sectionId: section.id,
      edge,
      startX: event.clientX,
      startSeconds: seconds,
      currentSeconds: seconds,
      moved: false,
    });
    capturePointer(event.currentTarget, event.pointerId);
  }

  function beginMove(
    event: React.PointerEvent<HTMLDivElement>,
    section: Section,
  ): void {
    if (event.button !== 0) {
      return;
    }
    setInteraction({
      kind: "move",
      sectionId: section.id,
      startX: event.clientX,
      startSeconds: section.startSeconds,
      currentSeconds: section.startSeconds,
      moved: false,
    });
    capturePointer(event.currentTarget, event.pointerId);
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>): void {
    setInteraction((draft) => {
      if (draft === null) {
        return null;
      }
      const moved =
        draft.moved ||
        Math.abs(event.clientX - draft.startX) >= DRAG_THRESHOLD_PX;
      const currentSeconds =
        draft.kind === "move"
          ? Math.max(
              0,
              draft.startSeconds +
                (event.clientX - draft.startX) * viewport.secondsPerPixel,
            )
          : timeAt(event.clientX);
      return { ...draft, currentSeconds, moved };
    });
  }

  function handlePointerUp(event: React.PointerEvent<HTMLDivElement>): void {
    if (interaction === null) {
      return;
    }
    if (interaction.moved) {
      if (interaction.kind === "create") {
        const range = createDraftRange(interaction);
        if (range !== null) {
          onChange(
            addSection(sections, range, snapMode, grid, { durationSeconds }),
          );
        }
      } else if (interaction.kind === "resize") {
        const range = resizeDraftRange(interaction);
        if (range !== null) {
          onChange(
            sections.map((section) =>
              section.id === interaction.sectionId
                ? {
                    ...section,
                    startSeconds: range.startSeconds,
                    endSeconds: range.endSeconds,
                  }
                : section,
            ),
          );
        }
      } else {
        const range = moveDraftRange(interaction);
        if (range !== null) {
          onChange(
            sections.map((section) =>
              section.id === interaction.sectionId
                ? {
                    ...section,
                    startSeconds: range.startSeconds,
                    endSeconds: range.endSeconds,
                  }
                : section,
            ),
          );
        }
        suppressClickRef.current = true;
        window.setTimeout(() => {
          suppressClickRef.current = false;
        }, 0);
      }
    } else if (interaction.kind === "create") {
      onSeek?.(timeAt(event.clientX));
    }
    setInteraction(null);
  }

  function handlePointerCancel(): void {
    setInteraction(null);
  }

  function draftStyle(range: TimeRange): { left: number; width: number } {
    return {
      left:
        (range.startSeconds - viewport.startSeconds) / viewport.secondsPerPixel,
      width: (range.endSeconds - range.startSeconds) / viewport.secondsPerPixel,
    };
  }

  return (
    <section
      className="section-lane"
      data-testid="section-lane"
      aria-label="Sections"
    >
      <div
        ref={timelineRef}
        className="section-timeline"
        style={{ width: widthPx, minHeight: 54 + maxLane * 20 }}
        onPointerDown={beginCreate}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
      >
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
          laidBlocks.map((block) => (
            <div
              key={block.section.id}
              className="section-block"
              data-testid={`section-block-${block.section.id}`}
              data-current={block.section.id === current?.id}
              data-lane={block.lane}
              data-overlap={block.lane > 0 ? "true" : undefined}
              style={{
                left: block.leftPx,
                width: block.widthPx,
                top: 26 + block.lane * 20,
                zIndex: 1 + block.lane,
              }}
              onPointerDown={(event) => beginMove(event, block.section)}
              onClick={() => {
                if (suppressClickRef.current) {
                  suppressClickRef.current = false;
                  return;
                }
                onSeek?.(block.section.startSeconds);
              }}
            >
              <div
                className="section-resize-handle section-resize-start"
                data-testid={`section-resize-${block.section.id}-start`}
                role="separator"
                aria-label={`Resize ${block.section.name} start`}
                onPointerDown={(event) =>
                  beginResize(event, block.section, "start")
                }
                onClick={(event) => event.stopPropagation()}
              />
              <span className="section-block-name">{block.section.name}</span>
              <button
                type="button"
                aria-label={`Loop ${block.section.name}`}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => {
                  event.stopPropagation();
                  handleLoop(block.section);
                }}
              >
                Loop
              </button>
              <div
                className="section-resize-handle section-resize-end"
                data-testid={`section-resize-${block.section.id}-end`}
                role="separator"
                aria-label={`Resize ${block.section.name} end`}
                onPointerDown={(event) =>
                  beginResize(event, block.section, "end")
                }
                onClick={(event) => event.stopPropagation()}
              />
            </div>
          ))
        )}
        {draftRange !== null && interaction !== null && (
          <div
            className={`section-draft${
              interaction.kind === "resize" ? " section-draft-resize" : ""
            }`}
            data-testid="section-draft"
            style={draftStyle(draftRange)}
          >
            {interaction.kind === "create"
              ? "New section"
              : interaction.kind === "resize"
                ? "Resize"
                : "Move"}
          </div>
        )}
      </div>

      <header className="panel-header section-toolbar">
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

      <div className="section-editor-split">
        <div className="section-list-pane">
          <h3>Section list</h3>
          {sortedSections.length === 0 ? (
            <p className="panel-empty">No sections to edit yet.</p>
          ) : (
            <ul
              className="section-editor"
              data-testid="section-list"
              aria-label="Section editor"
            >
              {sortedSections.map((section) => (
                <li
                  key={section.id}
                  data-testid={`section-editor-item-${section.id}`}
                >
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
                  <label className="section-edge">
                    <span className="section-edge-label">Start</span>
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
                  <label className="section-edge">
                    <span className="section-edge-label">End</span>
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
                    aria-label={`Loop ${section.name} from section list`}
                    onClick={() => handleLoop(section)}
                  >
                    Loop
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${section.name}`}
                    onClick={() =>
                      onChange(deleteSection(sections, section.id))
                    }
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <aside
          className="section-loop-pane"
          data-testid="section-loop-editor"
          aria-label="Loop customisation"
        >
          <h3>Loop customisation</h3>
          {sortedSections.length === 0 ? (
            <p className="panel-empty">No sections to chain yet.</p>
          ) : (
            <fieldset className="section-chain-select">
              <legend>Select sections</legend>
              {sortedSections.map((section) => (
                <label key={section.id} className="section-chain-option">
                  <input
                    type="checkbox"
                    aria-label={`Select ${section.name} for loop chain`}
                    checked={selectedChainIds.includes(section.id)}
                    onChange={() => toggleChainSection(section.id)}
                  />
                  <span className="section-chain-name">{section.name}</span>
                  <span className="section-chain-range">
                    {section.startSeconds.toFixed(1)}-
                    {section.endSeconds.toFixed(1)} s
                  </span>
                </label>
              ))}
            </fieldset>
          )}
          <p
            className="section-chain-summary"
            data-testid="section-chain-summary"
            aria-live="polite"
          >
            {chainNotice ?? chainSummary}
          </p>
          <div className="section-chain-actions">
            <button
              type="button"
              data-testid="section-chain-loop"
              disabled={chainSections.length < 2}
              onClick={handleLoopChain}
            >
              Loop selected
            </button>
            <button
              type="button"
              data-testid="section-chain-clear"
              onClick={handleClearLoop}
            >
              Clear loop
            </button>
          </div>
        </aside>
      </div>
    </section>
  );
}
