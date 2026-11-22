import { describe, expect, it } from "vitest";

import { setupGates, type SetupStatus } from "../../state/setup";

function status(
  readiness: Partial<SetupStatus["readiness"]>,
  platform = "linux",
): SetupStatus {
  return {
    platform,
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

describe("Windows bundled analysis", () => {
  it("enables analysis when bundled Sonic/Vamp tools are present", () => {
    const base = status({}, "windows") as unknown as SetupStatus & {
      tools: Record<string, unknown>;
    };
    base.tools = {
      sonic_visualiser: {
        installed: true,
        path: "C:/PALM/tools/sonic-annotator",
        license: "GPL-2.0-or-later",
      },
      vamp_plugin_pack: {
        installed: true,
        path: "C:/PALM/tools/vamp-plugins",
        license: "AGPL-3.0",
      },
    };
    const gates = setupGates(base);
    expect(gates.canAnalyze).toBe(true);
    expect(gates.analyzeReason).toBeNull();
    expect(gates.canSeparate).toBe(true);
  });

  it("reports missing bundled tools without the old platform blocker", () => {
    const gates = setupGates(status({ tools_ready: false }, "windows"));
    expect(gates.canAnalyze).toBe(false);
    expect(gates.analyzeReason).not.toContain(
      "no 64-bit Vamp plugin distribution",
    );
    expect(gates.canSeparate).toBe(true);
  });
});
