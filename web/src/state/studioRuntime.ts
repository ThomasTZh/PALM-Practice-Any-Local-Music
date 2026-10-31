import type { AnalysisSnapshot } from "./analysis";
import type { MixerController } from "./mixer";
import type { PracticeController } from "./practice";
import type { StudioPlayer } from "./player";
import type { StudioProject } from "./project";

/** One project's live audio runtime: player plus the two practice seams. */
export interface StudioRuntime {
  player: StudioPlayer;
  mixer: MixerController;
  practice: PracticeController;
  ready?: Promise<void>;
  getNotice?: () => string | null;
  subscribeNotice?: (listener: (notice: string | null) => void) => () => void;
  diagnostics?: () => unknown;
  dispose?: () => void;
}

export type StudioRuntimeFactory = (
  project: StudioProject,
  analysis: AnalysisSnapshot | null,
) => StudioRuntime | Promise<StudioRuntime>;

export interface ShellTransport {
  open(
    project: StudioProject,
    analysis?: AnalysisSnapshot | null,
  ): Promise<StudioRuntime>;
  current(): StudioRuntime | null;
  dispose(): void;
}

function abortError(): Error {
  const error = new Error("project load superseded");
  error.name = "AbortError";
  return error;
}

/**
 * Owns one runtime at a time. Opening a project disposes the previous engine,
 * waits for the new one to be ready (or its mix fallback) and rejects stale
 * opens so a fast project switch cannot wire the wrong audio.
 */
export function createShellTransport(
  factory: StudioRuntimeFactory,
): ShellTransport {
  let currentRuntime: StudioRuntime | null = null;
  let generation = 0;
  let disposed = false;

  return {
    async open(project, analysis = null) {
      if (disposed) {
        throw abortError();
      }
      const current = generation + 1;
      generation = current;
      currentRuntime?.dispose?.();
      currentRuntime = null;
      const runtime = await factory(project, analysis);
      if (current !== generation || disposed) {
        runtime.dispose?.();
        throw abortError();
      }
      currentRuntime = runtime;
      // The shell renders the project immediately; callers that need audio
      // state await `runtime.ready` themselves, so a slow or blocked audio
      // context cannot hide the whole workspace.
      return runtime;
    },

    current() {
      return currentRuntime;
    },

    dispose() {
      disposed = true;
      generation += 1;
      currentRuntime?.dispose?.();
      currentRuntime = null;
    },
  };
}
