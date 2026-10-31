/**
 * Domain types shared by the API client, the state layer and the panels.
 * Response parsing in `api/client.ts` is the only place untrusted JSON turns
 * into these shapes.
 */

export interface Meter {
  numerator: number;
  denominator: number;
}

export interface Grid {
  bpm: number;
  meter: Meter;
  offsetSeconds: number;
}

export interface Asset {
  id: string;
  title: string;
  durationSeconds: number;
  sampleRate: number;
  channels: number;
}

export interface Stem {
  id: string;
  name: string;
  role: string;
  /** Asset whose peaks describe this stem. */
  peaksAssetId: string;
  audioUrl?: string;
}

export interface Project {
  id: string;
  title: string;
  durationSeconds: number;
  asset: Asset;
  grid: Grid | null;
  key: string | null;
  stems: Stem[];
}

export interface LibraryEntry {
  id: string;
  title: string;
  durationSeconds: number;
  sampleRate: number;
  channels: number;
  importedAt: string;
  projectId: string | null;
}
