import { formatSpeed } from "../../state/format";
import { SPEED_OPTIONS } from "../../state/player";
import {
  COUNT_IN_OPTIONS,
  type PracticeController,
} from "../../state/practice";
import type { SnapMode } from "../../state/sections";
import { usePracticeState } from "../../state/usePracticeState";

export interface PracticePanelProps {
  controller: PracticeController;
  snapMode: SnapMode;
  onSnapModeChange: (mode: SnapMode) => void;
}

/**
 * Practice controls: speed, loop, count-in, metronome and snap mode.
 * State and actions live behind PracticeController so the app can map it onto
 * the real transport and metronome without changing this panel.
 */
export function PracticePanel({
  controller,
  snapMode,
  onSnapModeChange,
}: PracticePanelProps) {
  const state = usePracticeState(controller);
  const speeds = SPEED_OPTIONS.includes(
    state.speed as (typeof SPEED_OPTIONS)[number],
  )
    ? [...SPEED_OPTIONS]
    : [...SPEED_OPTIONS, state.speed].sort((a, b) => a - b);

  return (
    <section className="practice" data-testid="practice" aria-label="Practice">
      <header className="panel-header">
        <h2>Practice</h2>
      </header>

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

        <div className="practice-control">
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

        <label className="practice-control">
          Snap
          <select
            aria-label="Snap mode"
            value={snapMode}
            onChange={(event) =>
              onSnapModeChange(event.target.value as SnapMode)
            }
          >
            <option value="bar">Bar</option>
            <option value="beat">Beat</option>
            <option value="free">Free</option>
          </select>
        </label>
      </div>
    </section>
  );
}
