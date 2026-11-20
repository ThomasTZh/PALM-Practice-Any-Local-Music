import { describe, expect, it } from "vitest";

import { setupGates, type SetupStatus } from "../../state/setup";

function status(readiness: Partial<SetupStatus["readiness"]>): SetupStatus {
  return {
    checks: {
      ffmpeg: { ok: true },
      ffprobe: { ok: true },
    },
    readiness: {
      ready: false,
      checks_ok: true,
      tools_ready: true,
      media_tools_ready: true,
      environment_ready: true,
      model_ready: true,
      requires_model_choice: false,
      ...readiness,
    },
  } as unknown as SetupStatus;
}

describe("separation setup gates", () => {
  it("disables Separate with a CPU environment setup path", () => {
    const gates = setupGates(status({ environment_ready: false }));
    expect(gates.canSeparate).toBe(false);
    expect(gates.separateReason).toContain("CPU or CUDA inference environment");
    expect(gates.separateReason).toContain("Open Setup");
  });

  it("disables Separate with a model setup path", () => {
    const gates = setupGates(status({ model_ready: false }));
    expect(gates.canSeparate).toBe(false);
    expect(gates.separateReason).toContain("separation model");
    expect(gates.separateReason).toContain("Open Setup");
  });

  it("enables Separate only when environment and model are ready", () => {
    const gates = setupGates(status({}));
    expect(gates.canSeparate).toBe(true);
    expect(gates.separateReason).toBeNull();
  });
});
