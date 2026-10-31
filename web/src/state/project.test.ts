import { describe, expect, it } from "vitest";

import {
  barIndexForSeconds,
  barTimesFromGrid,
  buildServerState,
  createShellApi,
  mixerFromServer,
  mixerToServer,
  parseStudioProject,
  practiceFromDocument,
  sectionsFromDocument,
  sectionsToServer,
  type ServerPracticeState,
} from "./project";
import { DEFAULT_PRACTICE_STATE } from "./practice";
import { createInitialMixerState, type MixerState } from "./mixer";

const RAW = {
  id: "p1",
  name: "Demo take",
  revision: 3,
  title: "Demo take",
  durationSeconds: 8,
  duration_seconds: 8,
  asset: {
    id: "a1",
    sampleRate: 48000,
    sample_rate: 48000,
    channels: 2,
    frames: 384000,
  },
  grid: {
    bpm: 120,
    bpb: 4,
    meter: { numerator: 4, denominator: 4 },
    offsetSeconds: 0,
    beats: Array.from({ length: 16 }, (_, index) => index * 0.5),
    bars: [0, 2, 4, 6],
  },
  key: "C major",
  stems: [
    {
      label: "drums",
      url: "/api/projects/p1/stems/drums/pcm",
      frames: 384000,
      channels: 2,
      sampleRate: 48000,
    },
    {
      label: "bass",
      url: "/api/projects/p1/stems/bass/pcm",
      frames: 384000,
      channels: 2,
      sampleRate: 48000,
    },
    {
      label: "other",
      url: "/api/projects/p1/stems/other/pcm",
      frames: 384000,
      channels: 2,
      sampleRate: 48000,
    },
    {
      label: "vocals",
      url: "/api/projects/p1/stems/vocals/pcm",
      frames: 384000,
      channels: 2,
      sampleRate: 48000,
    },
  ],
  document: {
    grid: {
      bpm: 120,
      bpb: 4,
      meter: { numerator: 4, denominator: 4 },
      offsetSeconds: 0,
      beats: Array.from({ length: 16 }, (_, index) => index * 0.5),
      bars: [0, 2, 4, 6],
    },
    key: "C major",
    chords: [
      { start_seconds: 0, end_seconds: 2, label: "C:maj" },
      { start_seconds: 2, end_seconds: 4, label: "A:min7" },
    ],
    analysis: { bpb: 4, bpm: 120, key: "C major", cached: true },
    sections: [{ id: "s1", name: "Intro", start_bar: 0, end_bar: 1 }],
    speed: 0.75,
    pitch_semitones: -2,
    position_frame: 24000,
    loop: {
      start_frame: 48000,
      end_frame: 96000,
      repeat_count: null,
      fade: true,
    },
    mixer: {
      bass: { gain: 0.5, muted: false, solo: false, pan: -0.5 },
      mix: { gain: 1, muted: true, solo: false, pan: 0 },
    },
  },
};

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

describe("parseStudioProject", () => {
  it("normalises server stems and the analysis document", () => {
    const project = parseStudioProject(RAW);

    expect(project).toMatchObject({
      id: "p1",
      title: "Demo take",
      revision: 3,
      frames: 384000,
      durationSeconds: 8,
      key: "C major",
      bpb: 4,
      beats: RAW.document.grid.beats,
      bars: [0, 2, 4, 6],
    });
    expect(project.stems).toHaveLength(4);
    expect(project.stems[0]).toMatchObject({
      id: "drums",
      name: "Drums",
      role: "drums",
      audioUrl: "/api/projects/p1/stems/drums/pcm",
      frames: 384000,
      channels: 2,
      sampleRate: 48000,
    });
    expect(project.analysis).toMatchObject({
      bpb: 4,
      bpm: 120,
      key: "C major",
      beats: RAW.document.grid.beats,
      bars: [0, 2, 4, 6],
      cached: true,
    });
    expect(project.chords).toEqual([
      { startSeconds: 0, endSeconds: 2, label: "C:maj" },
      { startSeconds: 2, endSeconds: 4, label: "A:min7" },
    ]);
  });

  it("restores sections from bar indices", () => {
    const project = parseStudioProject(RAW);
    expect(project.sections).toEqual([
      { id: "s1", name: "Intro", startSeconds: 0, endSeconds: 2 },
    ]);
  });

  it("restores speed, pitch, position, loop and mixer", () => {
    const project = parseStudioProject(RAW);
    expect(project.restored.state).toMatchObject({
      speed: 0.75,
      pitchSemitones: -2,
      loopEnabled: true,
    });
    expect(project.restored.positionSeconds).toBeCloseTo(0.5);
    expect(project.restored.loopRange).toEqual({
      startSeconds: 1,
      endSeconds: 2,
    });
    expect(project.restored.mixer.bass).toMatchObject({
      pan: -0.5,
      muted: false,
      soloed: false,
    });
    expect(project.restored.mixer.bass.gainDb).toBeCloseTo(-6.0206, 3);
    expect(project.restored.mixer.mix.muted).toBe(true);
  });

  it("accepts a project without stems or analysis", () => {
    const project = parseStudioProject({
      ...RAW,
      stems: [],
      document: {},
      grid: null,
      key: null,
    });

    expect(project.stems).toEqual([]);
    expect(project.analysis).toBeNull();
    expect(project.chords).toEqual([]);
    expect(project.sections).toEqual([]);
    expect(project.bpb).toBe(4);
    expect(project.restored.state).toEqual(DEFAULT_PRACTICE_STATE);
    expect(project.restored.loopRange).toBeNull();
  });

  it("rebuilds the ruler grid from the analysis document when the alias is absent", () => {
    const project = parseStudioProject({
      ...RAW,
      grid: null,
    });

    expect(project.grid).toMatchObject({
      bpm: 120,
      meter: { numerator: 4, denominator: 4 },
      offsetSeconds: 0,
    });
  });

  it("rejects a payload without a project id", () => {
    expect(() => parseStudioProject({ title: "no id" })).toThrow();
  });
});

