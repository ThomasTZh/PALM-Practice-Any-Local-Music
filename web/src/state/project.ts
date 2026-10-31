import {
  ApiError,
  createStudioApi,
  parseProject,
  type FetchLike,
  type RequestOptions,
  type StudioApi,
} from "../api/client";
import type { AnalysisSnapshot } from "./analysis";
import type { ChordRegion } from "./chords";
import { clampGainDb, clampPan, MIN_GAIN_DB, type MixerState } from "./mixer";
import {
  applyPracticeChange,
  DEFAULT_PRACTICE_STATE,
  type PracticeState,
} from "./practice";
import type { LoopRange } from "./player";
import type { Section } from "./sections";
import type { Grid, Project, Stem } from "./types";

/**
 * The shell's project type: everything the t4 API parser returns plus the
 * practice state, analysis document and server stems the real studio needs.
 * Parsed once, at the HTTP boundary, so App never inspects raw JSON.
 */

export interface StudioStem extends Stem {
  frames: number;
  channels: number;
  sampleRate: number;
}

export interface RestoredPractice {
  state: PracticeState;
  loopRange: LoopRange | null;
  positionSeconds: number;
  mixer: MixerState;
}

export interface StudioProject extends Project {
  revision: number;
  frames: number;
  stems: StudioStem[];
  analysis: AnalysisSnapshot | null;
  chords: ChordRegion[];
  beats: number[];
  bars: number[];
  bpb: number;
  sections: Section[];
  restored: RestoredPractice;
}

export interface ServerSection {
  id: string;
  name: string;
  start_bar: number;
  end_bar: number;
  start_seconds?: number;
  end_seconds?: number;
}

export interface ServerLoop {
  start_frame: number;
  end_frame: number;
  repeat_count: number | null;
  fade: boolean;
}

export interface ServerMixerChannel {
  gain: number;
  muted: boolean;
  solo: boolean;
  pan: number;
}

export interface ServerPracticeState {
  state_version: number;
  sections: ServerSection[];
  loop: ServerLoop | null;
  speed: number;
  pitch_semitones: number;
  position_frame: number;
  mixer: Record<string, ServerMixerChannel>;
}

export interface ShellApi extends StudioApi {
  openProject(
    projectId: string,
    options?: RequestOptions,
  ): Promise<StudioProject>;
  saveState(
    projectId: string,
    state: ServerPracticeState,
    revision?: number,
  ): Promise<number>;
}

type RawRecord = Record<string, unknown>;

const EPSILON = 1e-9;

function recordOf(value: unknown): RawRecord | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as RawRecord;
}

function mustRecord(value: unknown, what: string): RawRecord {
  const record = recordOf(value);
  if (record === null) {
    throw new ApiError(0, `malformed ${what}: expected an object`);
  }
  return record;
}

function textOf(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : null;
}

