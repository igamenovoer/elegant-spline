import { readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { parseDocument, type FitDocument, type Point, type Stage } from "../../src/document";

function straightStage(y: number): Stage {
  const at = (x: number): Point => [x, y];
  return {
    controls: [0.25, 0.5, 1.5, 2.5, 3.25].map(at),
    spans: [
      { a: 0, b: 0.25, points: [at(0.25), at(0.5), at(0.75), at(1)] },
      { a: 0.25, b: 1, points: [at(1), at(1.75), at(2.5), at(3.25)] },
    ],
  };
}

function crossingFit(): FitDocument {
  const start: Point = [0.25, 1.5];
  const mid: Point = [1.75, 1.5];
  const end: Point = [3.25, 1.5];
  return {
    version: 1, unit: "mm",
    domain: {
      outer: [[0, 0], [4.5, 0], [4.5, 3], [0, 3]],
      holes: [[[1, 1], [2, 1], [2, 2], [1, 2]]],
      clearance: 0.12,
    },
    observations: [
      { xy: start, u: 0 }, { xy: start, u: 0 }, { xy: mid, u: 0.25 },
      { xy: start, u: 0.5 }, { xy: end, u: 1 },
    ],
    preprocessing: {
      membership: [0, 0, 1, 2, 3], representatives: [start, mid, start, end],
      points: [start, [1.2, 1.5], end], parameters: [0, 0.4, 1],
    },
    fit: { method: "fixed-knot", status: "fitted", reason: null, stages: {
      initial: straightStage(1.75), preFairing: straightStage(1.65), final: straightStage(1.5),
    } },
  };
}

async function openJSON(page: Page, data: unknown, name: string) {
  await page.locator("#file-input").setInputFiles({
    name, mimeType: "application/json", buffer: Buffer.from(JSON.stringify(data)),
  });
}

async function loadFit(page: Page, fit: FitDocument, name = "crossing.json") {
  await openJSON(page, fit, name);
  await expect(page.locator("#document-file")).toContainText(name);
}

async function pick(page: Page, kind: string, index: number) {
  await page.locator("#pick-kind").selectOption(kind);
  await page.locator("#pick-index").fill(String(index));
  await page.locator("#pick-index").press("Tab");
}

async function camera(page: Page) {
  return page.locator("[data-part=world]").evaluate(el => {
    const m = (el as SVGGraphicsElement).getCTM()!;
    return [m.a, m.b, m.c, m.d, m.e, m.f];
  });
}

async function renderedPixel(page: Page, [x, y]: Point) {
  const screen = await page.locator("[data-part=world]").evaluate((node, xy) => {
    const p = new DOMPoint(...xy).matrixTransform((node as SVGGraphicsElement).getScreenCTM()!);
    return { x: Math.round(p.x + scrollX), y: Math.round(p.y + scrollY) };
  }, [x, y]);
  const screenshot = await page.screenshot({ clip: { ...screen, width: 1, height: 1 }, scale: "css" });
  return page.evaluate(async base64 => {
    const image = new Image();
    image.src = "data:image/png;base64," + base64;
    await image.decode();
    const ctx = document.createElement("canvas").getContext("2d")!;
    ctx.drawImage(image, 0, 0);
    return Array.from(ctx.getImageData(0, 0, 1, 1).data);
  }, screenshot.toString("base64"));
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("[data-part=fit-path]")).toBeVisible();
});