describe("bar times", () => {
  it("uses analysis bars and falls back to beats or tempo", () => {
    expect(barTimesFromGrid([0, 0.5, 1, 1.5, 2], [0, 2], 120, 4, 0, 3)).toEqual(
      [0, 2],
    );
    expect(barTimesFromGrid([0, 0.5, 1, 1.5, 2], [], 120, 4, 0, 3)).toEqual([
      0, 2,
    ]);
    expect(barTimesFromGrid([], [], 120, 4, 0, 5)).toEqual([0, 2, 4]);
    expect(barTimesFromGrid([], [], 0, 4, 0, 5)).toEqual([]);
  });

  it("finds the bar containing a time", () => {
    expect(barIndexForSeconds(0, [0, 2, 4, 6])).toBe(0);
    expect(barIndexForSeconds(1.9, [0, 2, 4, 6])).toBe(0);
    expect(barIndexForSeconds(2, [0, 2, 4, 6])).toBe(1);
    expect(barIndexForSeconds(99, [0, 2, 4, 6])).toBe(3);
    expect(barIndexForSeconds(1, [])).toBe(0);
  });
});

describe("section conversion", () => {
  it("prefers stored seconds then falls back to bar indices", () => {
    const sections = sectionsFromDocument(
      {
        sections: [
          { id: "a", name: "Bars", start_bar: 1, end_bar: 2 },
          {
            id: "b",
            name: "Free",
            start_bar: 1,
            end_bar: 2,
            start_seconds: 2.2,
            end_seconds: 3.9,
          },
        ],
      },
      [0, 2, 4, 6],
      120,
      4,
      0,
      8,
    );

    expect(sections).toEqual([
      { id: "a", name: "Bars", startSeconds: 2, endSeconds: 4 },
      { id: "b", name: "Free", startSeconds: 2.2, endSeconds: 3.9 },
    ]);
  });

  it("writes bar indices plus exact seconds for round-tripping", () => {
    const server = sectionsToServer(
      [
        { id: "s1", name: "Intro", startSeconds: 0, endSeconds: 2 },
        { id: "s2", name: "Solo", startSeconds: 2.2, endSeconds: 3.9 },
      ],
      [0, 2, 4, 6],
    );

    expect(server[0]).toMatchObject({ start_bar: 0, end_bar: 1 });
    expect(server[1]).toMatchObject({
      start_bar: 1,
      end_bar: 2,
      start_seconds: 2.2,
      end_seconds: 3.9,
    });
  });
});

