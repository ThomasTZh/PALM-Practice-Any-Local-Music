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

export interface MixerStem {
  id: string;
  name: string;
  role?: string;
}

export interface MixerPanelProps {
  stems: MixerStem[];
  controller: MixerController;
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
export function MixerPanel({ stems, controller }: MixerPanelProps) {
  const state = useMixerState(controller);
  const soloActive = anySoloed(state);

  return (
    <section className="mixer" data-testid="mixer" aria-label="Stem mixer">
      <header className="panel-header">
        <h2>Mixer</h2>
        {soloActive && <span className="panel-badge">Solo</span>}
      </header>

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
