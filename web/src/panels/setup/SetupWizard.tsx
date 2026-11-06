import { useEffect, useRef, useState } from "react";

import type { SeparationModel } from "../../api/types";
import {
  environmentEstimate,
  modelLicenceLink,
  toolLicenceLink,
  type SetupClient,
  type SetupJobState,
  type SetupStatus,
} from "../../state/setup";
import { formatModelSize } from "../../state/separationModels";
import "./setup.css";

export interface SetupWizardProps {
  client: SetupClient;
  status: SetupStatus;
  onStatus: (status: SetupStatus) => void;
  onClose: () => void;
  pollIntervalMs?: number;
}

type SetupOperation = "tools" | "environment" | "models";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isTerminal(status: SetupJobState["status"]): boolean {
  return (
    status === "succeeded" || status === "failed" || status === "cancelled"
  );
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

function modelLabels(model: SeparationModel): string {
  return model.labels
    .map((label) => label[0]?.toUpperCase() + label.slice(1))
    .join(", ");
}

/**
 * Full-page first-run setup. It is deliberately independent of the library so
 * an incomplete install cannot start analysis or separation before its tools,
 * environment and model are ready.
 */
export function SetupWizard({
  client,
  status,
  onStatus,
  onClose,
  pollIntervalMs = 350,
}: SetupWizardProps) {
  const [toolsConsent, setToolsConsent] = useState(false);
  const [variant, setVariant] = useState<"cpu" | "cuda" | null>(null);
  const [environmentConsent, setEnvironmentConsent] = useState<
    "cpu" | "cuda" | null
  >(null);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [modelConsents, setModelConsents] = useState<string[]>([]);
  const [job, setJob] = useState<SetupJobState | null>(null);
  const [operation, setOperation] = useState<SetupOperation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState<(() => void) | null>(null);
  const activeJobRef = useRef<string | null>(null);
  const runTokenRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      runTokenRef.current += 1;
    };
  }, []);

  function toggle(list: string[], value: string): string[] {
    return list.includes(value)
      ? list.filter((entry) => entry !== value)
      : [...list, value];
  }

  async function runJob(
    kind: SetupOperation,
    label: string,
    start: () => Promise<SetupJobState>,
    retryAction: () => void,
  ): Promise<void> {
    const token = runTokenRef.current + 1;
    runTokenRef.current = token;
    setBusy(true);
    setError(null);
    setRetry(null);
    setOperation(kind);
    try {
      let state = await start();
      activeJobRef.current = state.id;
      if (!mountedRef.current || token !== runTokenRef.current) return;
      setJob(state);
      while (!isTerminal(state.status)) {
        await delay(pollIntervalMs);
        if (!mountedRef.current || token !== runTokenRef.current) return;
        state = await client.job(state.id);
        if (!mountedRef.current || token !== runTokenRef.current) return;
        setJob(state);
      }
      activeJobRef.current = null;
      if (state.status !== "succeeded") {
        throw new Error(
          state.error ??
            (state.status === "cancelled"
              ? `${label} was cancelled. You can retry when ready.`
              : `${label} failed`),
        );
      }
      const next = await client.status();
      if (!mountedRef.current || token !== runTokenRef.current) return;
      onStatus(next);
      setJob(null);
      setOperation(null);
    } catch (failure) {
      if (!mountedRef.current || token !== runTokenRef.current) return;
      setError(errorMessage(failure));
      setRetry(() => retryAction);
      setOperation(null);
    } finally {
      activeJobRef.current = null;
      if (mountedRef.current && token === runTokenRef.current) {
        setBusy(false);
      }
    }
  }

  function installTools(): void {
    void runJob(
      "tools",
      "Tool installation",
      () => client.startTools(toolsConsent),
      installTools,
    );
  }

  function installEnvironment(): void {
    if (variant === null || environmentConsent !== variant) return;
    void runJob(
      "environment",
      "Environment installation",
      () => client.startEnvironment(variant, true),
      installEnvironment,
    );
  }

  function installModels(): void {
    void runJob(
      "models",
      "Model installation",
      () =>
        client.startModels(
          selectedModels,
          selectedModels.filter((id) => modelConsents.includes(id)),
        ),
      installModels,
    );
  }

  async function cancelJob(): Promise<void> {
    const id = activeJobRef.current;
    runTokenRef.current += 1;
    activeJobRef.current = null;
    setBusy(false);
    setJob(null);
    setOperation(null);
    setError("Setup was cancelled. You can retry when ready.");
    setRetry(null);
    if (id !== null) {
      try {
        await client.cancel(id);
      } catch (failure) {
        if (mountedRef.current) setError(errorMessage(failure));
      }
    }
  }

  async function skip(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const next = await client.skip(true);
      if (!mountedRef.current) return;
      onStatus(next);
      onClose();
    } catch (failure) {
      if (mountedRef.current) setError(errorMessage(failure));
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  }

  const canClose = status.skipped || status.ready;
  const toolsInstalled = Object.values(status.tools).every(
    (tool) => tool.installed,
  );
  const environmentInstalled =
    variant !== null && status.environments[variant]?.installed === true;
  const selectedMissing = status.models.filter(
    (model) => selectedModels.includes(model.id) && !model.installed,
  );
  const allSelectedConsented = selectedMissing.every((model) =>
    modelConsents.includes(model.id),
  );
  const canInstallModels =
    selectedMissing.length > 0 && allSelectedConsented && !busy;
  const progress = job === null ? 0 : Math.round(job.progress * 100);

  return (
    <main
      className="setup-page"
      data-testid="setup-wizard"
      tabIndex={0}
      style={{ overflowY: "auto" }}
    >
      <div className="setup-card">
        <p className="setup-early-warning" data-testid="setup-early-warning" role="note">
          Early version 0.1.0-dev: limited testing and quality control. Keep
          backups of projects you care about.
        </p>
        <header className="setup-header">
          <div>
            <p className="setup-eyebrow">First-run setup</p>
            <h1>Set up the studio</h1>
            <p>
              Install the local analysis tools, one inference environment and at
              least one separation model. Everything stays on this machine.
            </p>
          </div>
          <div className="setup-header-actions">
            {canClose && (
              <button type="button" data-testid="setup-close" onClick={onClose}>
                Back to studio
              </button>
            )}
            <button
              type="button"
              data-testid="setup-skip"
              disabled={busy}
              onClick={() => {
                void skip();
              }}
            >
              Skip for now
            </button>
          </div>
        </header>

        {status.ready && (
          <p className="setup-ready" data-testid="setup-ready">
            Setup is complete. The studio is ready.
          </p>
        )}
        {status.skipped && !status.ready && (
          <p className="setup-note" data-testid="setup-skipped">
            Setup was skipped. Analysis, separation and import stay unavailable
            until their requirements are installed.
          </p>
        )}
        {error !== null && (
          <div className="setup-error" role="alert" data-testid="setup-error">
            <span>{error}</span>
            {retry !== null && (
              <button type="button" data-testid="setup-retry" onClick={retry}>
                Retry
              </button>
            )}
          </div>
        )}
        {job !== null && (
          <div className="setup-progress-wrap">
            <div
              className="setup-progress"
              role="progressbar"
              aria-label="Setup progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress}
              data-testid="setup-progress"
            >
              <div
                className="setup-progress-fill"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="setup-progress-row">
              <span data-testid="setup-progress-stage">
                {operation ?? "Setup"} · {job.message} · {progress}%
              </span>
              <button
                type="button"
                data-testid="setup-cancel"
                onClick={() => {
                  void cancelJob();
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <section className="setup-section" data-testid="setup-checks">
          <h2>System checks</h2>
          <ul className="setup-check-list">
            {Object.entries(status.checks).map(([name, check]) => (
              <li key={name} data-ok={check.ok}>
                <span className="setup-check-name">{name}</span>
                <span className="setup-check-detail">{check.detail}</span>
                <span className="setup-status" data-ok={check.ok}>
                  {check.ok ? "Ready" : "Needs attention"}
                </span>
              </li>
            ))}
          </ul>
          {status.registryError !== null && (
            <p className="setup-error" role="alert">
              Model registry: {status.registryError}
            </p>
          )}
        </section>

        <section className="setup-section" data-testid="setup-tools">
          <h2>Optional GPL tools</h2>
          <p className="setup-note">
            Sonic Visualiser and the Vamp plugin pack are GPL/AGPL licensed and
            required for chord and tempo analysis.
          </p>
          <ul className="setup-tool-list">
            {Object.entries(status.tools).map(([name, tool]) => (
              <li key={name}>
                <span>{name.replaceAll("_", " ")}</span>
                <span className="setup-muted">
                  <a
                    data-testid={`tool-licence-${name}`}
                    href={toolLicenceLink(name).licenceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {tool.license}
                  </a>
                  {" · "}
                  <a
                    data-testid={`tool-source-${name}`}
                    href={toolLicenceLink(name).sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Source
                  </a>
                </span>
                <span className="setup-status" data-ok={tool.installed}>
                  {tool.installed ? "Installed" : "Missing"}
                </span>
              </li>
            ))}
          </ul>
          <label className="setup-consent">
            <input
              type="checkbox"
              aria-label="Accept GPL tool licences"
              checked={toolsConsent}
              onChange={(event) => setToolsConsent(event.target.checked)}
            />
            I accept the GPL/AGPL licences for the optional tools.
          </label>
          <button
            type="button"
            data-testid="setup-tools-install"
            disabled={busy || toolsInstalled || !toolsConsent}
            onClick={installTools}
          >
            {toolsInstalled ? "Tools installed" : "Install optional tools"}
          </button>
        </section>

        <section className="setup-section" data-testid="setup-environments">
          <h2>Inference environment</h2>
          <p className="setup-note">
            Choose one PyTorch environment. CPU works everywhere; CUDA needs an
            NVIDIA GPU and driver.
          </p>
          <div className="setup-environment-options">
            {(["cpu", "cuda"] as const).map((choice) => (
              <label key={choice} className="setup-environment-card">
                <input
                  type="radio"
                  name="setup-environment"
                  aria-label={`${choice.toUpperCase()} environment`}
                  checked={variant === choice}
                  onChange={() => {
                    setVariant(choice);
                    setEnvironmentConsent(null);
                  }}
                />
                <span className="setup-environment-name">
                  {choice.toUpperCase()}
                </span>
                <span className="setup-muted">
                  {environmentEstimate(choice)}
                </span>
                <span
                  className="setup-status"
                  data-ok={status.environments[choice]?.installed === true}
                >
                  {status.environments[choice]?.installed
                    ? "Installed"
                    : "Missing"}
                </span>
              </label>
            ))}
          </div>
          {variant !== null && !environmentInstalled && (
            <label className="setup-consent">
              <input
                type="checkbox"
                aria-label={`Accept ${variant.toUpperCase()} environment licence`}
                checked={environmentConsent === variant}
                onChange={(event) =>
                  setEnvironmentConsent(event.target.checked ? variant : null)
                }
              />
              I accept the licence for the {variant.toUpperCase()} inference
              environment.
            </label>
          )}
          <button
            type="button"
            data-testid="setup-env-install"
            disabled={
              busy ||
              variant === null ||
              environmentConsent !== variant ||
              environmentInstalled
            }
            onClick={installEnvironment}
          >
            {environmentInstalled
              ? `${variant?.toUpperCase()} environment installed`
              : "Install environment"}
          </button>
        </section>

        <section className="setup-section" data-testid="setup-models">
          <h2>Separation models</h2>
          <p className="setup-note">
            All models are equal. Install any that you want to use; licences are
            shown per model.
          </p>
          <div className="setup-model-grid">
            {status.models.map((model) => {
              const selected = selectedModels.includes(model.id);
              const consent = modelConsents.includes(model.id);
              return (
                <article
                  key={model.id}
                  className="setup-model-card"
                  data-testid={`setup-model-card-${model.id}`}
                  data-installed={model.installed}
                >
                  <header>
                    <h3>{model.name}</h3>
                    <span className="setup-status" data-ok={model.installed}>
                      {model.installed ? "Installed" : "Missing"}
                    </span>
                  </header>
                  <p className="setup-muted">
                    {model.engine.toUpperCase()} ·{" "}
                    {formatModelSize(model.size_bytes)}
                  </p>
                  <p className="setup-model-labels">{modelLabels(model)}</p>
                  <p className="setup-licence">
                    <a
                      data-testid={`model-licence-${model.id}`}
                      href={modelLicenceLink(model).licenceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {model.license}
                    </a>
                    {modelLicenceLink(model).sourceUrl !== "" && (
                      <>
                        {" · "}
                        <a
                          data-testid={`model-source-${model.id}`}
                          href={modelLicenceLink(model).sourceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Source
                        </a>
                      </>
                    )}
                  </p>
                  {!model.installed && (
                    <div className="setup-model-actions">
                      <label>
                        <input
                          type="checkbox"
                          aria-label={`Select ${model.name}`}
                          checked={selected}
                          onChange={() =>
                            setSelectedModels((current) =>
                              toggle(current, model.id),
                            )
                          }
                        />
                        Select for install
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          aria-label={`Accept ${model.name} licence`}
                          checked={consent}
                          onChange={() =>
                            setModelConsents((current) =>
                              toggle(current, model.id),
                            )
                          }
                        />
                        I accept this licence
                      </label>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
          <button
            type="button"
            data-testid="setup-model-install"
            disabled={!canInstallModels}
            onClick={installModels}
          >
            Install selected models
          </button>
          {selectedMissing.length > 0 && !allSelectedConsented && (
            <p className="setup-note">
              Accept each selected model's licence before installing.
            </p>
          )}
        </section>

        <footer className="setup-footer">
          <span className="setup-muted">
            Data root: {status.roots.data_root ?? "unknown"}
          </span>
          {!canClose && (
            <button
              type="button"
              data-testid="setup-skip-footer"
              disabled={busy}
              onClick={() => {
                void skip();
              }}
            >
              Skip and use the library
            </button>
          )}
        </footer>
      </div>
    </main>
  );
}
