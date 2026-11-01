import { describe, expect, it, vi } from "vitest";

import { createLocalStudioRuntime } from "./localStudio";
import {
  applyStudioRuntimeSnapshot,
  captureStudioRuntime,
  createShellTransport,
  type StudioRuntime,
} from "./studioRuntime";
import type { StudioProject } from "./project";

const PROJECT = { id: "p1", durationSeconds: 8 } as StudioProject;

function runtime(label: string): StudioRuntime & { label: string } {
  const local = createLocalStudioRuntime(PROJECT);
  return { ...local, label };
}

describe("createShellTransport", () => {
  it("disposes the previous runtime when a new project opens", async () => {
    const first = runtime("first");
    const disposeFirst = vi.spyOn(first, "dispose");
    const second = runtime("second");
    const transport = createShellTransport((project) =>
      project.id === "p2" ? second : first,
    );

    await transport.open(PROJECT);
    await transport.open({ ...PROJECT, id: "p2" });

    expect(disposeFirst).toHaveBeenCalledTimes(1);
    expect(transport.current()).toBe(second);
    transport.dispose();
  });

  it("returns the runtime before audio is ready", async () => {
    let release!: () => void;
    const ready = new Promise<void>((resolve) => {
      release = resolve;
    });
    const local = runtime("slow");
    const transport = createShellTransport(() => ({ ...local, ready }));

    const opened = await transport.open(PROJECT);

    expect(opened.player).toBe(local.player);
    release();
    await opened.ready;
    transport.dispose();
  });

  it("propagates a factory failure", async () => {
    const transport = createShellTransport(() => {
      throw new Error("engine failed");
    });

    await expect(transport.open(PROJECT)).rejects.toThrow("engine failed");
    expect(transport.current()).toBeNull();
    transport.dispose();
  });

  it("rejects after dispose", async () => {
    const transport = createShellTransport(() => runtime("r"));
    transport.dispose();
    await expect(transport.open(PROJECT)).rejects.toMatchObject({
      name: "AbortError",
    });
  });
});

describe("studio runtime snapshots", () => {
  function runtimeState(): StudioRuntime {
    const local = createLocalStudioRuntime({
      durationSeconds: 8,
      stems: [{ id: "mix" }, { id: "bass" }],
    });
    local.practice.setSpeed(0.75);
    local.practice.setCountInBars(1);
    local.practice.setMetronomeEnabled(true);
    local.practice.setMetronomeVolume(0.4);
    local.practice.setAccentDownbeat(false);
    local.player.setLoopRange({ startSeconds: 1, endSeconds: 3 });
    local.player.setLoopEnabled(true);
    local.player.seek(1.5);
    local.mixer.setGain("bass", -6);
    local.mixer.setPan("bass", 0.5);
    local.mixer.setMuted("bass", true);
    local.mixer.setMuted("mix", true);
    return local;
  }

  it("captures and reapplies position, speed, loop, practice and mixer", () => {
    const source = runtimeState();
    const snapshot = captureStudioRuntime(source);
    expect(snapshot).toMatchObject({
      positionSeconds: 1.5,
      speed: 0.75,
      loopRange: { startSeconds: 1, endSeconds: 3 },
      loopEnabled: true,
      wasPlaying: false,
    });

    const target = createLocalStudioRuntime({
      durationSeconds: 8,
      stems: [{ id: "mix" }, { id: "bass" }],
    });
    applyStudioRuntimeSnapshot(target, snapshot);

    expect(target.player.getState()).toMatchObject({
      positionSeconds: 1.5,
      speed: 0.75,
      loopRange: { startSeconds: 1, endSeconds: 3 },
      loopEnabled: true,
      status: "paused",
    });
    expect(target.practice.getState()).toMatchObject({
      speed: 0.75,
      countInBars: 1,
      metronomeEnabled: true,
      metronomeVolume: 0.4,
      accentDownbeat: false,
    });
    expect(target.mixer.getState().bass).toMatchObject({
      gainDb: -6,
      pan: 0.5,
      muted: true,
    });
    expect(target.mixer.getState().mix.muted).toBe(true);
  });

  it("resumes playback only when it was playing and requested", () => {
    const source = runtimeState();
    source.player.play();
    const snapshot = captureStudioRuntime(source);
    expect(snapshot.wasPlaying).toBe(true);

    const pausedTarget = createLocalStudioRuntime({ durationSeconds: 8 });
    applyStudioRuntimeSnapshot(pausedTarget, snapshot);
    expect(pausedTarget.player.getState().status).toBe("paused");

    const resumedTarget = createLocalStudioRuntime({ durationSeconds: 8 });
    applyStudioRuntimeSnapshot(resumedTarget, snapshot, {
      resumePlayback: true,
    });
    expect(resumedTarget.player.getState().status).toBe("playing");

    source.dispose?.();
    pausedTarget.dispose?.();
    resumedTarget.dispose?.();
  });
});

describe("createLocalStudioRuntime", () => {
  it("provides controller state without audio", () => {
    const local = createLocalStudioRuntime({
      durationSeconds: 8,
      stems: [{ id: "bass" }],
    });
    expect(local.player.getState().durationSeconds).toBe(8);
    expect(Object.keys(local.mixer.getState())).toEqual(["bass"]);
    expect(local.getNotice?.()).toBeNull();
    local.dispose?.();
  });
});