function numberOf(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function numberArray(value: unknown): number[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter(
      (entry): entry is number =>
        typeof entry === "number" && Number.isFinite(entry),
    )
    .slice()
    .sort((a, b) => a - b);
}

function firstNumber(source: RawRecord | null, keys: string[]): number | null {
  if (source === null) {
    return null;
  }
  for (const key of keys) {
    const value = numberOrNull(source[key]);
    if (value !== null) {
      return value;
    }
  }
  return null;
}

function titleCase(label: string): string {
  return label.length === 0 ? label : label[0].toUpperCase() + label.slice(1);
}

interface RawStemMeta {
  label: string;
  url: string | null;
  frames: number | null;
  channels: number | null;
  sampleRate: number | null;
}

function parseStemRows(value: unknown): RawStemMeta[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const rows: RawStemMeta[] = [];
  value.forEach((entry, index) => {
    const raw = recordOf(entry);
    if (raw === null) {
      return;
    }
    const label =
      textOf(raw.label) ??
      textOf(raw.role) ??
      textOf(raw.id) ??
      `stem-${index + 1}`;
    rows.push({
      label,
      url: textOf(raw.url) ?? textOf(raw.audioUrl) ?? textOf(raw.audio_url),
      frames: firstNumber(raw, ["frames", "frameCount", "frame_count"]),
      channels: firstNumber(raw, ["channels", "channelCount", "channel_count"]),
      sampleRate: firstNumber(raw, ["sampleRate", "sample_rate"]),
    });
  });
  return rows;
}

function parseChordRegions(value: unknown): ChordRegion[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const chords: ChordRegion[] = [];
  for (const entry of value) {
    const raw = recordOf(entry);
    if (raw === null) {
      continue;
    }
    const start = firstNumber(raw, ["startSeconds", "start_seconds"]);
    const end = firstNumber(raw, ["endSeconds", "end_seconds"]);
    const label = textOf(raw.label);
    if (start === null || end === null || label === null || !(end > start)) {
      continue;
    }
    chords.push({ startSeconds: start, endSeconds: end, label });
  }
  return chords;
}

function analysisGrid(
  raw: RawRecord,
  document: RawRecord,
): {
  beats: number[];
  bars: number[];
  bpb: number | null;
  bpm: number | null;
  offset: number;
} {
  const rawGrid = recordOf(raw.grid);
  const docGrid = recordOf(document.grid);
  const analysis = recordOf(document.analysis);
  const beats = numberArray(docGrid?.beats ?? rawGrid?.beats);
  const bars = numberArray(docGrid?.bars ?? rawGrid?.bars);
  return {
    beats,
    bars,
    bpb:
      firstNumber(docGrid, ["bpb", "beatsPerBar", "beats_per_bar"]) ??
      firstNumber(rawGrid, ["bpb"]) ??
      firstNumber(analysis, ["bpb"]) ??
      computeBpb(raw),
    bpm:
      firstNumber(docGrid, ["bpm", "tempo"]) ??
      firstNumber(rawGrid, ["bpm", "tempo"]),
    offset: firstNumber(docGrid, ["offsetSeconds", "offset_seconds"]) ?? 0,
  };
}

function computeBpb(raw: RawRecord): number | null {
  const grid = recordOf(raw.grid);
  const meter = recordOf(grid?.meter);
  const numerator = firstNumber(meter, ["numerator"]);
  return numerator !== null && numerator >= 1 ? Math.round(numerator) : null;
}

/** Bar boundary times, from analysis bars, detected beats or the tempo. */
export function barTimesFromGrid(
  beats: number[],
  bars: number[],
  bpm: number | null,
  bpb: number,
  offsetSeconds: number,
  durationSeconds: number,
): number[] {
  const cleanBars = bars.filter(
    (value) => Number.isFinite(value) && value >= 0,
  );
  if (cleanBars.length > 0) {
    return cleanBars.slice().sort((a, b) => a - b);
  }
  const cleanBeats = beats.filter(
    (value) => Number.isFinite(value) && value >= 0,
  );
  const count = Math.max(1, Math.round(bpb));
  if (cleanBeats.length > 0) {
    const boundaries: number[] = [];
    for (let index = 0; index < cleanBeats.length; index += count) {
      boundaries.push(cleanBeats[index]);
    }
    return boundaries;
  }
  if (bpm === null || !(bpm > 0)) {
    return [];
  }
  const barSeconds = (60 / bpm) * count;
  const duration =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? durationSeconds
      : Infinity;
  const boundaries: number[] = [];
  for (
    let time = Math.max(0, offsetSeconds);
    time < duration - EPSILON && boundaries.length < 10_000;
    time += barSeconds
  ) {
    boundaries.push(Number(time.toFixed(9)));
  }
  return boundaries;
}

export function barIndexForSeconds(seconds: number, bars: number[]): number {
  if (bars.length === 0) {
    return 0;
  }
  let index = 0;
  for (let candidate = 0; candidate < bars.length; candidate += 1) {
    if (bars[candidate] <= seconds + EPSILON) {
      index = candidate;
    } else {
      break;
    }
  }
  return index;
}

/** Reads sections from the document, preferring exact seconds when stored. */
export function sectionsFromDocument(
  document: RawRecord,
  bars: number[],
  bpm: number | null,
  bpb: number,
  offsetSeconds: number,
  durationSeconds: number,
): Section[] {
  const rawSections = Array.isArray(document.sections) ? document.sections : [];
  const barTimes = barTimesFromGrid(
    [],
    bars,
    bpm,
    bpb,
    offsetSeconds,
    durationSeconds,
  );
  const sections: Section[] = [];
  for (const entry of rawSections) {
    const raw = recordOf(entry);
    if (raw === null) {
      continue;
    }
    const id = textOf(raw.id);
    if (id === null) {
      continue;
    }
    const startBar = Math.max(0, Math.round(numberOf(raw.start_bar, 0)));
    const endBar = Math.max(
      startBar,
      Math.round(numberOf(raw.end_bar, startBar)),
    );
    const fallbackStart = barTimes[startBar] ?? 0;
    const fallbackEnd =
      barTimes[endBar] ?? barTimes[startBar + 1] ?? durationSeconds;
    const startSeconds = Math.max(
      0,
      numberOrNull(raw.start_seconds) ?? fallbackStart,
    );
    const endSeconds = Math.min(
      durationSeconds,
      numberOrNull(raw.end_seconds) ?? fallbackEnd,
    );
    if (!(endSeconds > startSeconds)) {
      continue;
    }
    sections.push({
      id,
      name: textOf(raw.name) ?? "Section",
      startSeconds,
      endSeconds,
    });
  }
  return sections;
}

export function mixerFromServer(value: unknown): MixerState {
  const raw = recordOf(value);
  const mixer: MixerState = {};
  if (raw === null) {
    return mixer;
  }
  for (const [channelId, entry] of Object.entries(raw)) {
    const channel = recordOf(entry);
    if (channel === null) {
      continue;
    }
    const linearGain = Math.max(0, numberOf(channel.gain, 1));
    mixer[channelId] = {
      gainDb: clampGainDb(
        linearGain > 0 ? 20 * Math.log10(linearGain) : MIN_GAIN_DB,
      ),
      pan: clampPan(numberOf(channel.pan, 0)),
      muted: channel.muted === true || channel.mute === true,
      soloed: channel.solo === true || channel.soloed === true,
    };
  }
  return mixer;
}

export function mixerToServer(
  mixer: MixerState,
): Record<string, ServerMixerChannel> {
  const server: Record<string, ServerMixerChannel> = {};
  for (const [channelId, channel] of Object.entries(mixer)) {
    const gainDb = clampGainDb(channel.gainDb);
    server[channelId] = {
      gain: Number(Math.pow(10, gainDb / 20).toFixed(6)),
      muted: channel.muted,
      solo: channel.soloed,
      pan: clampPan(channel.pan),
    };
  }
  return server;
}

export function practiceFromDocument(
  document: RawRecord,
  durationSeconds: number,
  sampleRate: number,
): RestoredPractice {
  const safeSampleRate = sampleRate > 0 ? sampleRate : 48_000;
  const loopRaw = recordOf(document.loop);
  const loopStart = firstNumber(loopRaw, ["start_frame", "startFrame"]);
  const loopEnd = firstNumber(loopRaw, ["end_frame", "endFrame"]);
  const loopRange: LoopRange | null =
    loopStart !== null && loopEnd !== null && loopEnd > loopStart
      ? {
          startSeconds: loopStart / safeSampleRate,
          endSeconds: Math.min(durationSeconds, loopEnd / safeSampleRate),
        }
      : null;
  const positionFrame = Math.max(
    0,
    Math.round(numberOf(document.position_frame, 0)),
  );
  const speed = numberOf(document.speed, 1);
  const pitch = numberOf(document.pitch_semitones, 0);
  const state = applyPracticeChange(
    { ...DEFAULT_PRACTICE_STATE },
    {
      speed,
      pitchSemitones: pitch,
      loopEnabled: loopRange !== null,
    },
  );
  return {
    state,
    loopRange,
    positionSeconds: Math.max(
      0,
      Math.min(durationSeconds, positionFrame / safeSampleRate),
    ),
    mixer: mixerFromServer(document.mixer),
  };
}

/** Bar indices for saving; exact seconds ride along as extra fields. */
export function sectionsToServer(
  sections: Section[],
  bars: number[],
): ServerSection[] {
  return sections.map((section) => {
    const startBar = barIndexForSeconds(section.startSeconds, bars);
    let endBar = barIndexForSeconds(section.endSeconds, bars);
    if (endBar <= startBar) {
      endBar = startBar + 1;
    }
    return {
      id: section.id,
      name: section.name,
      start_bar: startBar,
      end_bar: endBar,
      start_seconds: Number(section.startSeconds.toFixed(6)),
      end_seconds: Number(section.endSeconds.toFixed(6)),
    };
  });
}

export interface BuildServerStateInput {
  sections: Section[];
  bars: number[];
  sampleRate: number;
  positionSeconds: number;
  loopRange: LoopRange | null;
  practice: PracticeState;
  mixer: MixerState;
}

export function buildServerState(
  input: BuildServerStateInput,
): ServerPracticeState {
  const sampleRate = input.sampleRate > 0 ? input.sampleRate : 48_000;
  const loop =
    input.loopRange !== null &&
    input.loopRange.endSeconds > input.loopRange.startSeconds
      ? {
          start_frame: Math.round(input.loopRange.startSeconds * sampleRate),
          end_frame: Math.round(input.loopRange.endSeconds * sampleRate),
          repeat_count: null,
          fade: true,
        }
      : null;
  return {
    state_version: 1,
    sections: sectionsToServer(input.sections, input.bars),
    loop,
    speed: input.practice.speed,
    pitch_semitones: input.practice.pitchSemitones,
    position_frame: Math.max(0, Math.round(input.positionSeconds * sampleRate)),
    mixer: mixerToServer(input.mixer),
  };
}

export function parseStudioProject(value: unknown): StudioProject {
  const wrapped = recordOf(value)?.project;
  const raw = mustRecord(wrapped ?? value, "project");
  const stemMeta = parseStemRows(raw.stems);
  const normalizedStems = stemMeta.map((meta) => ({
    id: meta.label,
    name: titleCase(meta.label),
    role: meta.label,
    audioUrl: meta.url ?? undefined,
    peaksAssetId: meta.label,
  }));
  const base = parseProject({ ...raw, stems: normalizedStems });
  const document = recordOf(raw.document) ?? {};
  const grid = analysisGrid(raw, document);
  const bpb = grid.bpb ?? base.grid?.meter.numerator ?? 4;
  const bpm = grid.bpm ?? base.grid?.bpm ?? null;
  const key = base.key ?? textOf(document.key) ?? null;
  const chords = parseChordRegions(document.chords ?? raw.chords);
  const analysisMeta = recordOf(document.analysis);
  const analysis: AnalysisSnapshot | null =
    grid.beats.length > 0 || chords.length > 0 || analysisMeta !== null
      ? {
          bpb,
          bpm,
          key,
          chords,
          beats: grid.beats,
          bars: grid.bars,
          cached: analysisMeta?.cached === true,
        }
      : null;
  const sampleRate = base.asset.sampleRate;
  const durationSeconds = base.durationSeconds;
  const frames = Math.max(
    0,
    Math.round(
      firstNumber(recordOf(raw.asset), ["frames"]) ??
        firstNumber(recordOf(raw.audio), ["frames"]) ??
        durationSeconds * sampleRate,
    ),
  );
  const stems: StudioStem[] = base.stems.map((stem, index) => {
    const meta = stemMeta[index];
    return {
      ...stem,
      frames: Math.max(0, Math.round(meta?.frames ?? frames)),
      channels: Math.max(1, Math.round(meta?.channels ?? base.asset.channels)),
      sampleRate: Math.max(1, Math.round(meta?.sampleRate ?? sampleRate)),
    };
  });
  const barTimes = barTimesFromGrid(
    grid.beats,
    grid.bars,
    bpm,
    bpb,
    grid.offset,
    durationSeconds,
  );
  const sections = sectionsFromDocument(
    document,
    grid.bars.length > 0 ? grid.bars : barTimes,
    bpm,
    bpb,
    grid.offset,
    durationSeconds,
  );
  const restored = practiceFromDocument(document, durationSeconds, sampleRate);
  const normalizedGrid: Grid | null =
    base.grid ??
    (bpm !== null
      ? {
          bpm,
          meter: { numerator: bpb, denominator: 4 },
          offsetSeconds: grid.offset,
        }
      : null);
  return {
    ...base,
    grid: normalizedGrid,
    revision: Math.max(1, Math.round(numberOf(raw.revision, 1))),
    frames,
    stems,
    analysis,
    chords,
    beats: grid.beats,
    bars: grid.bars,
    bpb,
    sections,
    restored,
  };
}

export interface ShellApiOptions {
  baseUrl?: string;
  fetchImpl?: FetchLike;
}

async function httpDetail(response: Response): Promise<string> {
  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.text();
    if (body.trim().length > 0) {
      try {
        const parsed = recordOf(JSON.parse(body));
        detail =
          textOf(parsed?.detail) ?? textOf(parsed?.message) ?? body.trim();
      } catch {
        detail = body.trim();
      }
    }
  } catch {
    // The status alone is still a usable message.
  }
  return detail;
}

