import type { SeparationModel } from "../api/types";
import { formatModelSize } from "./separationModels";

export type SetupJobStatus =
  "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface SetupJobState {
  id: string;
  status: SetupJobStatus;
  progress: number;
  message: string;
  error: string | null;
}

export interface SetupCheck {
  ok: boolean;
  status: string;
  detail: string;
}

export interface SetupTool {
  name?: string;
  installed: boolean;
  path: string;
  license: string;
}

export interface SetupMediaTool {
  installed: boolean;
  path: string;
  version?: string;
  build?: string;
  license?: string;
  source_url?: string;
}

export interface SetupEnvironment {
  variant: "cpu" | "cuda";
  installed: boolean;
  path: string;
  python: string;
  project: string;
  uv: string;
}

export interface SetupReadiness {
  ready: boolean;
  checks_ok: boolean;
  tools_ready: boolean;
  media_tools_ready: boolean;
  environment_ready: boolean;
  model_ready: boolean;
  requires_model_choice: boolean;
}

export interface SetupStatus {
  mode: string;
  platform?: string;
  ready: boolean;
  skipped: boolean;
  requiresModelChoice: boolean;
  roots: Record<string, string>;
  checks: Record<string, SetupCheck>;
  tools: Record<string, SetupTool>;
  mediaTools: Record<string, SetupMediaTool>;
  mediaToolsReady: boolean;
  environmentVariants: Array<"cpu" | "cuda">;
  environments: Record<string, SetupEnvironment>;
  models: SeparationModel[];
  readiness: SetupReadiness;
  registryError: string | null;
  setupComplete: boolean;
}

export interface SetupClient {
  status(options?: { signal?: AbortSignal }): Promise<SetupStatus>;
  skip(skip?: boolean): Promise<SetupStatus>;
  startTools(consent: boolean): Promise<SetupJobState>;
  startMediaTools(consent: boolean): Promise<SetupJobState>;
  startEnvironment(
    variant: "cpu" | "cuda",
    consent?: boolean,
  ): Promise<SetupJobState>;
  startModels(
    modelIds: string[],
    acceptedModelIds: string[] | boolean,
  ): Promise<SetupJobState>;
  job(jobId: string): Promise<SetupJobState>;
  cancel(jobId: string): Promise<SetupJobState>;
}

export interface SetupGates {
  canImport: boolean;
  canAnalyze: boolean;
  canSeparate: boolean;
  importReason: string | null;
  analyzeReason: string | null;
  separateReason: string | null;
}

export interface LicenceLink {
  licenceUrl: string;
  sourceUrl: string;
}

const TOOL_LICENCE_LINKS: Record<string, LicenceLink> = {
  sonic_visualiser: {
    licenceUrl: "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html",
    sourceUrl: "https://github.com/sonic-visualiser/sonic-visualiser",
  },
  vamp_plugin_pack: {
    licenceUrl: "https://www.gnu.org/licenses/agpl-3.0.html",
    sourceUrl: "https://github.com/c4dm/qm-vamp-plugins",
  },
};

const MODEL_LICENCE_URLS: Record<string, string> = {
  htdemucs_ft: "https://github.com/facebookresearch/demucs/blob/main/LICENSE",
  "scnet-xl-ihf":
    "https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/main/LICENSE",
  "bs-roformer-sw": "https://huggingface.co/FractalSurfer/BS-RoFormer-SW-6stem",
};

export function toolLicenceLink(toolId: string): LicenceLink {
  return (
    TOOL_LICENCE_LINKS[toolId] ?? {
      licenceUrl: "https://www.gnu.org/licenses/",
      sourceUrl: "https://www.gnu.org/licenses/",
    }
  );
}

export function modelLicenceLink(model: SeparationModel): LicenceLink {
  return {
    licenceUrl: MODEL_LICENCE_URLS[model.id] ?? model.source_url,
    sourceUrl: model.source_url || MODEL_LICENCE_URLS[model.id] || "",
  };
}

export interface BundledComponent {
  id: string;
  name: string;
  version: string;
  licence: string;
  licenceUrl: string;
  sourceUrl: string;
  licenceTextKeys: LicenceTextKey[];
}

const LICENCE_URLS: Record<LicenceTextKey, string> = {
  "GPL-2.0": "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html",
  "GPL-3.0": "https://www.gnu.org/licenses/gpl-3.0.html",
  "AGPL-3.0": "https://www.gnu.org/licenses/agpl-3.0.html",
  "LGPL-2.1": "https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html",
  MIT: "https://opensource.org/license/mit",
  "Apache-2.0": "https://www.apache.org/licenses/LICENSE-2.0",
  "BSD-3-Clause": "https://opensource.org/license/bsd-3-clause",
  "PSF-2.0": "https://docs.python.org/3/license.html",
};

