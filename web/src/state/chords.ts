import type { Viewport } from "../panels/waveform/viewport";

/** A chord region as analysed (raw Chordino label) or edited by the user. */
export interface ChordRegion {
  startSeconds: number;
  endSeconds: number;
  label: string;
}

export interface NormalizedChord extends ChordRegion {
  /** Display symbol, e.g. `C`, `Am7`, `N.C.`. */
  symbol: string;
}

export interface ChordBlock extends NormalizedChord {
  /** Index in the analysed chord list. */
  index: number;
  leftPx: number;
  widthPx: number;
}

const QUALITY_MAP: Record<string, string> = {
  "": "",
  maj: "",
  major: "",
  min: "m",
  m: "m",
  minor: "m",
  min7: "m7",
  m7: "m7",
  min7b5: "m7b5",
  m7b5: "m7b5",
  hdim7: "m7b5",
  maj7: "maj7",
  major7: "maj7",
  "7": "7",
  dom7: "7",
  dim: "dim",
  dim7: "dim7",
  aug: "aug",
  "+": "aug",
  sus: "sus4",
  sus4: "sus4",
  sus2: "sus2",
  "6": "6",
  maj6: "6",
  min6: "m6",
  m6: "m6",
  "9": "9",
  min9: "m9",
  m9: "m9",
  maj9: "maj9",
  "11": "11",
  min11: "m11",
  "13": "13",
  min13: "m13",
  add9: "add9",
  add11: "add11",
  "5": "5",
};

const NO_CHORD = "N.C.";
const NOTE = /^[A-Ga-g][#b♯♭]?$/;

function normalizeRoot(root: string): string {
  const trimmed = root.trim().replace(/♯/g, "#").replace(/♭/g, "b");
  if (trimmed.length === 0) {
    return trimmed;
  }
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

/**
 * Turns Chordino's raw labels into the compact symbols players read.
 *
 * `C:maj` becomes `C`, `A:min7` becomes `Am7`, `N` becomes `N.C.`. Already
 * compact labels pass through, unknown qualities keep their text instead of
 * being dropped, and slash bass notes are preserved.
 */
export function normalizeChordLabel(raw: string): string {
  const text = String(raw ?? "").trim();
  if (
    text.length === 0 ||
    text.toUpperCase() === "N" ||
    text.toUpperCase().replace(/\s+/g, "") === "N.C." ||
    text.toLowerCase() === "none" ||
    text.toLowerCase() === "no chord"
  ) {
    return NO_CHORD;
  }

  let body = text;
  let bass = "";
  const slash = text.lastIndexOf("/");
  if (slash !== -1 && NOTE.test(text.slice(slash + 1).trim())) {
    body = text.slice(0, slash).trim();
    bass = normalizeRoot(text.slice(slash + 1).trim());
  }

  let rootPart: string;
  let qualityPart: string;
  const colon = body.indexOf(":");
  if (colon !== -1) {
    rootPart = body.slice(0, colon);
    qualityPart = body.slice(colon + 1);
  } else {
    const match = body.match(/^([A-Ga-g][#b♯♭]?)(.*)$/);
    if (match === null) {
      return text;
    }
    rootPart = match[1];
    qualityPart = match[2];
  }

  const root = normalizeRoot(rootPart);
  const qualityKey = qualityPart.trim().toLowerCase().replace(/\s+/g, "");
  const quality = QUALITY_MAP[qualityKey] ?? qualityPart.trim();
  return `${root}${quality}${bass.length > 0 ? `/${bass}` : ""}`;
}

export function normalizeChords(chords: ChordRegion[]): NormalizedChord[] {
  return chords.map((chord) => ({
    ...chord,
    symbol: normalizeChordLabel(chord.label),
  }));
}

/** The region containing the playhead, or null in a gap. */
export function chordAt(
  chords: ChordRegion[],
  positionSeconds: number,
): ChordRegion | null {
  for (const chord of chords) {
    if (
      positionSeconds >= chord.startSeconds &&
      positionSeconds < chord.endSeconds
    ) {
      return chord;
    }
  }
  return null;
}

function roundPixels(value: number): number {
  return Math.round(value * 100) / 100;
}

/** Pixel layout of the chords visible in a viewport, clipped at the edges. */
export function chordBlocks(
  chords: ChordRegion[],
  viewport: Viewport,
  widthPx: number,
): ChordBlock[] {
  const visibleStart = viewport.startSeconds;
  const visibleEnd = visibleStart + widthPx * viewport.secondsPerPixel;
  const blocks: ChordBlock[] = [];
  normalizeChords(chords).forEach((chord, index) => {
    const start = Math.max(chord.startSeconds, visibleStart);
    const end = Math.min(chord.endSeconds, visibleEnd);
    if (!(end > start)) {
      return;
    }
    blocks.push({
      ...chord,
      index,
      leftPx: roundPixels((start - visibleStart) / viewport.secondsPerPixel),
      widthPx: roundPixels((end - start) / viewport.secondsPerPixel),
    });
  });
  return blocks;
}
