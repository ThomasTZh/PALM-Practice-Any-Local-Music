import { useEffect, useRef, useState } from "react";

import type { SeparationModel } from "../../api/types";
import {
  environmentEstimate,
  modelLicenceLink,
  setupBundledComponents,
  setupLicenceComponents,
  toolLicenceLink,
  type SetupClient,
  type SetupJobState,
  type SetupStatus,
} from "../../state/setup";
import { LICENCE_TEXTS } from "./licenceTexts";
import { formatModelSize } from "../../state/separationModels";
import "./setup.css";

export interface SetupWizardProps {
  client: SetupClient;
  status: SetupStatus;
  onStatus: (status: SetupStatus) => void;
  onClose: () => void;
  pollIntervalMs?: number;
}

type SetupOperation = "media" | "tools" | "environment" | "models";

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
  const [mediaConsent, setMediaConsent] = useState(false);
  const [toolsConsent, setToolsConsent] = useState(false);
  const [variant, setVariant] = useState<"cpu" | "cuda" | null>(null);
  const [environmentConsent, setEnvironmentConsent] = useState<
    "cpu" | "cuda" | null
  >(null);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [modelConsents, setModelConsents] = useState<string[]>([]);
  const [job, setJob] = useState<SetupJobState | null>(null);
  const [operation, setOperation] = useState<string | null>(null);
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
    _kind: SetupOperation,
    label: string,
    startJob: () => Promise<SetupJobState>,
    retryAction: () => void,
  ): Promise<boolean> {
    const token = runTokenRef.current + 1;
    runTokenRef.current = token;
    setBusy(true);
    setError(null);
    setRetry(null);
    setOperation(label);
    try {
      let state = await startJob();
      activeJobRef.current = state.id;
      if (!mountedRef.current || token !== runTokenRef.current) return false;
      setJob(state);
      while (!isTerminal(state.status)) {
        await delay(pollIntervalMs);
        if (!mountedRef.current || token !== runTokenRef.current) return false;
        state = await client.job(state.id);
        if (!mountedRef.current || token !== runTokenRef.current) return false;
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
      if (!mountedRef.current || token !== runTokenRef.current) return false;
      onStatus(next);
      setJob(null);
      setOperation(null);
      return true;
    } catch (failure) {
      if (!mountedRef.current || token !== runTokenRef.current) return false;
      setError(errorMessage(failure));
      setRetry(() => retryAction);
      setOperation(null);
      return false;
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

  function acceptRequiredLicences(): void {
    setMediaConsent(true);
    setToolsConsent(true);
    setVariant("cpu");
    setEnvironmentConsent("cpu");
    setModelConsents((current) =>
      current.includes("htdemucs_ft") ? current : [...current, "htdemucs_ft"],
    );
  }

  function installMediaTools(): void {
    void runJob(
      "media",
      "Media tools",
      () => client.startMediaTools(mediaConsent),
      installMediaTools,
    );
  }

  async function installRecommended(): Promise<void> {
    if (
      !mediaConsent ||
      !toolsConsent ||
      environmentConsent !== "cpu" ||
      (!modelConsents.includes("htdemucs_ft") &&
        status.models.find((model) => model.id === "htdemucs_ft")?.installed !==
          true)
    ) {
      return;
    }
    setVariant("cpu");
    setEnvironmentConsent("cpu");
    setSelectedModels((current) =>
      current.includes("htdemucs_ft") ? current : [...current, "htdemucs_ft"],
    );
    setModelConsents((current) =>
      current.includes("htdemucs_ft") ? current : [...current, "htdemucs_ft"],
    );
    const steps: Array<{
      kind: SetupOperation;
      label: string;
      start: () => Promise<SetupJobState>;
    }> = [
      {
        kind: "media",
        label: "Recommended 1/4 · Media tools",
        start: () => client.startMediaTools(true),
      },
      {
        kind: "tools",
        label: "Recommended 2/4 · Analysis tools",
        start: () => client.startTools(true),
      },
      {
        kind: "environment",
        label: "Recommended 3/4 · CPU environment",
        start: () => client.startEnvironment("cpu", true),
      },
      {
        kind: "models",
        label: "Recommended 4/4 · Demucs model",
        start: () => client.startModels(["htdemucs_ft"], ["htdemucs_ft"]),
      },
    ];
    for (const step of steps) {
      const ok = await runJob(step.kind, step.label, step.start, () => {
        void installRecommended();
      });
      if (!ok || !mountedRef.current) return;
    }
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
  const mediaToolsInstalled =
    status.mediaTools.ffmpeg?.installed === true &&
    status.mediaTools.ffprobe?.installed === true;
  const demucs = status.models.find((model) => model.id === "htdemucs_ft");
  const demucsConsent =
    demucs?.installed === true || modelConsents.includes("htdemucs_ft");
  const canInstallRecommended =
    !busy &&
    (mediaToolsInstalled || mediaConsent) &&
    (toolsInstalled || toolsConsent) &&
    (status.environments.cpu?.installed === true ||
      environmentConsent === "cpu") &&
    demucsConsent;
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
  const recommendedMissing: string[] = [];
  if (!mediaToolsInstalled && !mediaConsent) {
    recommendedMissing.push("accept the FFmpeg/FFprobe licence");
  }
  if (!toolsInstalled && !toolsConsent) {
    recommendedMissing.push("accept the analysis tool licences");
  }
  if (
    status.environments.cpu?.installed !== true &&
    environmentConsent !== "cpu"
  ) {
    recommendedMissing.push("select CPU and accept its environment licence");
  }
  if (demucs?.installed !== true && !modelConsents.includes("htdemucs_ft")) {
    recommendedMissing.push("accept the Demucs licence");
  }

  const progress = job === null ? 0 : Math.round(job.progress * 100);
  const licenceComponents = setupLicenceComponents(status);
  const bundledComponents = setupBundledComponents();
  const licenceTextKeys = Array.from(
    new Set(
      licenceComponents.flatMap((component) => component.licenceTextKeys),
    ),
  );
  const bundledTextKeys = Array.from(
    new Set(
      bundledComponents.flatMap((component) => component.licenceTextKeys),
    ),
  );
  const mediaLicence = licenceComponents.find(
    (component) => component.id === "media-ffmpeg",
  );
  const environmentLicence = licenceComponents.find(
    (component) => component.id === "environment-cpu",
  );
  const demucsLicence = licenceComponents.find(
    (component) => component.id === "model-htdemucs_ft",
  );

  return (
    <main
      className="setup-page"
      data-testid="setup-wizard"
      tabIndex={0}
      style={{ overflowY: "auto" }}
    >
      <div className="setup-card">
        <p
          className="setup-early-warning"
          data-testid="setup-early-warning"
          role="note"
        >
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

        <section
          className="setup-section setup-before-download"
          data-testid="setup-licence-summary"
        >
          <h2>Before downloading</h2>
          <p className="setup-note">
            Review every component this setup can download. No download starts
            until each group is accepted below.
          </p>
          <details
            className="setup-licence-details"
            data-testid="setup-download-licence-details"
          >
            <summary>Downloadable components and full licence texts</summary>
            <ul className="setup-component-list">
              {licenceComponents.map((component) => (
                <li
                  key={component.id}
                  data-testid={`licence-component-${component.id}`}
                  data-required={component.required}
                >
                  <div className="setup-component-main">
                    <strong>{component.name}</strong>
                    <span>{component.version}</span>
                  </div>
                  <div className="setup-component-meta">
                    <a
                      href={component.licenceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {component.licence}
                    </a>
                    <a
                      data-testid={`licence-source-${component.id}`}
                      href={component.sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Source
                    </a>
                    <span>{component.size}</span>
                    <span
                      className="setup-requirement"
                      data-required={component.required}
                    >
                      {component.requirementLabel}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
            <div className="setup-caveat" data-testid="setup-ffmpeg-nonfree">
              <strong>FFmpeg build licence:</strong> GPL-3.0-or-later. Linux x64
              and macOS arm64 use Martin Riedl 9.0.2; the Linux build is
              configured with <code>--enable-nonfree</code> and is not legally
              redistributable. PALM downloads it at setup time and does not
              bundle or redistribute it. Windows uses gyan.dev 8.1.2 essentials.
            </div>
            <details
              className="setup-licence-texts"
              data-testid="setup-licence-texts"
            >
              <summary>Full bundled licence texts</summary>
              {licenceTextKeys.map((key) => (
                <section key={key}>
                  <h3>{key}</h3>
                  <pre data-testid={`licence-text-${key}`}>
                    {LICENCE_TEXTS[key]}
                  </pre>
                </section>
              ))}
            </details>
          </details>
        </section>

        <details
          className="setup-section setup-bundled-details"
          data-testid="setup-bundled-components"
        >
          <summary>
            Bundled third-party components ({bundledComponents.length})
          </summary>
          <p className="setup-note">
            These third-party components are already included in the packaged
            app; they are not downloads.
          </p>
          <ul className="setup-component-list">
            {bundledComponents.map((component) => (
              <li
                key={component.id}
                data-testid={`bundled-component-${component.id}`}
              >
                <div className="setup-component-main">
                  <strong>{component.name}</strong>
                  <span>{component.version}</span>
                </div>
                <div className="setup-component-meta">
                  <a
                    href={component.licenceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {component.licence}
                  </a>
                  <a
                    data-testid={`bundled-source-${component.id}`}
                    href={component.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Source
                  </a>
                </div>
              </li>
            ))}
          </ul>
          <details
            className="setup-licence-texts"
            data-testid="setup-bundled-licence-texts"
          >
            <summary>Full bundled third-party licence texts</summary>
            {bundledTextKeys.map((key) => (
              <section key={key}>
                <h3>{key}</h3>
                <pre data-testid={`bundled-licence-text-${key}`}>
                  {LICENCE_TEXTS[key]}
                </pre>
              </section>
            ))}
          </details>
        </details>

        <section className="setup-recommended" data-testid="setup-recommended">
          <div>
            <h2>Install recommended setup</h2>
            <p className="setup-note">
              FFmpeg/FFprobe, the analysis tools, the CPU environment and Demucs
              htdemucs_ft. Demucs is selected visibly and the model cards stay
              editable.
            </p>
            <div
              className="setup-action-links"
              data-testid="setup-recommended-links"
            >
              {mediaLicence && (
                <>
                  <a
                    href={mediaLicence.licenceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    FFmpeg licence
                  </a>
                  <a
                    href={mediaLicence.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    FFmpeg source
                  </a>
                </>
              )}
              <a
                href={toolLicenceLink("vamp_plugin_pack").licenceUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Vamp licence
              </a>
              <a
                href={toolLicenceLink("vamp_plugin_pack").sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Vamp source
              </a>
              {environmentLicence && (
                <>
                  <a
                    href={environmentLicence.licenceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Environment licence
                  </a>
                  <a
                    href={environmentLicence.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Environment source
                  </a>
                </>
              )}
              {demucsLicence && (
                <>
                  <a
                    href={demucsLicence.licenceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Demucs licence
                  </a>
                  <a
                    href={demucsLicence.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Demucs source
                  </a>
                </>
              )}
            </div>
            {recommendedMissing.length > 0 ? (
              <p
                className="setup-recommended-reason"
                data-testid="setup-recommended-reason"
              >
                To enable: {recommendedMissing.join("; ")}.
              </p>
            ) : (
              <p
                className="setup-recommended-reason setup-recommended-ready"
                data-testid="setup-recommended-reason"
              >
                All required licences are accepted.
              </p>
            )}
          </div>
          <div className="setup-recommended-actions">
            <button
              type="button"
              data-testid="setup-accept-required"
              disabled={busy || recommendedMissing.length === 0}
              onClick={acceptRequiredLicences}
            >
              Accept required licences
            </button>
            <button
              type="button"
              data-testid="setup-recommended-install"
              disabled={!canInstallRecommended}
              onClick={() => {
                void installRecommended();
              }}
            >
              Install recommended setup
            </button>
          </div>
        </section>

        <section className="setup-section" data-testid="setup-media-tools">
          <h2>Media tools</h2>
          <p className="setup-note">
            FFmpeg and FFprobe are downloaded by this setup. They are not a
            system prerequisite and do not need to be installed beforehand.
          </p>
          <ul className="setup-tool-list">
            {Object.entries(status.mediaTools).map(([name, tool]) => (
              <li key={name}>
                <span>{name}</span>
                <span className="setup-muted">
                  {tool.version ? `${tool.version} · ` : ""}
                  {tool.license ?? "GPL-3.0-or-later"}
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
              aria-label="Accept media tools licences"
              checked={mediaConsent}
              onChange={(event) => setMediaConsent(event.target.checked)}
            />
            I accept the FFmpeg/FFprobe GPL-3.0 licences.
          </label>
          <button
            type="button"
            data-testid="setup-media-install"
            disabled={busy || mediaToolsInstalled || !mediaConsent}
            onClick={installMediaTools}
          >
            {mediaToolsInstalled
              ? "Media tools installed"
              : "Install media tools"}
          </button>
          {mediaLicence && (
            <div className="setup-action-links" data-testid="setup-media-links">
              <a
                href={mediaLicence.licenceUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Licence
              </a>
              <a
                href={mediaLicence.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Source
              </a>
            </div>
          )}
        </section>

        <section className="setup-section" data-testid="setup-checks">
          <h2>System checks</h2>
          <ul className="setup-check-list">
            {Object.entries(status.checks)
              .filter(([name]) => name !== "ffmpeg" && name !== "ffprobe")
              .map(([name, check]) => (
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
            Sonic Annotator or Sonic Visualiser and the Vamp plugin pack are
            GPL/AGPL licensed and required for chord and tempo analysis.
          </p>
          <p className="setup-note" data-testid="setup-windows-uac">
            On Windows, the Vamp plugin pack may show one UAC prompt. Approve it
            to finish the tool installation; denying it stops setup and you can
            retry.
          </p>
          <ul className="setup-tool-list">
            {Object.entries(status.tools).map(([name, tool]) => (
              <li key={name}>
                <span>{tool.name ?? name.replaceAll("_", " ")}</span>
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
          <div className="setup-action-links" data-testid="setup-tools-links">
            <a
              href={toolLicenceLink("sonic_visualiser").licenceUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              Sonic licence
            </a>
            <a
              href={toolLicenceLink("vamp_plugin_pack").licenceUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              Vamp licence
            </a>
            <a
              href={toolLicenceLink("vamp_plugin_pack").sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              Source
            </a>
          </div>
        </section>

        <section className="setup-section" data-testid="setup-environments">
          <h2>Inference environment</h2>
          <p className="setup-note">
            Choose one PyTorch environment. CPU works everywhere; CUDA needs an
            NVIDIA GPU and driver.
          </p>
          <div className="setup-environment-options">
            {(["cpu", "cuda"] as const)
              .filter((choice) => status.environments[choice] !== undefined)
              .map((choice) => (
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
          {environmentLicence && (
            <div className="setup-action-links" data-testid="setup-env-links">
              <a
                href={environmentLicence.licenceUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Licence
              </a>
              <a
                href={environmentLicence.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Source
              </a>
            </div>
          )}
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
          {demucsLicence && (
            <div className="setup-action-links" data-testid="setup-model-links">
              <a
                href={demucsLicence.licenceUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Licence
              </a>
              <a
                href={demucsLicence.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Source
              </a>
            </div>
          )}
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
