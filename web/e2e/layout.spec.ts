/**
 * Layout regression: the rail stays visible, the stage fills the remaining
 * width, and no native scrollbar appears at 1280 or 1920 CSS pixels, even
 * after zooming the shared timeline. The custom green scrollbar is the only
 * horizontal navigation.
 */

import { copyFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE = resolve(HERE, "../../tests/fixtures/audio/progression_120.wav");

interface Box {
  left: number;
  right: number;
  width: number;
  clientWidth: number;
  scrollWidth: number;
  clientHeight: number;
  scrollHeight: number;
  overflowX: string;
  overflowY: string;
  scrollbarWidth: string;
}

async function measure(page: Page) {
  return page.evaluate(() => {
    const box = (selector: string): Box | null => {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element) return null;
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return {
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        scrollbarWidth: style.scrollbarWidth,
      };
    };
    const nativeHorizontal = Array.from(
      document.querySelectorAll<HTMLElement>("*"),
    )
      .filter((element) => {
        const style = getComputedStyle(element);
        return (
          (style.overflowX === "auto" || style.overflowX === "scroll") &&
          element.scrollWidth > element.clientWidth + 1
        );
      })
      .map((element) => ({
        tag: element.tagName,
        className: String(element.className).slice(0, 60),
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
      }));
    const main = document.querySelector<HTMLElement>(".studio-main");
    const scrollbar = document.querySelector<HTMLElement>(
      '[data-testid="timeline-scrollbar"]',
    );
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        clientHeight: document.documentElement.clientHeight,
        scrollHeight: document.documentElement.scrollHeight,
      },
      body: {
        clientWidth: document.body.clientWidth,
        scrollWidth: document.body.scrollWidth,
      },
      main: box(".studio-main"),
      rail: box('[data-testid="studio-rail"]'),
      stage: box(".stage"),
      timeline: box(".timeline"),
      transport: box(".transport"),
      greenScrollbar: scrollbar !== null,
      greenThumbWidth: (() => {
        const thumb = document.querySelector<HTMLElement>(
          '[data-testid="timeline-scrollbar-thumb"]',
        );
        return thumb ? Math.round(thumb.getBoundingClientRect().width) : null;
      })(),
      nativeHorizontal,
      mainScrollTop: main?.scrollTop ?? 0,
      hasHeader: document.querySelector(".studio-header") !== null,
    };
  });
}

async function assertNoNativeScrollbars(page: Page) {
  const data = await measure(page);
  expect(data.document.scrollWidth).toBe(data.document.clientWidth);
  expect(data.body.scrollWidth).toBe(data.body.clientWidth);
  expect(data.nativeHorizontal).toEqual([]);
  expect(data.hasHeader).toBe(false);
  return data;
}

test("layout stays full-width with no native page or timeline scrollbar", async ({
  page,
}, testInfo) => {
  const uploadDir = mkdtempSync(join(tmpdir(), "basseparate-layout-"));
  const title = `layout-${testInfo.project.name}-${Date.now()}`;
  const upload = join(uploadDir, `${title}.wav`);
  copyFileSync(FIXTURE, upload);

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(page.getByTestId("transport-toggle")).toBeVisible();
  await page.getByLabel("Import recording").setInputFiles(upload);
  await expect(page.getByTestId("project-title")).toHaveText(title, {
    timeout: 120_000,
  });
  await expect(page.getByTestId("studio-rail")).toBeVisible();
  await expect(
    page.locator('[data-testid^="waveform-"]').first(),
  ).toBeVisible();

  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(page.getByTestId("timeline-scrollbar")).toBeVisible();

  const at1280 = await assertNoNativeScrollbars(page);
  expect(at1280.viewport).toEqual({ width: 1280, height: 800 });
  expect(at1280.rail).not.toBeNull();
  expect(at1280.stage).not.toBeNull();
  expect(at1280.rail!.width).toBeGreaterThan(200);
  expect(at1280.rail!.right).toBeLessThan(at1280.stage!.left);
  expect(at1280.stage!.right).toBeGreaterThanOrEqual(at1280.main!.right - 2);
  expect(at1280.timeline!.scrollWidth).toBe(at1280.timeline!.clientWidth);
  expect(at1280.greenScrollbar).toBe(true);
  expect(at1280.transport!.right).toBeLessThanOrEqual(1280);

  await page.getByTestId("timeline-scrollbar-thumb").hover();
  const beforeGreen = await page
    .getByTestId("timeline-scrollbar")
    .getAttribute("aria-valuenow");
  const thumb = await page
    .getByTestId("timeline-scrollbar-thumb")
    .boundingBox();
  if (!thumb) throw new Error("green scrollbar thumb has no box");
  await page.mouse.move(thumb.x + thumb.width / 2, thumb.y + thumb.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    thumb.x + thumb.width / 2 + 120,
    thumb.y + thumb.height / 2,
    {
      steps: 4,
    },
  );
  await page.mouse.up();
  const afterGreen = await page
    .getByTestId("timeline-scrollbar")
    .getAttribute("aria-valuenow");
  expect(Number(afterGreen)).toBeGreaterThan(Number(beforeGreen));

  const at1920 = await (async () => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(250);
    return assertNoNativeScrollbars(page);
  })();
  expect(at1920.viewport).toEqual({ width: 1920, height: 1080 });
  expect(at1920.rail!.width).toBeGreaterThan(200);
  expect(at1920.stage!.width).toBeGreaterThan(at1280.stage!.width + 300);
  expect(at1920.stage!.right).toBeGreaterThanOrEqual(at1920.main!.right - 2);
  expect(at1920.greenThumbWidth!).toBeGreaterThan(0);
  expect(at1920.transport!.right).toBeLessThanOrEqual(1920);

  // The main area is still wheel-scrollable (the page itself never scrolls).
  await page.setViewportSize({ width: 1280, height: 640 });
  await page.waitForTimeout(200);
  const beforeWheel = await measure(page);
  await page.locator(".studio-main").hover();
  await page.mouse.wheel(0, 500);
  await page.waitForTimeout(200);
  const afterWheel = await measure(page);
  if (beforeWheel.main!.scrollHeight > beforeWheel.main!.clientHeight) {
    expect(afterWheel.mainScrollTop).toBeGreaterThan(beforeWheel.mainScrollTop);
  }
  expect(afterWheel.transport!.right).toBeLessThanOrEqual(1280);
  await assertNoNativeScrollbars(page);

  testInfo.annotations.push({
    type: "layout-measurements",
    description: JSON.stringify({
      at1280: {
        rail: at1280.rail,
        stage: at1280.stage,
        main: at1280.main,
        document: at1280.document,
        greenThumbWidth: at1280.greenThumbWidth,
      },
      at1920: {
        rail: at1920.rail,
        stage: at1920.stage,
        main: at1920.main,
        document: at1920.document,
        greenThumbWidth: at1920.greenThumbWidth,
      },
    }),
  });
});
