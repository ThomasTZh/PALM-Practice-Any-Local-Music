import type { StudioApi } from "../api/client";

/**
 * Test double for the API boundary. Components receive the client as a prop,
 * so tests exercise the same public component API the app uses.
 */
export interface FakeApi extends StudioApi {
  readonly calls: string[];
}

export function createFakeApi(overrides: Partial<StudioApi> = {}): FakeApi {
  const calls: string[] = [];
  return {
    get calls() {
      return calls;
    },
    listLibrary(...args) {
      calls.push("listLibrary");
      return overrides.listLibrary
        ? overrides.listLibrary(...args)
        : Promise.resolve([]);
    },
    openProject(...args) {
      calls.push(`openProject:${args[0]}`);
      return overrides.openProject
        ? overrides.openProject(...args)
        : Promise.reject(new Error(`no project ${args[0]}`));
    },
    importRecording(...args) {
      calls.push(`importRecording:${args[0].name}`);
      return overrides.importRecording
        ? overrides.importRecording(...args)
        : Promise.reject(new Error("import is not configured"));
    },
    fetchPeaks(...args) {
      calls.push(`fetchPeaks:${args[0]}`);
      return overrides.fetchPeaks
        ? overrides.fetchPeaks(...args)
        : Promise.resolve(new ArrayBuffer(0));
    },
  };
}
