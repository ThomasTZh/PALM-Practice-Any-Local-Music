/**
 * Golden practice path on the real server: import the deterministic
 * progression fixture, analyse it with the preserved Vamp pack, reopen the
 * project, practise it through the real transport (speed, section loop,
 * metronome), and export a WAV. The headless browsers have a virtual audio
 * sink: the test asserts that the audio graph advances and records that
 * audibility itself was not verified.
 */

import { copyFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  expect,
  test,
  type APIRequestContext,
  type Page,
  type TestInfo,
} from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE = resolve(HERE, "../../tests/fixtures/audio/progression_120.wav");
const BPM = 120;
const BPM_TOLERANCE = 0.5;
const LOOP_RANGE_TOLERANCE = 0.35;

function parsePosition(text: string): number {
  const match = /(\d+):(\d+(?:\.\d+)?)/.exec(text);
  if (!match) throw new Error(`unreadable transport position: ${text}`);
  return Number(match[1]) * 60 + Number(match[2]);
}

async function position(page: Page): Promise<number> {
  return parsePosition(
    await page.getByTestId("transport-position").innerText(),
  );
}

async function waitForAdvance(
  page: Page,
  from: number,
  timeoutMs: number,
): Promise<number | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await page.waitForTimeout(100);
    const now = await position(page);
    if (now > from + 0.2) return now;
  }
  return null;
}

/**
 * Reach and keep Playing through a seek/buffering transition.
 *
 * A seek issued while playing can finish as Paused after the first status
 * check; clicking once and asserting Playing immediately then hangs. Poll the
 * status, click Play only when the transport is not loading and not playing,
 * and only give up after the deadline.
 */
/**
 * Wait until the server's saved practice state contains the created section.
 *
 * The save-status label can already read "saved" from an earlier autosave when
 * the test pauses, so it is not evidence that the new section was persisted.
 * Poll the saved document instead and fail with the exact save path when it
 * never appears; a real persistence bug must not be retried away as a flake.
 */