test("opens the Python-exported fit, toggles the layers, inspects a merge and changes stages", async ({ page }) => {
  const file = resolve(process.env.SPLINE_TEST_DOCUMENT || "example.json");
  const doc = parseDocument(JSON.parse(readFileSync(file, "utf8")));
  await page.locator("#file-input").setInputFiles(file);
  await expect(page.locator("#document-file")).toContainText(basename(file));
  await expect(page.locator("#observations-count")).toHaveText(String(doc.observations.length));
  await expect(page.locator("#span-count")).toHaveText(String(doc.fit.stages.final!.spans.length));

  await page.locator("#zoom-in").click();
  await expect(page.locator("#zoom-level")).not.toHaveText("100%");
  const beforePan = await camera(page);
  const plot = await page.locator("#plot").boundingBox();
  if (!plot) throw new Error("Plot is hidden");
  const x = plot.x + plot.width / 2;
  const y = plot.y + plot.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 25, y - 14, { steps: 4 });
  await page.mouse.up();
  const zoomed = await camera(page);
  expect(zoomed[4]).not.toBe(beforePan[4]);
  for (const key of ["domain", "data", "preprocessing", "curve"]) {
    const toggle = page.locator("#layer-" + key);
    await toggle.uncheck();
    await expect(page.locator('[data-layer="' + key + '"]')).toBeHidden();
    expect(await camera(page)).toEqual(zoomed);
    await toggle.check();
    await expect(page.locator('[data-layer="' + key + '"]')).toBeVisible();
  }

  const merged = doc.preprocessing.membership.find((c, i, all) => i > 0 && c === all[i - 1]);
  expect(merged).toBeDefined();
  await pick(page, "cluster", merged!);
  const members = doc.preprocessing.membership.flatMap((c, i) => c === merged ? [String(i)] : []);
  const selected = page.locator('[data-kind="source"][data-highlighted="true"]');
  await expect(selected).toHaveCount(members.length);
  expect(await selected.evaluateAll(nodes => nodes.map(n => n.getAttribute("data-index")))).toEqual(members);
  await page.locator("#stage").selectOption("initial");
  await expect(page.locator('[data-kind="control"]')).toHaveCount(doc.fit.stages.initial!.controls.length);
  expect(await camera(page)).toEqual(zoomed);
  await page.locator("#frame").click();
  await expect(page.locator("#zoom-level")).toHaveText("100%");
});

test("rejects invalid input and keeps the previous document and camera", async ({ page }) => {
  const current = crossingFit();
  await loadFit(page, current);
  await page.locator("#zoom-in").click();
  const zoomed = await camera(page);
  await openJSON(page, { ...current, version: 7 }, "unsupported.json");
  await expect(page.locator("#error")).toContainText(/version/i);
  current.preprocessing.membership[1] = 128;
  await openJSON(page, current, "bad-cluster.json");
  await expect(page.locator("#error")).toContainText("preprocessing.membership.1");
  await expect(page.locator("#document-file")).toContainText("crossing.json");
  await expect(page.locator('[data-kind="source"]')).toHaveCount(5);
  expect(await camera(page)).toEqual(zoomed);
});

test("uses a Y-up viewport, preserves holes, and leaves the crossing stroke visible", async ({ page }) => {
  const doc = crossingFit();
  await loadFit(page, doc);
  const [sx, , , sy] = await camera(page);
  expect(sx).toBeGreaterThan(0);
  expect(-sy).toBeCloseTo(sx);
  const domainFill = page.locator("[data-part=domain-fill]");
  const inside = await domainFill.evaluate(el => [new DOMPoint(1.5, 1.5), new DOMPoint(3.5, 2.4)]
    .map(point => (el as SVGPathElement).isPointInFill(point)));
  expect(inside).toEqual([false, true]);

  for (const key of ["controls", "handles", "data", "preprocessing"]) {
    await page.locator("#layer-" + key).uncheck();
  }
  // The actual rendered pixel inside the hole changes when the curve is hidden.
  const throughHole: Point = [1.46, 1.5];
  const withCurve = await renderedPixel(page, throughHole);
  await page.locator("#layer-stroke").uncheck();
  const withoutCurve = await renderedPixel(page, throughHole);
  expect(Math.abs(withoutCurve[0] - withCurve[0])).toBeGreaterThan(40);

  const clearance = page.locator("[data-sublayer=clearance] path");
  expect(await clearance.getAttribute("stroke-width")).toBe("0.24");
  await page.locator("#layer-clearance").uncheck();
  await expect(clearance).toBeHidden();
  await page.locator("#layer-domain").uncheck();
  await page.locator("#layer-domain").check();
  await expect(clearance).toBeHidden();
  doc.domain = null;
  await loadFit(page, doc, "unbounded.json");
  await expect(domainFill).toHaveCount(0);
  await expect(page.locator("[data-layer=domain]")).toBeHidden();
});

