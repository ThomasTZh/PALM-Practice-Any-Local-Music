import {
  anySoloed,
  defaultStemMix,
  isAudible,
  MAX_GAIN_DB,
  MAX_PAN,
  MIN_GAIN_DB,
  MIN_PAN,
  type MixerController,
} from "../../state/mixer";
import { useMixerState } from "../../state/useMixerState";
import "./mixer.css";

export interface MixerStem {
  id: string;
  name: string;
  role?: string;
}

export interface MixerSeparation {
  hasStems: boolean;
  running: boolean;
  /** 0..1 */
  progress: number;
  stage: string;
  error: string | null;
  onSeparate: () => void;
  onCancel: () => void;
}

export interface MixerPanelProps {
  stems: MixerStem[];
  controller: MixerController;
  separation?: MixerSeparation;
}

export function formatGainDb(gainDb: number): string {
  const rounded = Math.round(gainDb * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)} dB`;
}

export function formatPan(pan: number): string {
  if (Math.abs(pan) < 0.005) {
    return "C";
  }
  const side = pan < 0 ? "L" : "R";
  return `${side} ${Math.round(Math.abs(pan) * 100)}`;
}

/**
 * Stem mixer strips. Every control writes to the MixerController seam, which
 * the app maps onto the real engine's per-stem gain/mute/solo/pan.
 */
export function MixerPanel({ stems, controller, separation }: MixerPanelProps) {
  const state = useMixerState(controller);
  const soloActive = anySoloed(state);
  const progressPercent = Math.round(
    Math.min(1, Math.max(0, separation?.progress ?? 0)) * 100,
  );

  return (
    <section className="mixer" data-testid="mixer" aria-label="Stem mixer">
      <header className="panel-header">
        <h2>Mixer</h2>
        {soloActive && <span className="panel-badge">Solo</span>}
      </header>

      {separation !== undefined && (
        <div className="mixer-separation" data-testid="mixer-separation">
          {separation.running ? (
            <>
              <div
                className="mixer-separation-progress"
                role="progressbar"
                aria-label="Stem separation progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progressPercent}
                data-testid="separation-progress"
              >
                <div
                  className="mixer-separation-progress-fill"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
              <div className="mixer-separation-row">
                <span data-testid="separation-stage">
                  {separation.stage || "Separating stems…"} · {progressPercent}%
                </span>
                <button
                  type="button"
                  aria-label="Cancel stem separation"
                  onClick={separation.onCancel}
                >
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <>
              <button
                type="button"
                className="mixer-separation-button"
                onClick={separation.onSeparate}
              >
                {separation.hasStems ? "Re-separate" : "Separate stems"}
              </button>
              <p
                className="mixer-separation-hint"
                data-testid="separation-hint"
              >
                {separation.hasStems
                  ? "Stem separation is cached: a re-run is instant."
                  : "Separate into drums, bass, other and vocals. Cached separations are instant."}
              </p>
            </>
          )}
          {separation.error !== null && (
            <p
              className="panel-error"
              role="alert"
              data-testid="separation-error"
            >
              {separation.error}
            </p>
          )}
        </div>
      )}

      {stems.length === 0 ? (
        <p className="panel-empty">Separate stems to mix them.</p>
      ) : (
        <div className="mixer-channels">
          {stems.map((stem) => {
            const channel = state[stem.id] ?? defaultStemMix();
            const audible = isAudible(state, stem.id);
            return (
              <div
                className="mixer-channel"
                key={stem.id}
                data-testid={`mixer-channel-${stem.id}`}
                data-audible={audible}
              >
                <div className="mixer-channel-name">{stem.name}</div>
                <div className="mixer-buttons">
                  <button
                    type="button"
                    aria-label={`Mute ${stem.name}`}
                    aria-pressed={channel.muted}
                    onClick={() => controller.setMuted(stem.id, !channel.muted)}
                  >
                    M
                  </button>
                  <button
                    type="button"
                    aria-label={`Solo ${stem.name}`}
                    aria-pressed={channel.soloed}
                    onClick={() =>
                      controller.setSoloed(stem.id, !channel.soloed)
                    }
                  >
                    S
                  </button>
                </div>
                <label className="mixer-slider">
                  Gain
                  <input
                    type="range"
                    aria-label={`${stem.name} gain`}
                    min={MIN_GAIN_DB}
                    max={MAX_GAIN_DB}
                    step={0.5}
                    value={channel.gainDb}
                    onChange={(event) =>
                      controller.setGain(stem.id, Number(event.target.value))
                    }
                  />
                </label>
                <output
                  className="mixer-value"
                  data-testid={`mixer-gain-${stem.id}`}
                >
                  {formatGainDb(channel.gainDb)}
                </output>
                <label className="mixer-slider">
                  Pan
                  <input
                    type="range"
                    aria-label={`${stem.name} pan`}
                    min={MIN_PAN}
                    max={MAX_PAN}
                    step={0.05}
                    value={channel.pan}
                    onChange={(event) =>
                      controller.setPan(stem.id, Number(event.target.value))
                    }
                  />
                </label>
                <output
                  className="mixer-value"
                  data-testid={`mixer-pan-${stem.id}`}
                >
                  {formatPan(channel.pan)}
                </output>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
