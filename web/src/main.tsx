import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import {
  createStudioPlayer,
  studioPlayerOptionsFromProject,
} from "./player/studio-player";
import type { AnalysisSnapshot } from "./state/analysis";
import { createAnalysisJobClient } from "./state/analysisApi";
import {
  createShellApi,
  type StudioProject,
} from "./state/project";
import {
  createShellTransport,
  type StudioRuntime,
} from "./state/studioRuntime";
import "./styles.css";

const api = createShellApi();
const analysisClient = createAnalysisJobClient();

/** Real runtime: t9's engine mapped onto the shell's player/mixer/practice seams. */
const transport = createShellTransport(
  (project: StudioProject, analysis: AnalysisSnapshot | null): StudioRuntime => {
    const options = studioPlayerOptionsFromProject(project, {
      frameCount: project.frames,
      channelCount: project.asset.channels,
      ...(analysis !== null
        ? {
            grid: {
              bpm: analysis.bpm ?? 120,
              bpb: analysis.bpb,
              beatsSeconds: analysis.beats,
              offsetSeconds: analysis.beats[0] ?? 0,
            },
          }
        : {}),
    });
    const engine = createStudioPlayer(options);
    return {
      player: engine.player,
      mixer: engine.mixer,
      practice: engine.practice,
      ready: engine.ready,
      getNotice: engine.getNotice,
      subscribeNotice: engine.subscribeNotice,
      diagnostics: engine.diagnostics,
      dispose: engine.dispose,
    };
  },
);

const container = document.getElementById("root");
if (container === null) {
  throw new Error("index.html is missing the #root element");
}

createRoot(container).render(
  <StrictMode>
    <App api={api} transport={transport} analysisClient={analysisClient} />
  </StrictMode>,
);
