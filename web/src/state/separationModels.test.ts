import { describe, expect, it } from "vitest";

import {
  defaultSeparationModels,
  resolveSeparationModelId,
  separationModelName,
} from "./separationModels";
import { HTDEMUCS_MODEL } from "./separationModels";

const BS = {
  ...HTDEMUCS_MODEL,
  id: "bs-roformer-sw",
  name: "BS-RoFormer-SW",
  installed: true,
  status: "installed" as const,
};

describe("separation model selection", () => {
  it("has no implicit default for a fresh project", () => {
    expect(defaultSeparationModels().default).toBeNull();
    expect(resolveSeparationModelId([HTDEMUCS_MODEL, BS], null)).toBeNull();
    expect(
      resolveSeparationModelId([HTDEMUCS_MODEL, BS], "missing"),
    ).toBeNull();
  });

  it("preselects only a recorded model that is installed", () => {
    expect(resolveSeparationModelId([HTDEMUCS_MODEL, BS], BS.id)).toBe(BS.id);
    const missing = { ...BS, installed: false, status: "missing" as const };
    expect(
      resolveSeparationModelId([HTDEMUCS_MODEL, missing], BS.id),
    ).toBeNull();
  });

  it("shows the recorded active model name", () => {
    expect(separationModelName([HTDEMUCS_MODEL, BS], BS.id)).toBe(
      "BS-RoFormer-SW",
    );
  });
});