describe("practice state conversion", () => {
  it("round-trips sections, loop, speed, pitch, position and mixer", () => {
    const mixer: MixerState = {
      ...createInitialMixerState(["mix", "bass"]),
      bass: { gainDb: -6.0206, pan: 0.25, muted: true, soloed: true },
    };
    const server: ServerPracticeState = buildServerState({
      sections: [{ id: "s1", name: "Intro", startSeconds: 0, endSeconds: 2 }],
      bars: [0, 2, 4, 6],
      sampleRate: 48000,
      positionSeconds: 1.5,
      loopRange: { startSeconds: 1, endSeconds: 2 },
      practice: {
        ...DEFAULT_PRACTICE_STATE,
        speed: 0.75,
        pitchSemitones: 2,
        loopEnabled: true,
      },
      mixer,
    });

    expect(server).toMatchObject({
      state_version: 1,
      speed: 0.75,
      pitch_semitones: 2,
      position_frame: 72000,
      loop: { start_frame: 48000, end_frame: 96000 },
      sections: [
        {
          id: "s1",
          name: "Intro",
          start_bar: 0,
          end_bar: 1,
          start_seconds: 0,
          end_seconds: 2,
        },
      ],
    });
    expect(server.mixer.bass.gain).toBeCloseTo(0.5, 4);
    expect(server.mixer.bass.muted).toBe(true);
    expect(server.mixer.bass.solo).toBe(true);
  });

  it("converts linear server gains to dB and back", () => {
    const mixer = mixerFromServer({
      bass: { gain: 0.5, muted: false, solo: true, pan: 0.5 },
    });
    expect(mixer.bass.gainDb).toBeCloseTo(-6.0206);
    expect(mixer.bass.soloed).toBe(true);

    const server = mixerToServer(mixer);
    expect(server.bass.gain).toBeCloseTo(0.5, 4);
    expect(server.bass.solo).toBe(true);
  });

  it("uses practice defaults for an empty document", () => {
    const restored = practiceFromDocument({}, 8, 48000);
    expect(restored.state).toEqual(DEFAULT_PRACTICE_STATE);
    expect(restored.positionSeconds).toBe(0);
    expect(restored.loopRange).toBeNull();
    expect(restored.mixer).toEqual({});
  });
});

describe("createShellApi", () => {
  it("parses the project payload from the real endpoint", async () => {
    const calls: string[] = [];
    const api = createShellApi({
      fetchImpl: async (input) => {
        calls.push(String(input));
        return response(RAW);
      },
    });

    const project = await api.openProject("p1");

    expect(calls).toEqual(["/api/projects/p1"]);
    expect(project.analysis?.cached).toBe(true);
    expect(project.stems[1].id).toBe("bass");
  });

  it("saves practice state with the current revision", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const api = createShellApi({
      fetchImpl: async (input, init) => {
        calls.push({ url: String(input), init });
        return response({ project: { revision: 4 }, state: {} });
      },
    });

    const revision = await api.saveState(
      "p1",
      buildServerState({
        sections: [],
        bars: [],
        sampleRate: 48000,
        positionSeconds: 0,
        loopRange: null,
        practice: DEFAULT_PRACTICE_STATE,
        mixer: {},
      }),
      3,
    );

    expect(revision).toBe(4);
    expect(calls[0].url).toBe("/api/projects/p1/state");
    expect(calls[0].init?.method).toBe("PUT");
    expect(JSON.parse(String(calls[0].init?.body))).toMatchObject({
      revision: 3,
      state: { state_version: 1 },
    });
  });

  it("refreshes the revision and retries once after a 409", async () => {
    const puts: Array<{ revision?: number; sections?: unknown }> = [];
    let gets = 0;
    const api = createShellApi({
      fetchImpl: async (input, init) => {
        const url = String(input);
        if (url.endsWith("/state")) {
          const body = JSON.parse(String(init?.body)) as {
            revision?: number;
            state?: { sections?: unknown };
          };
          puts.push({
            revision: body.revision,
            sections: body.state?.sections,
          });
          if (puts.length === 1) {
            return response({ detail: "revision conflict" }, 409);
          }
          return response({ project: { revision: 8 }, state: {} });
        }
        gets += 1;
        return response({ ...RAW, revision: 7 });
      },
    });
    const state = buildServerState({
      sections: [{ id: "s1", name: "Verse", startSeconds: 0, endSeconds: 2 }],
      bars: [0, 2, 4, 6],
      sampleRate: 48000,
      positionSeconds: 0,
      loopRange: null,
      practice: DEFAULT_PRACTICE_STATE,
      mixer: {},
    });

    const revision = await api.saveState("p1", state, 3);

    expect(puts).toHaveLength(2);
    expect(puts[0].revision).toBe(3);
    expect(puts[1].revision).toBe(7);
    expect(puts[1].sections).toMatchObject([
      { id: "s1", name: "Verse", start_bar: 0, end_bar: 1 },
    ]);
    expect(gets).toBe(1);
    expect(revision).toBe(8);
  });

  it("does not retry other save failures", async () => {
    const api = createShellApi({
      fetchImpl: async () => response({ detail: "disk full" }, 500),
    });
    const state = buildServerState({
      sections: [],
      bars: [],
      sampleRate: 48000,
      positionSeconds: 0,
      loopRange: null,
      practice: DEFAULT_PRACTICE_STATE,
      mixer: {},
    });

    await expect(api.saveState("p1", state, 3)).rejects.toMatchObject({
      status: 500,
      message: "disk full",
    });
  });

  it("reports a project HTTP failure with the server detail", async () => {
    const api = createShellApi({
      fetchImpl: async () => response({ detail: "project p9 not found" }, 404),
    });

    await expect(api.openProject("p9")).rejects.toMatchObject({
      status: 404,
      message: "project p9 not found",
    });
  });
});
