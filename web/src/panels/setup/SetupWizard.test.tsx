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
    const checks = screen.getByTestId("setup-checks");
    expect(checks).toHaveTextContent("glibc");
    expect(checks).toHaveTextContent("ffmpeg is not on PATH");
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

  it("installs a chosen environment and selected consented models", async () => {
    const client = createFakeSetupClient(incompleteSetupStatus());
    renderWizard(client);

    fireEvent.click(screen.getByLabelText("CPU environment"));
    expect(screen.getByLabelText("CPU environment")).toBeChecked();
    fireEvent.click(screen.getByTestId("setup-env-install"));
    await waitFor(() => expect(client.calls).toContain("environment:cpu"));

    const card = screen.getByTestId("setup-model-card-scnet-xl-ihf");
    fireEvent.click(within(card).getByLabelText("Select SCNet XL IHF"));
    expect(screen.getByTestId("setup-model-install")).toBeDisabled();
    fireEvent.click(within(card).getByLabelText("Accept SCNet XL IHF licence"));
    expect(screen.getByTestId("setup-model-install")).toBeEnabled();
    fireEvent.click(screen.getByTestId("setup-model-install"));
    await waitFor(() =>
      expect(client.calls).toContain("models:scnet-xl-ihf:true"),
    );
  });
});
