import { chordAt, chordBlocks, type ChordRegion } from "../../state/chords";
import { timeToX, type Viewport } from "../waveform/viewport";

export interface ChordRibbonProps {
  chords: ChordRegion[];
  viewport: Viewport;
  widthPx: number;
  positionSeconds: number;
  onSeek?: (seconds: number) => void;
}

/**
 * Chord blocks on the shared timeline. The chord under the playhead is marked
 * with aria-current and a stronger style; gaps stay empty.
 */
export function ChordRibbon({
  chords,
  viewport,
  widthPx,
  positionSeconds,
  onSeek,
}: ChordRibbonProps) {
  const blocks = chordBlocks(chords, viewport, widthPx);
  const current = chordAt(chords, positionSeconds);
  const currentIndex =
    current === null
      ? -1
      : chords.findIndex(
          (chord) =>
            chord.startSeconds === current.startSeconds &&
            chord.endSeconds === current.endSeconds &&
            chord.label === current.label,
        );

  return (
    <section
      className="chord-ribbon"
      data-testid="chord-ribbon"
      aria-label="Chord ribbon"
      style={{ width: widthPx }}
    >
      {chords.length === 0 ? (
        <p className="panel-empty">Run analysis to see chords.</p>
      ) : (
        <div className="chord-track">
          {blocks.map((block) => (
            <button
              type="button"
              key={`${block.index}-${block.startSeconds}`}
              className="chord-block"
              data-testid={`chord-block-${block.index}`}
              data-current={block.index === currentIndex}
              aria-current={block.index === currentIndex ? "true" : undefined}
              title={block.label}
              style={{ left: block.leftPx, width: block.widthPx }}
              onClick={() => onSeek?.(Math.max(0, block.startSeconds))}
            >
              {block.symbol}
            </button>
          ))}
          <div
            className="chord-ribbon-playhead"
            data-testid="chord-ribbon-playhead"
            style={{ left: timeToX(positionSeconds, viewport) }}
          />
        </div>
      )}
    </section>
  );
}
