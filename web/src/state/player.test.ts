import { afterEach, describe, expect, it, vi } from "vitest";

import { createFakePlayer } from "./fakePlayer";
import { createLocalPlayer } from "./localPlayer";
import {
  clampLoopRangeToDuration,
  clampSpeed,
  initialPlayerState,
  normalizeLoopRange,
} from "./player";

afterEach(() => {
  vi.useRealTimers();
});

describe("player state helpers", () => {
  it("starts paused when there is a duration and idle when there is not", () => {
    expect(initialPlayerState({ durationSeconds: 10 }).status).toBe("paused");
    expect(initialPlayerState().status).toBe("idle");
  });

  it("clamps speed to the practical range", () => {
    expect(clampSpeed(0.1)).toBe(0.25);
    expect(clampSpeed(3)).toBe(2);
    expect(clampSpeed(Number.NaN)).toBe(1);
  });

  it("normalises a backwards loop range and drops a collapsed one", () => {
    expect(normalizeLoopRange({ startSeconds: 4, endSeconds: 2 }, 10)).toEqual({
      startSeconds: 2,
      endSeconds: 4,
    });
    expect(
      normalizeLoopRange({ startSeconds: 2, endSeconds: 2 }, 10),
    ).toBeNull();
    expect(normalizeLoopRange({ startSeconds: 8, endSeconds: 20 }, 10)).toEqual(
      { startSeconds: 8, endSeconds: 10 },
    );
  });
});

describe("clampLoopRangeToDuration", () => {
  it("keeps a loop that still fits", () => {
    expect(
      clampLoopRangeToDuration({ startSeconds: 1, endSeconds: 2 }, 4),
    ).toEqual({ startSeconds: 1, endSeconds: 2 });
  });

  it("clamps the end to a shorter duration", () => {
    expect(
      clampLoopRangeToDuration({ startSeconds: 1, endSeconds: 8 }, 4),
    ).toEqual({ startSeconds: 1, endSeconds: 4 });
  });

  it("keeps the shortest legal loop at the tail instead of deleting it", () => {
    expect(
      clampLoopRangeToDuration({ startSeconds: 5, endSeconds: 8 }, 4),
    ).toEqual({ startSeconds: 3.95, endSeconds: 4 });
  });

  it("returns null only when there is no time to loop", () => {
    expect(
      clampLoopRangeToDuration({ startSeconds: 1, endSeconds: 2 }, 0),
    ).toBeNull();
    expect(clampLoopRangeToDuration(null, 4)).toBeNull();
  });
});

describe("local player transport", () => {
  it("plays, advances its clock, pauses and seeks within the track", () => {
    vi.useFakeTimers();
    let nowMs = 0;
    const player = createLocalPlayer({
      durationSeconds: 10,
      tickMs: 1000,
      now: () => nowMs,
    });

    player.play();
    expect(player.getState().status).toBe("playing");

    nowMs = 1000;
    vi.advanceTimersByTime(1000);
    expect(player.getState().positionSeconds).toBeCloseTo(1);

    player.pause();
    expect(player.getState().status).toBe("paused");
    const frozen = player.getState().positionSeconds;
    nowMs = 5000;
    vi.advanceTimersByTime(1000);
    expect(player.getState().positionSeconds).toBe(frozen);

    player.seek(99);
    expect(player.getState().positionSeconds).toBe(10);
    player.seek(-1);
    expect(player.getState().positionSeconds).toBe(0);
  });

  it("ends at the duration and restarts from the top", () => {
    vi.useFakeTimers();
    let nowMs = 0;
    const player = createLocalPlayer({
      durationSeconds: 2,
      tickMs: 1000,
      now: () => nowMs,
    });

    player.play();
    nowMs = 3000;
    vi.advanceTimersByTime(3000);
    expect(player.getState().status).toBe("ended");
    expect(player.getState().positionSeconds).toBe(2);

    player.play();
    expect(player.getState().positionSeconds).toBe(0);
    expect(player.getState().status).toBe("playing");
    player.dispose();
  });

  it("keeps the loop between its bounds", () => {
    vi.useFakeTimers();
    let nowMs = 0;
    const player = createLocalPlayer({
      durationSeconds: 10,
      tickMs: 1000,
      now: () => nowMs,
    });
    player.setLoopRange({ startSeconds: 1, endSeconds: 2 });
    player.setLoopEnabled(true);
    player.seek(1.9);
    player.play();

    nowMs = 1000;
    vi.advanceTimersByTime(1000);

    const { positionSeconds } = player.getState();
    expect(positionSeconds).toBeGreaterThanOrEqual(1);
    expect(positionSeconds).toBeLessThan(2);
    player.dispose();
  });

  it("applies speed and loop state and notifies subscribers", () => {
    const player = createLocalPlayer({ durationSeconds: 10 });
    const seen: string[] = [];
    const unsubscribe = player.subscribe((state) => seen.push(state.status));

    player.setSpeed(0.75);
    expect(player.getState()).toMatchObject({ speed: 0.75 });

    player.setLoopRange(null);
    expect(player.getState().loopEnabled).toBe(false);
    expect(seen.length).toBeGreaterThan(0);

    unsubscribe();
    player.setDuration(0);
    expect(seen).toHaveLength(2);
    player.dispose();
  });
});

describe("fake player", () => {
  it("records calls and publishes state changes", () => {
    const player = createFakePlayer({ durationSeconds: 8 });
    const seen: number[] = [];
    player.subscribe((state) => seen.push(state.positionSeconds));

    player.play();
    player.seek(2);
    player.setSpeed(0.5);

    expect(player.calls).toEqual(["play", "seek:2", "setSpeed:0.5"]);
    expect(seen).toEqual([0, 2, 2]);
    expect(player.getState()).toMatchObject({
      status: "playing",
      positionSeconds: 2,
      speed: 0.5,
    });
  });
});
