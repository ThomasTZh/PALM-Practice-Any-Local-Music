import { describe, expect, it, vi } from "vitest";

import { createLocalStudioRuntime } from "./localStudio";
import { createShellTransport, type StudioRuntime } from "./studioRuntime";
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