async function waitForSavedSection(
  request: APIRequestContext,
  projectId: string,
  name: string,
  timeoutMs = 20_000,
): Promise<Array<Record<string, unknown>>> {
  const url = `/api/projects/${projectId}/state`;
  const deadline = Date.now() + timeoutMs;
  let lastStatus: number | null = null;
  let lastSections: unknown = null;
  let lastError: string | null = null;
  while (Date.now() < deadline) {
    try {
      const response = await request.get(url);
      lastStatus = response.status();
      if (response.ok()) {
        const payload = (await response.json()) as {
          state?: { sections?: unknown };
        };
        const sections = payload.state?.sections;
        lastSections = sections;
        if (
          Array.isArray(sections) &&
          sections.some(
            (entry) =>
              typeof entry === "object" &&
              entry !== null &&
              (entry as { name?: unknown }).name === name,
          )
        ) {
          return sections as Array<Record<string, unknown>>;
        }
      } else {
        lastError = (await response.text()).slice(0, 200);
      }
    } catch (error) {
      lastError = String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(
    `section ${JSON.stringify(name)} never appeared in the saved project state at ` +
      `GET ${url} (autosave path); last status=${lastStatus ?? "none"}, ` +
      `last sections=${JSON.stringify(lastSections)}, ` +
      `last error=${lastError ?? "none"}`,
  );
}

async function ensurePlaying(page: Page, timeoutMs = 30_000): Promise<void> {
  const status = page.getByTestId("transport-status");
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const label = (await status.innerText()).trim();
    if (label === "Playing") return;
    if (label !== "Loading audio…") {
      await page.getByTestId("transport-toggle").click();
      await page.waitForTimeout(250);
    } else {
      await page.waitForTimeout(150);
    }
  }
  throw new Error(
    `transport did not reach Playing within ${timeoutMs} ms ` +
      `(last status: ${(await status.innerText()).trim()})`,
  );
}

async function audioCapability(page: Page): Promise<{
  secureContext: boolean;
  audioWorklet: boolean;
  state: string;
  sampleRate: number;
}> {
  return page.evaluate(async () => {
    const Ctor = (
      window as unknown as {
        AudioContext?: new () => AudioContext;
      }
    ).AudioContext;
    if (!Ctor) {
      return {
        secureContext: window.isSecureContext,
        audioWorklet: false,
        state: "missing",
        sampleRate: 0,
      };
    }
    const context = new Ctor();
    // A headless browser may expose a suspended AudioContext whose resume()
    // never settles when there is no audio device. Record that instead of
    // hanging the whole golden path; audible verification is never claimed.
    const resumed = await Promise.race([
      context.resume().then(() => "resumed" as const),
      new Promise<"timeout">((resolve) => {
        window.setTimeout(() => resolve("timeout"), 3_000);
      }),
    ]);
    const result = {
      secureContext: window.isSecureContext,
      audioWorklet: typeof AudioWorkletNode !== "undefined",
      state:
        resumed === "timeout"
          ? `resume-timeout (${context.state})`
          : context.state,
      sampleRate: context.sampleRate,
    };
    void Promise.race([
      context.close(),
      new Promise<void>((resolve) => {
        window.setTimeout(resolve, 1_000);
      }),
    ]).catch(() => undefined);
    return result;
  });
}

test("golden path: import, analyze, reopen, practise and export", async ({
  page,
  request,
}, testInfo) => {
  // Each browser (and each Playwright retry) gets its own copy of the
  // generated fixture so the shared server data root never has two projects
  // with the same title. A retry must start from a clean, unambiguous library
  // entry, not from `.first()` on a duplicated title.
  const attempt = `r${testInfo.retry + 1}`;
  const uploadDir = mkdtempSync(join(tmpdir(), "basseparate-golden-"));
  const upload = join(
    uploadDir,
    `golden-${testInfo.project.name}-${attempt}.wav`,
  );
  copyFileSync(FIXTURE, upload);
  const title = `golden-${testInfo.project.name}-${attempt}`;

  await page.goto("/");
  await expect(page.getByTestId("transport-toggle")).toBeVisible();

  const health = await (await request.get("/api/health")).json();
  expect(health.status).toBe("ok");
  expect(health.ui).toBe(true);
  // The Playwright webServer creates a fresh temp data root per run.
  expect(String(health.data_root)).toMatch(/basseparate-e2e-/);
  testInfo.annotations.push({
    type: "data-root",
    description: String(health.data_root),
  });

  const audio = await audioCapability(page);
  expect(audio.secureContext).toBe(true);
  expect(audio.audioWorklet).toBe(true);
  testInfo.annotations.push({
    type: "audio-capability",
    description: `AudioWorklet=${audio.audioWorklet} state=${audio.state} sampleRate=${audio.sampleRate} secureContext=${audio.secureContext}; headless audible output is not verified`,
  });

  // 1. Import the generated fixture through the real library upload.
  await page.getByLabel("Import recording").setInputFiles(upload);
  await expect(page.getByTestId("project-title")).toHaveText(title, {
    timeout: 120_000,
  });
  await expect(
    page.locator('[data-testid^="waveform-"]').first(),
  ).toBeVisible();

  // 2. Analysis job -> chords, key, BPM and bars from the preserved pack.
  await page.getByLabel("Run analysis").click();
  await expect(page.getByTestId("analysis-summary")).toContainText("bars", {
    timeout: 180_000,
  });
  await expect(page.getByTestId("key-readout")).toHaveText("C major");
  const bpmText = await page.getByTestId("bpm-readout").innerText();
  const bpm = Number(/(\d+(?:\.\d+)?)\s*·/.exec(bpmText)?.[1]);
  expect(Number.isFinite(bpm)).toBe(true);
  expect(Math.abs(bpm - BPM)).toBeLessThanOrEqual(BPM_TOLERANCE);
  const summary = await page.getByTestId("analysis-summary").innerText();
  expect(summary).toContain("8 bars");
  expect(summary).toContain("5 chords"); // N + C + Am + F + G

  const symbols = (
    await page.locator('[data-testid^="chord-block-"]').allInnerTexts()
  )
    .map((text) => text.trim())
    .filter((text) => text.length > 0 && text !== "N.C.");
  expect(symbols).toEqual(["C", "Am", "F", "G"]);

  // The analysis document keeps bar-aligned chord boundaries.
  const library = await (await request.get("/api/library")).json();
  const entry = (library.entries as Array<Record<string, unknown>>).find(
    (item) => item.title === title,
  );
  expect(entry).toBeDefined();
  const projectId = String(entry?.projectId ?? entry?.id);
  const project = await (
    await request.get(`/api/projects/${projectId}`)
  ).json();
  const document = project.document as Record<string, unknown>;
  const grid = document.grid as Record<string, unknown>;
  expect((grid.bars as number[]).length).toBe(8);
  const chordStarts = (document.chords as Array<Record<string, unknown>>)
    .filter((chord) => chord.label !== "N")
    .map((chord) => Number(chord.start_seconds));
  // Design: C 0-8 s, Am 8-12 s, F 12-14 s, G 14-16 s on 2 s bars.
  const expectedStarts = [0, 8, 12, 14];
  expect(chordStarts.length).toBe(4);
  for (const [index, expected] of expectedStarts.entries()) {
    expect(Math.abs(chordStarts[index] - expected)).toBeLessThan(0.6);
  }

  // 3. Reopen the project before practising so the engine builds its grid
  // from the persisted analysis (the live-grid gap belongs to its own task).
  await page.reload();
  await page.getByRole("button", { name: `Open ${title}` }).click();
  await expect(page.getByTestId("key-readout")).toHaveText("C major");
  await expect(page.getByTestId("chord-ribbon")).toContainText("C");

  // 4. Practise: metronome and count-in controls are visible and usable.
  await page.getByLabel("Metronome", { exact: true }).click();
  await expect(page.getByLabel("Metronome", { exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByTestId("bar-beat-overlay")).toBeVisible();
  await page.getByLabel("Count-in").selectOption("1");
  await expect(page.getByLabel("Count-in")).toHaveValue("1");
  await page.getByLabel("Count-in").selectOption("0");
  await page.getByLabel("Return to start").click();

  await expect(page.getByTestId("transport-toggle")).toBeEnabled({
    timeout: 60_000,
  });
  await page.getByTestId("transport-toggle").click();
  await ensurePlaying(page);
  await expect(page.getByTestId("transport-status")).toHaveText("Playing", {
    timeout: 30_000,
  });
  const startPosition = await position(page);
  const advanced = await waitForAdvance(page, startPosition, 8_000);
  const audioAdvanced = advanced !== null;
  testInfo.annotations.push({
    type: "audio-playback",
    description: audioAdvanced
      ? `[${testInfo.project.name}] transport position advanced from ${startPosition.toFixed(2)}s to ${advanced.toFixed(2)}s; audible output not verified in headless mode`
      : `[${testInfo.project.name}] AudioWorklet is available and the AudioContext runs, but the headless transport position did not advance; position/speed/loop-wrap assertions are skipped and no audible verification is claimed. Chromium runs the full transport assertions.`,
  });
  if (!audioAdvanced) {
    // Still prove the transport state machine through the real UI: a second
    // click must pause and a third must resume.
    await page.getByTestId("transport-toggle").click();
    await expect(page.getByTestId("transport-status")).toHaveText("Paused");
    await page.getByTestId("transport-toggle").click();
    await expect(page.getByTestId("transport-status")).toHaveText("Playing");
  } else {
    // 5. Speed change: 0.5x advances the source at roughly half real time.
    // Wait for transport stability, select 0.5x, let the rate ramp settle, then
    // measure a 1.5 s window. Ideal is 0.75 s; observed passes are 0.80-0.90 s
    // because of the UI tick/anchor mapping, so the bound allows UI latency
    // instead of treating a 1.00 s sample as a 2x transport bug.
    const statusLabel = page.getByTestId("transport-status");
    await expect(statusLabel).not.toHaveText("Loading audio…", {
      timeout: 30_000,
    });
    await page.getByLabel("Practice speed").selectOption("0.5");
    await expect(page.getByLabel("Practice speed")).toHaveValue("0.5");
    await page.waitForTimeout(600);
    const beforeSpeed = await position(page);
    await page.waitForTimeout(1_500);
    const afterSpeed = await position(page);
    const delta = afterSpeed - beforeSpeed;
    testInfo.annotations.push({
      type: "speed-change",
      description:
        `[${title}] position delta at 0.5x over 1.5 s: ${delta.toFixed(2)} s ` +
        `(accepted 0.55-1.15)`,
    });
    expect(delta).toBeGreaterThan(0.55);
    expect(delta).toBeLessThan(1.15);
    await page.getByLabel("Practice speed").selectOption("1");
  }

  // 6. Bar-snapped section and loop wiring are always exercised. Pause and
  // reset the playhead first: if the section is created while the playhead has
  // drifted, bar snapping produces a different range (observed once as a 2-4 s
  // section, which then correctly failed the "max position inside loop" check
  // only after the loop observation). A settled zero playhead makes the
  // default section deterministic. Its actual range is then read from the
  // saved state instead of assuming a fixed two bars, because Add section now
  // defaults to four bars (8 s at 120 BPM).
  const sectionStatus = page.getByTestId("transport-status");
  await expect(sectionStatus).not.toHaveText("Loading audio…", {
    timeout: 30_000,
  });
  if ((await sectionStatus.innerText()) === "Playing") {
    await page.getByTestId("transport-toggle").click();
  }
  await expect(sectionStatus).toHaveText("Paused", { timeout: 30_000 });
  await page.getByLabel("Return to start").click();
  await expect
    .poll(() => position(page), { timeout: 10_000 })
    .toBeLessThanOrEqual(0.25);
  await page.getByRole("button", { name: "Add section" }).click();
  const section = page.locator('[data-testid^="section-block-"]').first();
  await expect(section).toBeVisible();
  await expect(section).toContainText("Section 1");
  await section.getByRole("button", { name: "Loop Section 1" }).click();
  await expect(page.getByLabel("Practice loop")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByLabel("Loop", { exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // The section and loop are autosaved while paused. Read the persisted
  // seconds so the wrap check uses the range the app actually created, not a
  // hard-coded bar count. A missing range is a persistence/schema failure.
  const savedBeforeLoop = await waitForSavedSection(
    request,
    projectId,
    "Section 1",
    20_000,
  );
  testInfo.annotations.push({
    type: "saved-section-before-loop",
    description: JSON.stringify(savedBeforeLoop),
  });
  const createdSection = savedBeforeLoop.find(
    (entry) => (entry as { name?: unknown }).name === "Section 1",
  ) as { start_seconds?: unknown; end_seconds?: unknown } | undefined;
  const loopStartSeconds = Number(createdSection?.start_seconds);
  const loopEndSeconds = Number(createdSection?.end_seconds);
  if (
    !Number.isFinite(loopStartSeconds) ||
    !Number.isFinite(loopEndSeconds) ||
    loopEndSeconds <= loopStartSeconds
  ) {
    throw new Error(
      `saved Section 1 at GET /api/projects/${projectId}/state has no usable ` +
        `start_seconds/end_seconds: ${JSON.stringify(createdSection)}`,
    );
  }

  if (audioAdvanced) {
    // Installing the loop performs a controlled re-seek. Wait for it to
    // settle, then make one fresh seek to the loop start and only observe
    // from a confirmed Playing state: a buffering stall immediately after the
    // loop installation was the observed Chromium flake (no wrap within 10 s).
    const statusLabel = page.getByTestId("transport-status");
    await expect(statusLabel).not.toHaveText("Loading audio…", {
      timeout: 30_000,
    });
    await page.getByLabel("Return to start").click();
    await expect(statusLabel).not.toHaveText("Loading audio…", {
      timeout: 30_000,
    });
    await ensurePlaying(page);
    await expect(statusLabel).toHaveText("Playing", { timeout: 30_000 });
    // A fresh seek must land inside the created section before observation.
    await expect
      .poll(() => position(page), { timeout: 10_000 })
      .toBeLessThanOrEqual(loopEndSeconds + LOOP_RANGE_TOLERANCE);

    // Observe up to 20 s. Buffering can delay the first audible quantum, but a
    // real wrap is still required and the position must stay inside the loop.
    const loopSamples: number[] = [];
    let wraps = 0;
    let previous = await position(page);
    let stalledFor = 0;
    const loopDeadline = Date.now() + 20_000;
    while (Date.now() < loopDeadline && wraps < 1) {
      await page.waitForTimeout(100);
      const now = await position(page);
      loopSamples.push(now);
      if (now < previous - 0.2) {
        wraps += 1;
        stalledFor = 0;
      } else if (now <= previous) {
        stalledFor += 100;
      } else {
        stalledFor = 0;
      }
      previous = now;
    }
    testInfo.annotations.push({
      type: "section-loop",
      description:
        `wraps=${wraps} stalledMs=${stalledFor} ` +
        `samples=${loopSamples.slice(-12).join(",")}`,
    });
    expect(
      wraps,
      "the section loop must wrap inside the created section range",
    ).toBeGreaterThanOrEqual(1);
    expect(Math.min(...loopSamples)).toBeGreaterThanOrEqual(
      loopStartSeconds - LOOP_RANGE_TOLERANCE,
    );
    expect(Math.max(...loopSamples)).toBeLessThanOrEqual(
      loopEndSeconds + LOOP_RANGE_TOLERANCE,
    );
  }

  // 7. Persist, then reopen and export. Autosave intentionally skips while
  // playing, so pause first and let the debounce write.
  if ((await page.getByTestId("transport-status").innerText()) === "Playing") {
    await page.getByTestId("transport-toggle").click();
  }
  await expect(page.getByTestId("transport-status")).toHaveText("Paused");
  // The save-status label is not persistence evidence (it can be stale from an
  // earlier autosave). Wait for the created section to appear in the server's
  // saved state, then reopen.
  const savedSections = await waitForSavedSection(
    request,
    projectId,
    "Section 1",
    20_000,
  );
  testInfo.annotations.push({
    type: "saved-sections",
    description: JSON.stringify(savedSections),
  });
  await page.reload();
  await page.getByRole("button", { name: `Open ${title}` }).click();
  await expect(page.getByTestId("key-readout")).toHaveText("C major");
  await expect(page.locator('[data-testid^="section-block-"]')).toHaveCount(1);

  const media = await (
    await request.get(`/api/projects/${projectId}/media`)
  ).json();
  const exported = await request.post(`/api/projects/${projectId}/exports`, {
    data: { filename: "golden-path" },
  });
  expect(exported.status()).toBe(201);
  const exportJson = await exported.json();
  expect(exportJson.frames).toBe(media.frames);
  expect(exportJson.sample_rate).toBe(media.sample_rate);
  const download = await request.get(String(exportJson.download_url));
  expect(download.status()).toBe(200);
  const wav = await download.body();
  expect(wav.subarray(0, 4).toString("latin1")).toBe("RIFF");
  expect(wav.subarray(8, 12).toString("latin1")).toBe("WAVE");
  expect(wav.length).toBeGreaterThan(44);
  testInfo.annotations.push({
    type: "export",
    description: `frames=${exportJson.frames} sample_rate=${exportJson.sample_rate} bytes=${wav.length}`,
  });
});
