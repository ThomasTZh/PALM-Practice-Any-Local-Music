import "@testing-library/jest-dom/vitest";

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  createFakeSetupClient,
  incompleteSetupStatus,
} from "../../state/fakeSetup";
import type { SetupJobState, SetupStatus } from "../../state/setup";
import { SetupWizard } from "./SetupWizard";

function job(
  status: SetupJobState["status"],
  progress: number,
  overrides: Partial<SetupJobState> = {},
): SetupJobState {
  return {
    id: "setup-job-1",
    status,
    progress,
    message: status,
    error: null,
    ...overrides,
  };
}

function statusWith(update: (status: SetupStatus) => SetupStatus): SetupStatus {
  return update(incompleteSetupStatus());
}

function renderWizard(
  client = createFakeSetupClient(incompleteSetupStatus()),
  pollIntervalMs = 1,
) {
  const onStatus = vi.fn();
  const onClose = vi.fn();
  const view = render(
    <SetupWizard
      client={client}
      status={client.getStatus()}
      onStatus={onStatus}
      onClose={onClose}
      pollIntervalMs={pollIntervalMs}
    />,
  );
  return { client, onStatus, onClose, view };
}

describe("SetupWizard", () => {
  it("shows checks, optional tools, environments and three equal model cards", () => {
    renderWizard();

    expect(screen.getByTestId("setup-wizard")).toBeInTheDocument();
    expect(screen.getByTestId("setup-early-warning")).toHaveTextContent(
      "Early version 0.1.0-dev",
    );
    const checks = screen.getByTestId("setup-checks");
    expect(checks).toHaveTextContent("glibc");
    expect(checks).not.toHaveTextContent("ffmpeg");
    const tools = screen.getByTestId("setup-tools");
    expect(tools).toHaveTextContent("GPL");
    expect(tools).toHaveTextContent("AGPL");
    expect(screen.getByTestId("setup-tools-install")).toBeDisabled();

    const environments = screen.getByTestId("setup-environments");
    expect(environments).toHaveTextContent("~500 MB download");
    expect(environments).toHaveTextContent("~3.5 GB download");
    expect(screen.getByLabelText("CPU environment")).not.toBeChecked();
    expect(screen.getByLabelText("CUDA environment")).not.toBeChecked();
    expect(screen.getByTestId("setup-env-install")).toBeDisabled();

    const models = screen.getByTestId("setup-models");
    expect(models.querySelectorAll(".setup-model-card")).toHaveLength(3);
    expect(models).toHaveTextContent("Demucs htdemucs_ft");
    expect(models).toHaveTextContent("SCNet XL IHF");
    expect(models).toHaveTextContent("BS-RoFormer-SW");
    for (const model of [
      "Demucs htdemucs_ft",
      "SCNet XL IHF",
      "BS-RoFormer-SW",
    ]) {
      expect(screen.getByLabelText(`Select ${model}`)).not.toBeChecked();
      expect(
        screen.getByLabelText(`Accept ${model} licence`),
      ).not.toBeChecked();
    }
    expect(screen.getByTestId("setup-model-install")).toBeDisabled();
  });

  it("shows every downloadable component and full bundled licences before download", () => {
    renderWizard();
    const summary = screen.getByTestId("setup-licence-summary");
    expect(summary).toHaveTextContent("Before downloading");
    for (const id of [
      "media-ffmpeg",
      "media-ffprobe",
      "tool-sonic",
      "tool-vamp",
      "environment-cpu",
      "environment-cuda",
      "model-htdemucs_ft",
      "model-scnet-xl-ihf",
      "model-bs-roformer-sw",
    ]) {
      expect(summary).toContainElement(
        screen.getByTestId(`licence-component-${id}`),
      );
    }
    const ffmpeg = screen.getByTestId("licence-component-media-ffmpeg");
    expect(ffmpeg).toHaveTextContent("ffmpeg");
    expect(ffmpeg).toHaveTextContent(/9\.0\.2|8\.1\.2/);
    expect(ffmpeg).toHaveTextContent("GPL-3.0-or-later");
    expect(ffmpeg).toHaveTextContent("Required");
    expect(screen.getByTestId("licence-component-tool-vamp")).toHaveTextContent(
      "Optional",
    );
    expect(
      screen.getByTestId("licence-source-media-ffmpeg").getAttribute("href"),
    ).toMatch(/ffmpeg\.martin-riedl\.de|gyan\.dev/);
    expect(
      screen.getByTestId("licence-source-model-bs-roformer-sw"),
    ).toHaveAttribute(
      "href",
      "https://huggingface.co/FractalSurfer/BS-RoFormer-SW-6stem/tree/2b98254b19bdab07ce225d884ec4aa9dd8aafce1",
    );
    expect(
      screen.getByTestId("licence-component-environment-cpu"),
    ).toHaveTextContent("~500 MB download");
    expect(screen.getByTestId("licence-text-GPL-3.0")).toHaveTextContent(
      "GNU GENERAL PUBLIC LICENSE",
    );
    expect(screen.getByTestId("licence-text-AGPL-3.0")).toHaveTextContent(
      "GNU AFFERO GENERAL PUBLIC LICENSE",
    );
    expect(screen.getByTestId("setup-media-tools")).toHaveTextContent(
      "not a system prerequisite",
    );
    expect(screen.getByTestId("setup-windows-uac")).toHaveTextContent(
      "may show one UAC prompt",
    );
    expect(screen.getByTestId("setup-windows-uac")).not.toHaveTextContent(
      /no admin|no-admin|without.*admin/i,
    );
    expect(screen.getByTestId("setup-media-install")).toBeDisabled();
    expect(screen.getByTestId("setup-recommended-install")).toBeDisabled();
  });

  it("shows bundled components, full PSF/Apache/MIT/BSD texts and the FFmpeg caveat", () => {
    renderWizard();

    expect(
      screen.getByTestId("setup-download-licence-details"),
    ).not.toHaveAttribute("open");
    expect(screen.getByTestId("setup-bundled-components")).not.toHaveAttribute(
      "open",
    );
    const bundled = screen.getByTestId("setup-bundled-components");
    expect(bundled).toHaveTextContent("Bundled third-party components");
    expect(screen.getByTestId("bundled-component-python")).toHaveTextContent(
      "3.11.15",
    );
    expect(screen.getByTestId("bundled-component-python")).toHaveTextContent(
      "PSF-2.0",
    );
    expect(screen.getByTestId("bundled-component-uv")).toHaveTextContent(
      "0.12.0",
    );
    expect(screen.getByTestId("bundled-component-uv")).toHaveTextContent(
      /MIT.*Apache-2.0/,
    );
    expect(
      screen.getByTestId("bundled-component-python-fastapi"),
    ).toHaveTextContent("0.142.0");
    expect(screen.getByTestId("bundled-component-react")).toHaveTextContent(
      "19.3.0",
    );
    expect(screen.getByTestId("bundled-source-python")).toHaveAttribute(
      "href",
      "https://github.com/astral-sh/python-build-standalone/releases/tag/20260728",
    );
    expect(
      screen.getByTestId("bundled-licence-text-PSF-2.0"),
    ).toHaveTextContent("Python Software Foundation");
    expect(
      screen.getByTestId("bundled-licence-text-Apache-2.0"),
    ).toHaveTextContent("Apache License");
    expect(screen.getByTestId("bundled-licence-text-MIT")).toHaveTextContent(
      "Permission is hereby granted",
    );
    expect(
      screen.getByTestId("bundled-licence-text-BSD-3-Clause"),
    ).toHaveTextContent("Redistribution and use");

    const caveat = screen.getByTestId("setup-ffmpeg-nonfree");
    expect(caveat).toHaveTextContent("GPL-3.0-or-later");
    expect(caveat).toHaveTextContent("--enable-nonfree");
    expect(caveat).toHaveTextContent("not legally redistributable");
    expect(caveat).toHaveTextContent("PALM downloads it");
    expect(caveat).toHaveTextContent("does not bundle");
  });

  it("uses platform tool names and hides unsupported CUDA", () => {
    const status = statusWith((value) => ({
      ...value,
      environments: { cpu: value.environments.cpu },
      tools: {
        ...value.tools,
        sonic_visualiser: {
          ...value.tools.sonic_visualiser,
          name: "Sonic Annotator",
        },
      },
    }));
    renderWizard(createFakeSetupClient(status));

    expect(screen.getByTestId("setup-tools")).toHaveTextContent(
      "Sonic Annotator",
    );
    expect(screen.queryByLabelText("CUDA environment")).toBeNull();
    expect(screen.getByLabelText("CPU environment")).toBeInTheDocument();
  });

  it("links every tool and model licence safely and can scroll by keyboard", () => {
    renderWizard();
    const page = screen.getByTestId("setup-wizard");
    expect(page).toHaveClass("setup-page");
    expect(page).toHaveAttribute("tabindex", "0");
    expect((page as HTMLElement).style.overflowY).toBe("auto");

    const expected: Array<[string, string]> = [
      [
        "tool-licence-sonic_visualiser",
        "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html",
      ],
      [
        "tool-source-sonic_visualiser",
        "https://github.com/sonic-visualiser/sonic-visualiser",
      ],
      [
        "tool-licence-vamp_plugin_pack",
        "https://www.gnu.org/licenses/agpl-3.0.html",
      ],
      [
        "tool-source-vamp_plugin_pack",
        "https://github.com/c4dm/qm-vamp-plugins",
      ],
      [
        "model-licence-htdemucs_ft",
        "https://github.com/facebookresearch/demucs/blob/main/LICENSE",
      ],
      [
        "model-licence-scnet-xl-ihf",
        "https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/main/LICENSE",
      ],
      [
        "model-licence-bs-roformer-sw",
        "https://huggingface.co/FractalSurfer/BS-RoFormer-SW-6stem",
      ],
    ];
    for (const [testId, href] of expected) {
      const link = screen.getByTestId(testId);
      expect(link.tagName).toBe("A");
      expect(link).toHaveAttribute("href", href);
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
    // Licence text stays visible inside the anchors.
    expect(
      screen.getByTestId("tool-licence-sonic_visualiser"),
    ).toHaveTextContent("GPL-2.0-or-later");
    expect(screen.getByTestId("model-licence-scnet-xl-ihf")).toHaveTextContent(
      /MIT/,
    );
  });

  it("skips to the library and can be reopened", async () => {
    const client = createFakeSetupClient(incompleteSetupStatus());
    const { onStatus, onClose } = renderWizard(client);

    fireEvent.click(screen.getByTestId("setup-skip"));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onStatus).toHaveBeenCalledWith(
      expect.objectContaining({ skipped: true }),
    );
    expect(client.calls).toContain("skip:true");
  });

  it("installs tools with consent and determinate progress", async () => {
    const client = createFakeSetupClient(incompleteSetupStatus());
    const after = statusWith((status) => ({
      ...status,
      tools: {
        sonic_visualiser: { ...status.tools.sonic_visualiser, installed: true },
        vamp_plugin_pack: { ...status.tools.vamp_plugin_pack, installed: true },
      },
    }));
    let current = client.getStatus();
    client.status = vi.fn(async () => {
      client.calls.push("status");
      return current;
    });
    let resolveJob: (state: SetupJobState) => void = () => undefined;
    client.job = vi.fn(
      () =>
        new Promise<SetupJobState>((resolve) => {
          resolveJob = resolve;
        }),
    );
    const { onStatus } = renderWizard(client);

    fireEvent.click(screen.getByLabelText("Accept GPL tool licences"));
    fireEvent.click(screen.getByTestId("setup-tools-install"));

    const progress = await screen.findByTestId("setup-progress");
    expect(progress).toHaveAttribute("aria-valuenow", "0");
    resolveJob(job("running", 0.5, { message: "installing Vamp" }));
    await waitFor(() =>
      expect(screen.getByTestId("setup-progress")).toHaveAttribute(
        "aria-valuenow",
        "50",
      ),
    );
    current = after;
    resolveJob(job("succeeded", 1, { message: "tools installed" }));
    await waitFor(() => expect(onStatus).toHaveBeenCalled());
    expect(onStatus).toHaveBeenCalledWith(
      expect.objectContaining({
        tools: expect.objectContaining({
          sonic_visualiser: expect.objectContaining({ installed: true }),
        }),
      }),
    );
    expect(client.calls).toContain("tools:true");
    expect(client.calls).toContain("status");
  });

  it("cancels a running setup operation", async () => {
    const client = createFakeSetupClient(incompleteSetupStatus());
    client.enqueueJob(job("running", 0.2));
    const view = render(
      <SetupWizard
        client={client}
        status={client.getStatus()}
        onStatus={vi.fn()}
        onClose={vi.fn()}
        pollIntervalMs={1_000}
      />,
    );
    fireEvent.click(screen.getByLabelText("Accept GPL tool licences"));
    fireEvent.click(screen.getByTestId("setup-tools-install"));
    expect(await screen.findByTestId("setup-progress")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("setup-cancel"));

    await waitFor(() =>
      expect(screen.getByTestId("setup-error")).toHaveTextContent("cancelled"),
    );
    expect(client.calls.some((call) => call.startsWith("cancel:"))).toBe(true);
    view.unmount();
  });

  it("shows an actionable error and retries the operation", async () => {
    const client = createFakeSetupClient(incompleteSetupStatus());
    client.enqueueJob(
      job("failed", 0.4, {
        message: "download failed",
        error: "download failed: HTTP 503",
      }),
    );
    const { onStatus } = renderWizard(client);
    fireEvent.click(screen.getByLabelText("Accept GPL tool licences"));
    fireEvent.click(screen.getByTestId("setup-tools-install"));

    expect(await screen.findByTestId("setup-error")).toHaveTextContent(
      "download failed: HTTP 503",
    );
    expect(screen.getByTestId("setup-retry")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("setup-retry"));

    await waitFor(() => expect(onStatus).toHaveBeenCalled());
    expect(client.calls.filter((call) => call === "tools:true")).toHaveLength(
      2,
    );
  });

  it("surfaces environment consent rejection once and offers retry", async () => {
    const client = createFakeSetupClient(incompleteSetupStatus());
    const startEnvironment = vi.fn(async () => {
      throw new Error(
        "licence acceptance is required before installing environments",
      );
    });
    client.startEnvironment = startEnvironment;
    renderWizard(client);

    fireEvent.click(screen.getByLabelText("CPU environment"));
    fireEvent.click(screen.getByLabelText("Accept CPU environment licence"));
    fireEvent.click(screen.getByTestId("setup-env-install"));

    expect(await screen.findByTestId("setup-error")).toHaveTextContent(
      "licence acceptance is required before installing environments",
    );
    expect(startEnvironment).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("setup-retry")).toBeInTheDocument();
    await new Promise((resolve) => window.setTimeout(resolve, 30));
    expect(startEnvironment).toHaveBeenCalledTimes(1);
  });

  it("requires a fresh consent when switching environment flavour", () => {
    renderWizard(createFakeSetupClient(incompleteSetupStatus()));

    fireEvent.click(screen.getByLabelText("CPU environment"));
    fireEvent.click(screen.getByLabelText("Accept CPU environment licence"));
    expect(screen.getByTestId("setup-env-install")).toBeEnabled();

    fireEvent.click(screen.getByLabelText("CUDA environment"));
    expect(
      screen.getByLabelText("Accept CUDA environment licence"),
    ).not.toBeChecked();
    expect(screen.getByTestId("setup-env-install")).toBeDisabled();
  });

  it("states missing consents and accepts required licences explicitly", () => {
    renderWizard();

    const recommended = screen.getByTestId("setup-recommended-install");
    expect(recommended).toBeDisabled();
    const reason = screen.getByTestId("setup-recommended-reason");
    expect(reason).toHaveTextContent("accept the FFmpeg/FFprobe licence");
    expect(reason).toHaveTextContent("accept the analysis tool licences");
    expect(reason).toHaveTextContent("select CPU and accept");
    expect(reason).toHaveTextContent("accept the Demucs licence");

    for (const id of [
      "setup-recommended-links",
      "setup-media-links",
      "setup-tools-links",
      "setup-env-links",
      "setup-model-links",
    ]) {
      const links = within(screen.getByTestId(id)).getAllByRole("link");
      expect(links.length).toBeGreaterThanOrEqual(2);
      for (const link of links) {
        expect(link).toHaveAttribute("target", "_blank");
        expect(link).toHaveAttribute("rel", "noopener noreferrer");
        expect(link.getAttribute("href")).toMatch(/^https:\/\//);
      }
    }

    fireEvent.click(screen.getByTestId("setup-accept-required"));
    expect(screen.getByLabelText("Accept media tools licences")).toBeChecked();
    expect(screen.getByLabelText("Accept GPL tool licences")).toBeChecked();
    expect(screen.getByLabelText("CPU environment")).toBeChecked();
    expect(
      screen.getByLabelText("Accept CPU environment licence"),
    ).toBeChecked();
    expect(
      screen.getByLabelText("Accept Demucs htdemucs_ft licence"),
    ).toBeChecked();
    expect(screen.getByTestId("setup-recommended-reason")).toHaveTextContent(
      "All required licences are accepted",
    );
    expect(screen.getByTestId("setup-recommended-install")).toBeEnabled();
  });

  it("installs the recommended stack and visibly selects editable Demucs", async () => {
    const client = createFakeSetupClient(incompleteSetupStatus());
    const installOrder: string[] = [];
    const startMediaTools = vi.fn(async () => {
      installOrder.push("media");
      return job("queued", 0);
    });
    const startTools = vi.fn(async () => {
      installOrder.push("tools");
      return job("queued", 0);
    });
    const startEnvironment = vi.fn(async () => {
      installOrder.push("environment");
      return job("queued", 0);
    });
    const startModels = vi.fn(async () => {
      installOrder.push("models");
      return job("queued", 0);
    });
    client.startMediaTools = startMediaTools;
    client.startTools = startTools;
    client.startEnvironment = startEnvironment;
    client.startModels = startModels;
    renderWizard(client);

    fireEvent.click(screen.getByLabelText("Accept media tools licences"));
    fireEvent.click(screen.getByLabelText("Accept GPL tool licences"));
    fireEvent.click(screen.getByLabelText("CPU environment"));
    fireEvent.click(screen.getByLabelText("Accept CPU environment licence"));
    fireEvent.click(screen.getByLabelText("Select Demucs htdemucs_ft"));
    fireEvent.click(screen.getByLabelText("Accept Demucs htdemucs_ft licence"));

    const recommended = screen.getByTestId("setup-recommended-install");
    expect(recommended).toBeEnabled();
    fireEvent.click(recommended);
    expect(screen.getByLabelText("Select Demucs htdemucs_ft")).toBeChecked();

    await waitFor(() =>
      expect(startModels).toHaveBeenCalledWith(
        ["htdemucs_ft"],
        ["htdemucs_ft"],
      ),
    );
    await waitFor(() =>
      expect(installOrder).toEqual(["media", "tools", "environment", "models"]),
    );
    expect(startMediaTools).toHaveBeenCalledWith(true);
    expect(startTools).toHaveBeenCalledWith(true);
    expect(startEnvironment).toHaveBeenCalledWith("cpu", true);
    expect(
      screen.getByTestId("setup-model-card-scnet-xl-ihf"),
    ).toBeInTheDocument();
    fireEvent.click(
      within(
        screen.getByTestId("setup-model-card-scnet-xl-ihf"),
      ).getByLabelText("Select SCNet XL IHF"),
    );
    expect(screen.getByLabelText("Select SCNet XL IHF")).toBeChecked();
  });

  it("installs a chosen environment and selected consented models", async () => {
    const client = createFakeSetupClient(incompleteSetupStatus());
    const startEnvironment = vi.fn(async () =>
      job("queued", 0, { id: "environment-job" }),
    );
    const startModels = vi.fn(async () =>
      job("queued", 0, { id: "models-job" }),
    );
    client.startEnvironment = startEnvironment;
    client.startModels = startModels;
    renderWizard(client);

    fireEvent.click(screen.getByLabelText("CPU environment"));
    expect(screen.getByLabelText("CPU environment")).toBeChecked();
    expect(screen.getByTestId("setup-env-install")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Accept CPU environment licence"));
    expect(screen.getByTestId("setup-env-install")).toBeEnabled();
    fireEvent.click(screen.getByTestId("setup-env-install"));
    await waitFor(() =>
      expect(startEnvironment).toHaveBeenCalledWith("cpu", true),
    );

    const card = screen.getByTestId("setup-model-card-scnet-xl-ihf");
    fireEvent.click(within(card).getByLabelText("Select SCNet XL IHF"));
    expect(screen.getByTestId("setup-model-install")).toBeDisabled();
    fireEvent.click(screen.getByTestId("setup-model-install"));
    expect(
      client.calls.filter((call) => call.startsWith("models:")),
    ).toHaveLength(0);
    fireEvent.click(within(card).getByLabelText("Accept SCNet XL IHF licence"));
    // Consent for an unselected model is not sent as an accepted id.
    fireEvent.click(
      within(
        screen.getByTestId("setup-model-card-bs-roformer-sw"),
      ).getByLabelText("Accept BS-RoFormer-SW licence"),
    );
    expect(screen.getByTestId("setup-model-install")).toBeEnabled();
    fireEvent.click(screen.getByTestId("setup-model-install"));
    await waitFor(() =>
      expect(startModels).toHaveBeenCalledWith(
        ["scnet-xl-ihf"],
        ["scnet-xl-ihf"],
      ),
    );
  });
});
