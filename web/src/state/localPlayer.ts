import {
  clampSpeed,
  initialPlayerState,
  normalizeLoopRange,
  type LoopRange,
  type PlayerState,
  type StudioPlayer,
} from "./player";

/**
 * Silent transport used by the shell before the audio engine is attached.
 *
 * It keeps time in JavaScript so the playhead, position display and follow
 * behaviour can be exercised without decoding audio. It is not an audio engine
 * and says so: there is no sound, only transport state.
 */

export interface LocalPlayerOptions {
  durationSeconds?: number;
  tickMs?: number;
  now?: () => number;
}

export function createLocalPlayer(
  options: LocalPlayerOptions = {},
): StudioPlayer {
  const tickMs = options.tickMs ?? 50;
  const now = options.now ?? (() => Date.now());
  let state = initialPlayerState({
    durationSeconds: Math.max(0, options.durationSeconds ?? 0),
  });
  const listeners = new Set<(state: PlayerState) => void>();
  let timer: ReturnType<typeof setInterval> | null = null;
  let lastTick = now();

  function emit(next: PlayerState): void {
    state = next;
    for (const listener of listeners) {
      listener(state);
    }
  }

  function update(partial: Partial<PlayerState>): void {
    emit({ ...state, ...partial });
  }

  function stopClock(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  function advance(): void {
    if (state.status !== "playing") {
      return;
    }
    const current = now();
    const elapsed = Math.max(0, (current - lastTick) / 1000);
    lastTick = current;
    let position = state.positionSeconds + elapsed * state.speed;
    const loop = state.loopRange;
    if (state.loopEnabled && loop !== null) {
      const span = loop.endSeconds - loop.startSeconds;
      if (span > 0 && position >= loop.endSeconds) {
        position = loop.startSeconds + ((position - loop.startSeconds) % span);
      }
    } else if (state.durationSeconds > 0 && position >= state.durationSeconds) {
      stopClock();
      emit({
        ...state,
        positionSeconds: state.durationSeconds,
        status: "ended",
      });
      return;
    }
    update({ positionSeconds: position });
  }

  function startClock(): void {
    stopClock();
    lastTick = now();
    timer = setInterval(advance, tickMs);
  }

  function setDuration(seconds: number): void {
    const durationSeconds = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
    if (durationSeconds === 0) {
      stopClock();
    }
    const positionSeconds = Math.min(state.positionSeconds, durationSeconds);
    const status =
      state.status === "idle" && durationSeconds > 0
        ? "paused"
        : durationSeconds === 0 && state.status !== "error"
          ? "idle"
          : state.status;
    let loopRange = state.loopRange;
    if (loopRange !== null) {
      loopRange = normalizeLoopRange(loopRange, durationSeconds);
      if (loopRange === null) {
        update({
          durationSeconds,
          positionSeconds,
          status,
          loopRange,
          loopEnabled: false,
        });
        return;
      }
    }
    update({ durationSeconds, positionSeconds, status, loopRange });
  }

  function play(): void {
    if (state.status === "playing" || state.durationSeconds <= 0) {
      return;
    }
    const atEnd = state.positionSeconds >= state.durationSeconds;
    update({
      status: "playing",
      positionSeconds: atEnd ? 0 : state.positionSeconds,
      error: null,
    });
    startClock();
  }

  function pause(): void {
    if (state.status !== "playing") {
      return;
    }
    stopClock();
    update({ status: "paused" });
  }

  function toggle(): void {
    if (state.status === "playing") {
      pause();
    } else {
      play();
    }
  }

  function seek(seconds: number): void {
    const positionSeconds = Math.min(
      state.durationSeconds,
      Math.max(0, Number.isFinite(seconds) ? seconds : 0),
    );
    const status = state.status === "ended" ? "paused" : state.status;
    update({ positionSeconds, status });
  }

  function setSpeed(speed: number): void {
    update({ speed: clampSpeed(speed) });
  }

  function setLoopEnabled(enabled: boolean): void {
    update({ loopEnabled: enabled && state.loopRange !== null });
  }

  function setLoopRange(range: LoopRange | null): void {
    const loopRange = normalizeLoopRange(range, state.durationSeconds);
    update({
      loopRange,
      loopEnabled: loopRange === null ? false : state.loopEnabled,
    });
  }

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    play,
    pause,
    toggle,
    seek,
    setSpeed,
    setLoopEnabled,
    setLoopRange,
    setDuration,
    dispose() {
      stopClock();
      listeners.clear();
    },
  };
}
