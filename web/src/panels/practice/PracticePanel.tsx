import { formatSpeed } from "../../state/format";
import { SPEED_OPTIONS } from "../../state/player";
import {
  COUNT_IN_OPTIONS,
  type PracticeController,
} from "../../state/practice";
import { usePracticeState } from "../../state/usePracticeState";

export interface PracticePanelProps {
  controller: PracticeController;
}

/**
 * Compact practice controls in the bottom bar: speed, loop, count-in,
 * metronome, accent and metronome volume. Snap lives only in Sections.
 */
export function PracticePanel({ controller }: PracticePanelProps) {
  const state = usePracticeState(controller);
  const speeds = SPEED_OPTIONS.includes(
    state.speed as (typeof SPEED_OPTIONS)[number],
  )
    ? [...SPEED_OPTIONS]
    : [...SPEED_OPTIONS, state.speed].sort((a, b) => a - b);

  return (
    <section
      className="practice practice-bar"
      data-testid="practice"
      aria-label="Practice"
    >
      <div className="practice-controls">
        <label className="practice-control">
          Speed
          <select
            aria-label="Practice speed"
            value={state.speed}
            onChange={(event) =>
              controller.setSpeed(Number(event.target.value))
            }
          >
            {speeds.map((speed) => (
              <option key={speed} value={speed}>
                {formatSpeed(speed)}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          aria-label="Practice loop"
          aria-pressed={state.loopEnabled}
          onClick={() => controller.setLoopEnabled(!state.loopEnabled)}
        >
          Loop
        </button>

        <label className="practice-control">
          Count-in
          <select
            aria-label="Count-in"
            value={state.countInBars}
            onChange={(event) =>
              controller.setCountInBars(Number(event.target.value))
            }
          >
            {COUNT_IN_OPTIONS.map((bars) => (
              <option key={bars} value={bars}>
                {bars === 0 ? "Off" : `${bars} bar${bars === 1 ? "" : "s"}`}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          aria-label="Metronome"
          aria-pressed={state.metronomeEnabled}
          onClick={() =>
            controller.setMetronomeEnabled(!state.metronomeEnabled)
          }
        >
          Metronome
        </button>

        <button
          type="button"
          aria-label="Accent downbeat"
          aria-pressed={state.accentDownbeat}
          onClick={() => controller.setAccentDownbeat(!state.accentDownbeat)}
        >
          Accent
        </button>

        <div className="practice-control practice-volume">
          <label>
            Metronome volume
            <input
              type="range"
              aria-label="Metronome volume"
              min={0}
              max={100}
              step={1}
              value={Math.round(state.metronomeVolume * 100)}
              onChange={(event) =>
                controller.setMetronomeVolume(Number(event.target.value) / 100)
              }
            />
          </label>
          <output data-testid="metronome-volume-value">
            {Math.round(state.metronomeVolume * 100)}%
          </output>
        </div>
      </div>
    </section>
  );
}
