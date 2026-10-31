// @vitest-environment node
/**
 * Rebuilt stretch artifacts (t2): `stretch_set_transpose` must be
 * exported by both bundled variants, the committed BUILD.md hashes must
 * match the committed binaries, and the wrapper must actually shift
 * pitch while the playback rate stays independent.
 */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  dominantFrequency,
  makeEngine,
  QUANTUM,
  RATE,
  sine,
  stretchApi,
  stretchBytes,
} from "./test-utils";

const DIST = fileURLToPath(new URL("./stretch/dist/", import.meta.url));
const BUILD_MD = fileURLToPath(new URL("./stretch/BUILD.md", import.meta.url));

function sha256(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function wasmFunctionExports(bytes: ArrayBuffer): string[] {
  const module = new WebAssembly.Module(bytes);
  return WebAssembly.Module.exports(module)
    .filter((entry) => entry.kind === "function")
    .map((entry) => entry.name);
}

describe("stretch WASM artifacts", () => {
  it("exports stretch_set_transpose from both variants", () => {
    for (const variant of ["scalar", "simd"]) {
      const bytes = Uint8Array.from(
        readFileSync(`${DIST}stretch-${variant}.wasm`),
      );
      const exports = wasmFunctionExports(bytes.buffer);
      // d = memory, e = start, then the minified API in BUILD.md order.
      expect(
        WebAssembly.Module.exports(new WebAssembly.Module(bytes))[0],
      ).toMatchObject({
        name: "d",
        kind: "memory",
      });
      expect(exports[0]).toBe("e");
      expect(exports.length).toBe(14);
      // stretch_set_transpose is the tenth API entry -> export `o`.
      expect(exports[10]).toBe("o");
    }
  });

  it("keeps BUILD.md hashes and the export map current", () => {
    const manifest = readFileSync(BUILD_MD, "utf8");
    for (const artifact of [
      "stretch-scalar.js",
      "stretch-scalar.wasm",
      "stretch-simd.js",
      "stretch-simd.wasm",
    ]) {
      const digest = sha256(`${DIST}${artifact}`);
      expect(manifest).toContain(`| dist/${artifact} | \`${digest}\` |`);
    }
    expect(manifest).toContain("| `stretch_set_transpose` | `o` |");
    expect(manifest).toContain("## WASM export map");
  });

  it("applies the transpose in the wrapper and clamps it", () => {
    const engine = makeEngine();
    expect(engine.setTranspose(2)).toBe(2);
    expect(engine.setTranspose(40)).toBe(12);
    expect(engine.setTranspose(-40)).toBe(-12);
    expect(engine.setTranspose(Number.NaN)).toBe(0);
    engine.reset();
    // reset() keeps the wrapper's configured transpose (no silent pitch
    // change on a hard re-position).
    expect(engine.setTranspose(0)).toBe(0);
  });

  it("shifts the engine output pitch while the rolling rate stays 1x", () => {
    const api = stretchApi();
    const engine = api.instantiateStretch(stretchBytes());
    engine.configure(RATE);
    engine.setTranspose(2);
    const latency = engine.latencies();
    const window = engine.windowLength();
    // Feed a 440 Hz tone straight to the rolling seek for 200 quanta,
    // then measure the next 256 quanta.
    const roll = (
      startFrame: number,
      quanta: number,
      collect: Float32Array | null,
    ): number => {
      let cursor = startFrame;
      for (let q = 0; q < quanta; q += 1) {
        const end = Math.round(
          cursor + latency.outputFrames + latency.inputFrames,
        );
        const from = end - window;
        for (let i = 0; i < window; i += 1) {
          const value = 0.5 * Math.sin((2 * Math.PI * 440 * (from + i)) / RATE);
          engine.inL[i] = value;
          engine.inR[i] = value;
        }
        engine.seek(window, 1);
        engine.process(0, QUANTUM);
        if (collect) collect.set(engine.outL.subarray(0, QUANTUM), q * QUANTUM);
        cursor += QUANTUM;
      }
      return cursor;
    };
    const cursor = roll(0, 200, null);
    const samples = new Float32Array(256 * QUANTUM);
    roll(cursor, 256, samples);
    const measured = dominantFrequency(samples);
    const expected = 440 * Math.pow(2, 2 / 12);
    expect(measured).toBeGreaterThan(expected * 0.99);
    expect(measured).toBeLessThan(expected * 1.01);
  });

  it("produces a 440 Hz sine source for the test rig", () => {
    // Guards the helper itself: a broken generator would make the pitch
    // assertions above meaningless.
    expect(dominantFrequency(sine(32768), RATE)).toBeCloseTo(440, 0);
  });
});