function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name: string }).name === "AbortError"
  );
}

/**
 * Server API for the shell. Library/import/peaks come from the t4 client;
 * project opening is parsed here because the real payload carries stems,
 * analysis chords and persisted practice state that the t4 parser predates.
 */
export function createShellApi(options: ShellApiOptions = {}): ShellApi {
  const base = createStudioApi(options);
  const prefix = (options.baseUrl ?? "").replace(/\/+$/, "");
  const doFetch: FetchLike =
    options.fetchImpl ?? ((input, init) => fetch(input, init));

  async function request(path: string, init?: RequestInit): Promise<unknown> {
    let response: Response;
    try {
      response = await doFetch(`${prefix}${path}`, init);
    } catch (error) {
      if (isAbort(error)) {
        throw error;
      }
      const message = error instanceof Error ? error.message : String(error);
      throw new ApiError(0, `cannot reach the studio server: ${message}`);
    }
    if (!response.ok) {
      throw new ApiError(response.status, await httpDetail(response));
    }
    try {
      return await response.json();
    } catch {
      throw new ApiError(response.status, "malformed response: not JSON");
    }
  }

  async function loadProject(
    projectId: string,
    requestOptions: { signal?: AbortSignal } = {},
  ): Promise<StudioProject> {
    const payload = await request(
      `/api/projects/${encodeURIComponent(projectId)}`,
      requestOptions.signal ? { signal: requestOptions.signal } : undefined,
    );
    return parseStudioProject(payload);
  }

  async function putState(
    projectId: string,
    state: ServerPracticeState,
    revision?: number,
  ): Promise<number> {
    const payload = await request(
      `/api/projects/${encodeURIComponent(projectId)}/state`,
      {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(
          revision === undefined ? { state } : { state, revision },
        ),
      },
    );
    const record = recordOf(payload);
    const savedRevision = firstNumber(record?.project as RawRecord | null, [
      "revision",
    ]);
    return Math.max(
      1,
      Math.round(
        savedRevision ?? firstNumber(record, ["revision"]) ?? revision ?? 1,
      ),
    );
  }

  return {
    listLibrary: base.listLibrary,
    importRecording: base.importRecording,
    fetchPeaks: base.fetchPeaks,
    openProject: loadProject,

    async saveState(projectId, state, revision) {
      try {
        return await putState(projectId, state, revision);
      } catch (error) {
        // Analysis and separation jobs bump the server revision. Refresh once
        // and retry so a stale shell revision does not drop a section save.
        if (!(error instanceof ApiError) || error.status !== 409) {
          throw error;
        }
        const refreshed = await loadProject(projectId);
        return await putState(projectId, state, refreshed.revision);
      }
    },
  };
}