function pypi(
  name: string,
  version: string,
  licence: string,
  licenceKey: LicenceTextKey,
): BundledComponent {
  return {
    id: `python-${name}`,
    name,
    version,
    licence,
    licenceUrl: LICENCE_URLS[licenceKey],
    sourceUrl: `https://pypi.org/project/${name}/${version}/`,
    licenceTextKeys: [licenceKey],
  };
}

/** Third-party software already included in the portable package. */
export function setupBundledComponents(): BundledComponent[] {
  return [
    {
      id: "python",
      name: "CPython (python-build-standalone)",
      version: "3.11.15",
      licence: "PSF-2.0",
      licenceUrl: LICENCE_URLS["PSF-2.0"],
      sourceUrl:
        "https://github.com/astral-sh/python-build-standalone/releases/tag/20260728",
      licenceTextKeys: ["PSF-2.0"],
    },
    {
      id: "uv",
      name: "uv",
      version: "0.12.0",
      licence: "MIT OR Apache-2.0",
      licenceUrl: "https://github.com/astral-sh/uv/blob/0.12.0/LICENSE-MIT",
      sourceUrl: "https://github.com/astral-sh/uv/releases/tag/0.12.0",
      licenceTextKeys: ["MIT", "Apache-2.0"],
    },
    pypi("fastapi", "0.142.0", "MIT", "MIT"),
    pypi("uvicorn", "0.54.0", "BSD-3-Clause", "BSD-3-Clause"),
    pypi("pydantic", "2.13.5", "MIT", "MIT"),
    pypi("pydantic-core", "2.46.5", "MIT", "MIT"),
    pypi("pydantic-settings", "2.15.0", "MIT", "MIT"),
    pypi("starlette", "1.10.0", "BSD-3-Clause", "BSD-3-Clause"),
    pypi("numpy", "2.4.6", "BSD-3-Clause", "BSD-3-Clause"),
    pypi("psutil", "7.2.2", "BSD-3-Clause", "BSD-3-Clause"),
    pypi("platformdirs", "4.12.1", "MIT", "MIT"),
    pypi("click", "8.5.1", "BSD-3-Clause", "BSD-3-Clause"),
    pypi("h11", "0.16.0", "MIT", "MIT"),
    pypi("idna", "3.20", "BSD-3-Clause", "BSD-3-Clause"),
    pypi("anyio", "4.16.0", "MIT", "MIT"),
    pypi("annotated-doc", "0.0.5", "MIT", "MIT"),
    pypi("annotated-types", "0.8.0", "MIT", "MIT"),
    pypi("opentelemetry-api", "1.45.2", "Apache-2.0", "Apache-2.0"),
    pypi("python-dotenv", "1.2.4", "BSD-3-Clause", "BSD-3-Clause"),
    pypi("typing-extensions", "4.16.0", "PSF-2.0", "PSF-2.0"),
    pypi("typing-inspection", "0.4.5", "MIT", "MIT"),
    {
      id: "react",
      name: "React",
      version: "19.3.0",
      licence: "MIT",
      licenceUrl: LICENCE_URLS.MIT,
      sourceUrl: "https://github.com/facebook/react/tree/v19.3.0",
      licenceTextKeys: ["MIT"],
    },
    {
      id: "react-dom",
      name: "React DOM",
      version: "19.3.0",
      licence: "MIT",
      licenceUrl: LICENCE_URLS.MIT,
      sourceUrl: "https://github.com/facebook/react/tree/v19.3.0",
      licenceTextKeys: ["MIT"],
    },
  ];
}

const ENVIRONMENT_ESTIMATES: Record<"cpu" | "cuda", string> = {
  cpu: "~500 MB download",
  cuda: "~3.5 GB download",
};

export function environmentEstimate(variant: "cpu" | "cuda"): string {
  return ENVIRONMENT_ESTIMATES[variant];
}

export type LicenceTextKey =
  | "GPL-2.0"
  | "GPL-3.0"
  | "AGPL-3.0"
  | "LGPL-2.1"
  | "MIT"
  | "Apache-2.0"
  | "BSD-3-Clause"
  | "PSF-2.0";

export interface LicenceComponent {
  id: string;
  group: "media" | "tools" | "environment" | "model";
  name: string;
  version: string;
  licence: string;
  licenceUrl: string;
  sourceUrl: string;
  size: string;
  required: boolean;
  requirementLabel: string;
  licenceTextKeys: LicenceTextKey[];
}

