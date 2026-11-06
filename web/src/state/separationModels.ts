import type { SeparationModel, SeparationModelsResponse } from "../api/types";

export const DEFAULT_SEPARATION_MODEL_ID = "htdemucs_ft";

/** The bundled Demucs row, used before the model endpoint answers and by fakes. */
export const HTDEMUCS_MODEL: SeparationModel = {
  id: DEFAULT_SEPARATION_MODEL_ID,
  name: "Demucs htdemucs_ft",
  engine: "demucs",
  engine_command:
    "analysis/.venv/bin/python analysis/separate_track.py --bundle-dir models/htdemucs_ft",
  labels: ["drums", "bass", "other", "vocals"],
  sample_rate: 44100,
  size_bytes: 336565084,
  source_url:
    "https://github.com/facebookresearch/demucs/tree/b1ea86542ca11d7695cba4238909f461752283b5",
  license: "MIT code; htdemucs_ft weights are research use",
  bundled: true,
  install_dir: "models/htdemucs_ft",
  install_command: "bundled with the checkout",
  checkpoint_manifest: "analysis/checkpoints.json",
  config_name: "htdemucs_ft.yaml",
  status: "installed",
  installed: true,
  model_dir: "models/htdemucs_ft",
  detail: "",
  default: true,
  metrics: {
    device: "cpu",
    fixture_seconds: 8,
    wall_seconds: 19.24,
    child_seconds: 18.85,
    source: "t8 measured run",
  },
  file_states: [],
};

export function defaultSeparationModels(): SeparationModelsResponse {
  return { default: DEFAULT_SEPARATION_MODEL_ID, models: [HTDEMUCS_MODEL] };
}

/** Pick the preferred installed model, else the server default, else Demucs. */
export function resolveSeparationModelId(
  models: readonly SeparationModel[],
  preferred: string | null | undefined,
): string {
  const installed = models.filter((model) => model.installed);
  if (preferred !== null && preferred !== undefined) {
    const match = installed.find((model) => model.id === preferred);
    if (match !== undefined) {
      return match.id;
    }
  }
  const fallback =
    installed.find((model) => model.id === DEFAULT_SEPARATION_MODEL_ID) ??
    installed.find((model) => model.default) ??
    installed[0];
  return fallback?.id ?? DEFAULT_SEPARATION_MODEL_ID;
}

export function separationModelName(
  models: readonly SeparationModel[],
  modelId: string | null | undefined,
): string | null {
  if (modelId === null || modelId === undefined) {
    return null;
  }
  const name = models.find((model) => model.id === modelId)?.name;
  return name?.replace(/\s*\(bundled\)\s*$/i, "") ?? modelId;
}

export function formatModelSize(sizeBytes: number): string {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) {
    return "unknown size";
  }
  const gib = sizeBytes / 1024 ** 3;
  if (gib >= 1) {
    return `${gib.toFixed(2)} GB`;
  }
  return `${Math.round(sizeBytes / 1024 ** 2)} MB`;
}

/** CPU estimate for the current song from the measured 8 s run. */
export function modelCpuEstimate(
  model: SeparationModel,
  songSeconds: number,
): string | null {
  if (model.engine !== "msst") {
    return null;
  }
  const wall = model.metrics.wall_seconds;
  const child = model.metrics.child_seconds;
  const fixture = model.metrics.fixture_seconds;
  if (
    typeof wall !== "number" ||
    typeof fixture !== "number" ||
    !(wall > 0) ||
    !(fixture > 0) ||
    !(songSeconds > 0)
  ) {
    return null;
  }
  const wallMinutes = ((wall / fixture) * songSeconds) / 60;
  const childMinutes =
    typeof child === "number" && child > 0
      ? ((child / fixture) * songSeconds) / 60
      : wallMinutes;
  const low = Math.round(Math.min(wallMinutes, childMinutes));
  const high = Math.round(Math.max(wallMinutes, childMinutes));
  const label = low === high ? `~${high}` : `~${low}-${high}`;
  const songLabel =
    songSeconds >= 60
      ? `${Math.round(songSeconds / 60)} min`
      : `${Math.round(songSeconds)} s`;
  return `CPU ${label} min for this ${songLabel} song`;
}