test("distinguishes coincident visits and removes hidden points from picking", async ({ page }) => {
  await loadFit(page, crossingFit());
  for (const index of [0, 1, 3]) {
    await pick(page, "source", index);
    await expect(page.locator('[data-kind=source][data-index="' + index + '"]')).toHaveAttribute("data-highlighted", "true");
    expect(Number.parseFloat(await page.locator("#coord-x").innerText())).toBeCloseTo(0.25);
  }
  await page.locator("#layer-data").uncheck();
  const catches = await page.locator("[data-part=world]").evaluate(node => {
    const p = new DOMPoint(0.25, 1.5).matrixTransform((node as SVGGraphicsElement).getScreenCTM()!);
    return document.elementsFromPoint(p.x, p.y).some(el => el.getAttribute("data-kind") === "source");
  });
  expect(catches).toBe(false);
});

test("inspects native controls and handles of unequal spans across recorded stages", async ({ page }) => {
  const doc = crossingFit();
  await loadFit(page, doc);
  await page.locator("#zoom-in").click();
  const zoomed = await camera(page);
  await pick(page, "control", 2);
  expect(Number.parseFloat(await page.locator("#coord-x").innerText())).toBeCloseTo(1.5);
  await pick(page, "handle", 1);
  expect(Number.parseFloat(await page.locator("#coord-x").innerText())).toBeCloseTo(0.75);
  await pick(page, "handle", 2);
  expect(Number.parseFloat(await page.locator("#coord-x").innerText())).toBeCloseTo(1.75);
  await page.locator("#layer-controls").uncheck();
  await expect(page.locator("[data-sublayer=controls]")).toBeHidden();
  await expect(page.locator("[data-sublayer=handles]")).toBeVisible();
  await page.locator("#layer-curve").uncheck();
  await page.locator("#layer-curve").check();
  await expect(page.locator("[data-sublayer=controls]")).toBeHidden();
  const stroke = page.locator("[data-part=fit-path]");
  const finalPath = await stroke.getAttribute("d");
  await page.locator("#stage").selectOption("initial");
  await expect(stroke).not.toHaveAttribute("d", finalPath!);
  await pick(page, "handle", 2);
  expect(Number.parseFloat(await page.locator("#coord-y").innerText())).toBeCloseTo(1.75);
  expect(await camera(page)).toEqual(zoomed);
});

test("frames a constant fallback and clears its geometry on an unavailable fit", async ({ page }) => {
  const doc = crossingFit();
  const p: Point = [2.54, -5.61];
  const stage: Stage = { controls: [p, p, p, p], spans: [{ a: 0, b: 1, points: [p, p, p, p] }] };
  doc.domain = null;
  doc.observations = [{ xy: p, u: 0 }];
  doc.preprocessing = { membership: [0], representatives: [p], points: [p], parameters: [0] };
  doc.fit = { method: "distance", status: "fallback", reason: "constant", stages: { final: stage } };
  await loadFit(page, doc, "constant.json");
  await expect(page.locator("#fit-status")).toHaveText(/fallback/i);
  await page.locator("#frame").click();
  expect((await camera(page)).every(Number.isFinite)).toBe(true);
  await pick(page, "control", 3);
  expect(Number.parseFloat(await page.locator("#coord-y").innerText())).toBeCloseTo(-5.61);
  doc.fit = { method: "distance", status: "unavailable", reason: "Insufficient observations", stages: {} };
  await loadFit(page, doc, "unavailable.json");
  await expect(page.locator("#reason")).toContainText(doc.fit.reason!);
  await expect(page.locator("[data-kind=control], [data-kind=handle], [data-part=fit-path]")).toHaveCount(0);
  await expect(page.locator("[data-kind=source]")).toHaveCount(1);
});