export type SetupPlatform = "windows" | "macos" | "linux";

interface MediaPin {
  tool: "ffmpeg" | "ffprobe";
  version: string;
  licence: string;
  sourceUrl: string;
  size: string;
}

const MEDIA_PINS: Record<SetupPlatform, MediaPin[]> = {
  linux: [
    {
      tool: "ffmpeg",
      version: "9.0.2",
      licence: "GPL-3.0-or-later",
      sourceUrl: "https://ffmpeg.martin-riedl.de/",
      size: "32 MB",
    },
    {
      tool: "ffprobe",
      version: "9.0.2",
      licence: "GPL-3.0-or-later",
      sourceUrl: "https://ffmpeg.martin-riedl.de/",
      size: "32 MB",
    },
  ],
  macos: [
    {
      tool: "ffmpeg",
      version: "9.0.2",
      licence: "GPL-3.0-or-later",
      sourceUrl: "https://ffmpeg.martin-riedl.de/",
      size: "27 MB",
    },
    {
      tool: "ffprobe",
      version: "9.0.2",
      licence: "GPL-3.0-or-later",
      sourceUrl: "https://ffmpeg.martin-riedl.de/",
      size: "27 MB",
    },
  ],
  windows: [
    {
      tool: "ffmpeg",
      version: "8.1.2",
      licence: "GPL-3.0-or-later",
      sourceUrl: "https://www.gyan.dev/ffmpeg/builds/",
      size: "105 MB",
    },
    {
      tool: "ffprobe",
      version: "8.1.2",
      licence: "GPL-3.0-or-later",
      sourceUrl: "https://www.gyan.dev/ffmpeg/builds/",
      size: "105 MB",
    },
  ],
};

export function setupPlatform(): SetupPlatform {
  if (typeof navigator === "undefined") return "linux";
  const label = `${navigator.platform} ${navigator.userAgent}`.toLowerCase();
  if (label.includes("win")) return "windows";
  if (label.includes("mac")) return "macos";
  return "linux";
}

function environmentComponents(status: SetupStatus): LicenceComponent[] {
  const variants = status.environmentVariants.length
    ? status.environmentVariants
    : (Object.keys(status.environments) as Array<"cpu" | "cuda">);
  return variants.map((variant) => ({
    id: `environment-${variant}`,
    group: "environment",
    name: `${variant.toUpperCase()} inference environment`,
    version:
      variant === "cpu"
        ? "PyTorch 2.9.1 CPU, MSST 0.1.0"
        : "PyTorch 2.9.1 CUDA 12.8, MSST 0.1.0",
    licence: "BSD-3-Clause, MIT and Apache-2.0 dependencies",
    licenceUrl: "https://github.com/pytorch/pytorch/blob/main/LICENSE",
    sourceUrl:
      variant === "cpu"
        ? "https://download.pytorch.org/whl/cpu"
        : "https://download.pytorch.org/whl/cu128",
    size: environmentEstimate(variant),
    required: variant === "cpu",
    requirementLabel: variant === "cpu" ? "Required" : "Optional",
    licenceTextKeys: ["BSD-3-Clause", "MIT", "Apache-2.0"] as LicenceTextKey[],
  }));
}

