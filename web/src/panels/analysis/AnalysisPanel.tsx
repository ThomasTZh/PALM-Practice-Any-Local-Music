import { useEffect, useRef, useState } from "react";

import {
  runAnalysisJob,
  type AnalysisJobClient,
  type AnalysisJobState,
  type AnalysisSnapshot,
} from "../../state/analysis";
import { KeyBpmReadout } from "../chords/KeyBpmReadout";

export interface AnalysisPanelProps {
  projectId: string;
  analysis: AnalysisSnapshot | null;
  client: AnalysisJobClient;
  defaultBpb?: number;
  pollIntervalMs?: number;
  onAnalyzed?: (snapshot: AnalysisSnapshot) => void;
}

const BPB_OPTIONS = [2, 3, 4, 5, 6, 7, 8, 9, 12];
const DEFAULT_BPB = 4;

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name: string }).name === "AbortError"
  );
}

/**
 * Analysis controls: beats-per-bar selection, a Run button tied to the analysis
 * job client, live progress and a cached/fresh badge. The client is injected so
 * this panel works before (and independently of) the server endpoint.
 */
export function AnalysisPanel({
  projectId,
  analysis,
  client,
  defaultBpb = DEFAULT_BPB,
  pollIntervalMs = 250,
  onAnalyzed,
}: AnalysisPanelProps) {
  const [bpb, setBpb] = useState(() => analysis?.bpb ?? defaultBpb);
  const [job, setJob] = useState<AnalysisJobState | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  const analysisBpb = analysis?.bpb ?? null;
  useEffect(() => {
    if (analysisBpb !== null) {
      setBpb(analysisBpb);
    }
  }, [analysisBpb]);

  async function run(): Promise<void> {
    if (running) {
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setError(null);
    setJob(null);
    try {
      const finished = await runAnalysisJob(client, projectId, bpb, {
        pollIntervalMs,
        signal: controller.signal,
        onUpdate: (state) => {
          if (mountedRef.current) {
            setJob(state);
          }
        },
      });
      if (!mountedRef.current) {
        return;
      }
      setJob(finished);
      if (finished.snapshot !== null) {
        onAnalyzed?.(finished.snapshot);
      }
    } catch (failure) {
      if (mountedRef.current && !isAbort(failure)) {
        setError(messageOf(failure));
      }
    } finally {
      if (mountedRef.current) {
        setRunning(false);
      }
    }
  }

  const snapshot = job?.snapshot ?? analysis;
  const cached = snapshot === null ? null : snapshot.cached;
  const progress = job === null ? 0 : Math.round(job.progress * 100);
  const badgeText =
    cached === null ? "Not analysed" : cached ? "Cached" : "Fresh";

  return (
    <section className="analysis" data-testid="analysis" aria-label="Analysis">
      <header className="panel-header">
        <h2>Analysis</h2>
        <span
          className={`panel-badge${cached === true ? " panel-badge-cached" : ""}`}
          data-testid="analysis-cache-badge"
          data-cached={cached === null ? "unknown" : String(cached)}
        >
          {badgeText}
        </span>
        <div className="analysis-controls">
          <label className="analysis-control">
            Beats per bar
            <select
              aria-label="Beats per bar"
              value={bpb}
              disabled={running}
              onChange={(event) => setBpb(Number(event.target.value))}
            >
              {BPB_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            aria-label="Run analysis"
            disabled={running}
            onClick={() => {
              void run();
            }}
          >
            {running ? "Analysing…" : "Run analysis"}
          </button>
        </div>
      </header>

      {job !== null && (
        <div
          className="analysis-progress"
          role="progressbar"
          aria-label="Analysis progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
          data-testid="analysis-progress"
        >
          <div
            className="analysis-progress-fill"
            style={{ width: `${progress}%` }}
          />
          <span data-testid="analysis-progress-text">
            {job.message} · {progress}%
          </span>
        </div>
      )}

      {error !== null && (
        <p className="panel-error" role="alert">
          {error}
        </p>
      )}

      {snapshot !== null && (
        <>
          <KeyBpmReadout
            keyLabel={snapshot.key}
            bpm={snapshot.bpm}
            bpb={snapshot.bpb}
          />
          <p className="analysis-summary" data-testid="analysis-summary">
            {snapshot.chords.length} chords · {snapshot.bars.length} bars
          </p>
        </>
      )}
    </section>
  );
}