/** Every downloaded component shown before the first download can start. */
export function setupLicenceComponents(
  status: SetupStatus,
): LicenceComponent[] {
  const platform: SetupPlatform =
    status.platform === "windows" ||
    status.platform === "macos" ||
    status.platform === "linux"
      ? status.platform
      : setupPlatform();
  const media = MEDIA_PINS[platform].map((pin): LicenceComponent => {
    const installed = status.mediaTools[pin.tool];
    return {
      id: `media-${pin.tool}`,
      group: "media",
      name: pin.tool,
      version: installed?.version ?? pin.version,
      licence: installed?.license ?? pin.licence,
      licenceUrl: "https://www.gnu.org/licenses/gpl-3.0.html",
      sourceUrl: installed?.source_url ?? pin.sourceUrl,
      size: pin.size,
      required: true,
      requirementLabel: "Required",
      licenceTextKeys: ["GPL-3.0"],
    };
  });
  const tools: LicenceComponent[] = [];
  if (platform !== "windows" || Object.keys(status.tools).length > 0) {
    tools.push(
      {
        id: "tool-sonic",
        group: "tools",
        name:
          platform === "linux" ? "Sonic Visualiser / Piper" : "Sonic Annotator",
        version: "1.7",
        licence: "GPL-2.0-or-later",
        licenceUrl: "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html",
        sourceUrl: "https://github.com/sonic-visualiser/sonic-annotator",
        size: platform === "linux" ? "bundled launcher" : "6-11 MB",
        required: false,
        requirementLabel:
          platform === "windows"
            ? "Bundled with PALM"
            : "Optional (needed for analysis)",
        licenceTextKeys: ["GPL-2.0"],
      },
      {
        id: "tool-vamp",
        group: "tools",
        name: "Vamp Plugin Pack",
        version: "2.0",
        licence: "AGPL-3.0 (pack); individual plugins GPL/AGPL",
        licenceUrl: "https://www.gnu.org/licenses/agpl-3.0.html",
        sourceUrl: "https://github.com/vamp-plugins/vamp-plugin-pack",
        size: "33-47 MB",
        required: false,
        requirementLabel:
          platform === "windows"
            ? "Bundled with PALM"
            : "Optional (needed for analysis)",
        licenceTextKeys: ["AGPL-3.0"],
      },
    );
  }
  const models = status.models.map((model): LicenceComponent => ({
    id: `model-${model.id}`,
    group: "model",
    name: model.name,
    version: `${model.id} (${model.engine.toUpperCase()})`,
    licence: model.license,
    licenceUrl: modelLicenceLink(model).licenceUrl,
    sourceUrl: model.source_url || modelLicenceLink(model).licenceUrl,
    size: formatModelSize(model.size_bytes),
    required: false,
    requirementLabel: "Optional (choose at least one)",
    licenceTextKeys:
      model.id === "bs-roformer-sw" ? [] : (["MIT"] as LicenceTextKey[]),
  }));
  return [...media, ...tools, ...environmentComponents(status), ...models];
}

/**
 * The server exposes readiness booleans; the UI derives per-operation gates so
 * optional tools do not block importing, while analysis needs the Vamp tools
 * and separation additionally needs an installed model.
 */
export function setupGates(status: SetupStatus | null): SetupGates {
  if (status === null) {
    return {
      canImport: false,
      canAnalyze: false,
      canSeparate: false,
      importReason: "Checking studio setup…",
      analyzeReason: "Checking studio setup…",
      separateReason: "Checking studio setup…",
    };
  }
  const coreChecksOk = Object.entries(status.checks)
    .filter(([name]) => name !== "ffmpeg" && name !== "ffprobe")
    .every(([, check]) => check.ok);
  const mediaReady =
    status.readiness.media_tools_ready ??
    (status.checks.ffmpeg?.ok === true && status.checks.ffprobe?.ok === true);
  const toolsReady = status.readiness.tools_ready;
  const environmentReady = status.readiness.environment_ready;
  const modelReady = status.readiness.model_ready;
  const canImport = coreChecksOk && mediaReady;
  const windowsAnalysisBlocked =
    status.platform === "windows" &&
    Object.keys(status.tools ?? {}).length === 0;
  const canAnalyze =
    !windowsAnalysisBlocked &&
    coreChecksOk &&
    mediaReady &&
    toolsReady &&
    environmentReady;
  const canSeparate =
    coreChecksOk && mediaReady && environmentReady && modelReady;
  return {
    canImport,
    canAnalyze,
    canSeparate,
    importReason: canImport
      ? null
      : !coreChecksOk
        ? "Importing needs the system checks to pass. Open Setup to see what is missing."
        : "Importing needs the managed FFmpeg/FFprobe media tools. Open Setup to install them.",
    analyzeReason: canAnalyze
      ? null
      : !coreChecksOk
        ? "Analysis needs the system checks to pass. Open Setup to get the studio ready."
        : !mediaReady
          ? "Analysis needs the managed FFmpeg/FFprobe media tools. Open Setup to install them."
          : !toolsReady
            ? "Analysis needs the bundled Sonic Annotator and Vamp plugin payload. Reinstall PALM; no separate plugin install is required."
            : "Analysis needs the CPU or CUDA inference environment. Open Setup to create it.",
    separateReason: canSeparate
      ? null
      : !coreChecksOk
        ? "Stem separation needs the system checks to pass. Open Setup to see what is missing."
        : !mediaReady
          ? "Stem separation needs the managed FFmpeg/FFprobe media tools. Open Setup to install them."
          : !environmentReady
            ? "Stem separation needs the CPU or CUDA inference environment. Open Setup to create it."
            : !modelReady
              ? "Stem separation needs a separation model. Open Setup to install one."
              : "Stem separation needs the optional analysis tools. Open Setup to install them.",
  };
}

export function installedSetupModels(
  status: SetupStatus | null,
): SeparationModel[] {
  return (status?.models ?? []).filter((model) => model.installed);
}
