import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomTransform } from "d3-zoom";
import type { FitDocument, Point } from "./document";
import { element, PlotLayers, type LayerState, type Pick, type StageName } from "./plot-layers";

export type { LayerState, Pick, StageName } from "./plot-layers";

function geometryBounds(doc: FitDocument) {
  let lowX = Infinity, highX = -Infinity, lowY = Infinity, highY = -Infinity;
  function include([x, y]: Point) {
    lowX = Math.min(x, lowX);
    highX = Math.max(x, highX);
    lowY = Math.min(y, lowY);
    highY = Math.max(y, highY);
  }
  doc.observations.forEach(({ xy }) => include(xy));
  doc.domain?.outer.forEach(include);
  doc.domain?.holes.forEach(ring => ring.forEach(include));
  doc.preprocessing.representatives.forEach(include);
  doc.preprocessing.points.forEach(include);
  for (const stage of Object.values(doc.fit.stages)) {
    stage?.controls.forEach(include);
    stage?.spans.forEach(span => span.points.forEach(include));
  }
  const cx = lowX / 2 + highX / 2, cy = lowY / 2 + highY / 2;
  const radius = Math.max(highX - cx, highY - cy, cx - lowX, cy - lowY);
  // SVG implementations store coordinates at single precision. For small details
  // on a large offset, or magnitudes outside that range, draw in local coordinates.
  const unit = radius && (radius > 1e8 || radius < 1e-8) ? radius : 1;
  const shifted = unit !== 1 || Math.max(Math.abs(cx), Math.abs(cy)) > Math.max(radius, 1) * 8192;
  const ox = shifted ? cx : 0, oy = shifted ? cy : 0;
  return { ox, oy, unit, cx: (cx - ox) / unit, cy: (cy - oy) / unit,
    dx: (highX - ox) / unit - (lowX - ox) / unit, dy: (highY - oy) / unit - (lowY - oy) / unit };
}

function tickSpacing(target: number) {
  const magnitude = 10 ** Math.floor(Math.log10(target));
  const fraction = target / magnitude;
  const multiple = fraction < 1.5 ? 1 : fraction < 3.5 ? 2 : fraction < 7.5 ? 5 : 10;
  return multiple * magnitude;
}

function ticks(min: number, max: number, step: number) {
  const first = Math.ceil(min / step);
  const count = Math.min(2048, Math.floor(max / step) - first + 1);
  return Array.from({ length: count }, (_, i) => (first + i) * step);
}

function formatTick(value: number, step: number) {
  const precision = Math.max(0, -Math.floor(Math.log10(step)));
  if (precision > 6 || Math.abs(value) >= 1e7) return value.toExponential(1);
  return value.toFixed(precision);
}

let viewId = 0;

export class SplinePlot {
  private readonly grid: SVGGElement;
  private readonly world: SVGGElement;
  private readonly frameClip: SVGRectElement;
  private readonly geometry: PlotLayers;
  private readonly navigation = zoom<SVGSVGElement, unknown>().scaleExtent([0.05, 128]);
  private readonly resizeObserver: ResizeObserver;
  private viewport = { width: 1, height: 1 };
  private bounds = { ox: 0, oy: 0, unit: 1, cx: 0, cy: 0, dx: 1, dy: 1 };
  private camera = zoomIdentity;
  private doc: FitDocument | null = null;
  private layers: LayerState = { domain: true, clearance: true, data: true, preprocessing: true, curve: true, stroke: true, controls: true, handles: true };
  private stage: StageName = "final";
  private pick: Pick | null = null;

  constructor(
    private svg: SVGSVGElement, onPick: (pick: Pick) => void,
    onZoom: (scaleRelativeToFrame: number) => void,
  ) {
    const defs = element(svg, "defs");
    const clipId = "plot-viewport-" + ++viewId;
    const clip = element(defs, "clipPath", { id: clipId });
    this.frameClip = element(clip, "rect");
    this.grid = element(svg, "g", { "data-part": "axes", "pointer-events": "none" });
    const clipped = element(svg, "g", { "clip-path": "url(#" + clipId + ")" });
    this.world = element(clipped, "g", { "data-part": "world" });
    this.geometry = new PlotLayers(this.world, defs, onPick);
    this.navigation.extent(() => [[0, 0], [this.viewport.width, this.viewport.height]] as [[number, number], [number, number]])
      .clickDistance(4)
      .on("zoom", (event: { transform: ZoomTransform }) => {
        this.camera = event.transform;
        this.drawCamera();
        onZoom(this.camera.k);
      });
    select(svg).call(this.navigation);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(svg);
    this.resize();
  }

  private resize() {
    const width = Math.max(1, this.svg.clientWidth);
    const height = Math.max(1, this.svg.clientHeight);
    if (width === this.viewport.width && height === this.viewport.height) return;
    const old = this.frameBox();
    const shiftX = (old.cx - this.camera.applyX(old.cx)) / old.scale;
    const shiftY = (old.cy - this.camera.applyY(old.cy)) / old.scale;
    this.viewport = { width, height };
    this.svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    const box = this.frameBox();
    this.frameClip.setAttribute("x", String(box.left));
    this.frameClip.setAttribute("y", String(box.top));
    this.frameClip.setAttribute("width", String(box.width));
    this.frameClip.setAttribute("height", String(box.height));
    const k = this.camera.k;
    const next = zoomIdentity.translate((1 - k) * box.cx - shiftX * box.scale, (1 - k) * box.cy - shiftY * box.scale).scale(k);
    select(this.svg).call(this.navigation.transform, next);
  }

  private frameBox() {
    const left = 35, top = 13;
    const width = Math.max(1, this.viewport.width - left - 18);
    const height = Math.max(1, this.viewport.height - top - 27);
    const { dx, dy } = this.bounds;
    const scaleX = dx > 0 ? width / dx : Infinity;
    const scaleY = dy > 0 ? height / dy : Infinity;
    let scale = 0.85 * Math.min(scaleX, scaleY);
    if (!Number.isFinite(scale) || scale === 0) scale = Math.min(width, height) / 2;
    return { left, top, width, height, cx: left + width / 2, cy: top + height / 2, scale };
  }

  setDocument(doc: FitDocument) {
    this.doc = doc;
    this.pick = null;
    this.bounds = geometryBounds(doc);
    this.geometry.setDocument(doc, this.bounds);
    this.geometry.update(doc, this.layers, this.stage, this.pick);
    this.frame();
  }

  update(layers: LayerState, stage: StageName, pick: Pick | null) {
    this.layers = layers;
    this.stage = stage;
    this.pick = pick;
    if (this.doc) this.geometry.update(this.doc, layers, stage, pick);
  }

  frame() {
    select(this.svg).call(this.navigation.transform, zoomIdentity);
  }

  zoomBy(factor: number) {
    const { cx, cy } = this.frameBox();
    select(this.svg).call(this.navigation.scaleBy, factor, [cx, cy]);
  }

  private drawCamera() {
    const box = this.frameBox();
    const scale = box.scale * this.camera.k;
    const x0 = this.camera.applyX(box.cx) - scale * this.bounds.cx;
    const y0 = this.camera.applyY(box.cy) + scale * this.bounds.cy;
    this.world.setAttribute("transform", "matrix(" + [scale, 0, 0, -scale, x0, y0].join(" ") + ")");
    this.geometry.rescale(scale);
    this.drawGrid(box, scale, x0, y0);
  }

  private drawGrid(box: ReturnType<SplinePlot["frameBox"]>, scale: number, x0: number, y0: number) {
    const { left, top } = box;
    const right = left + box.width, bottom = top + box.height;
    const step = tickSpacing(68 / scale);
    const xMin = (left - x0) / scale, xMax = (right - x0) / scale;
    const yMin = (y0 - bottom) / scale, yMax = (y0 - top) / scale;
    this.grid.replaceChildren();
    this.grid.setAttribute("font-family", "'IBM Plex Mono', monospace");
    this.grid.setAttribute("font-size", "10");
    this.grid.setAttribute("fill", "#60746a");
    for (const minor of [true, false]) {
      const interval = minor ? step / 4 : step;
      let lines = "";
      for (const x of ticks(xMin, xMax, interval)) {
        const sx = x0 + x * scale;
        lines += "M" + sx + "," + top + "V" + bottom;
        if (!minor && sx < right - Math.max(48, 26 + 7 * (this.doc?.unit?.length ?? 0)) && sx >= left + 4) {
          element(this.grid, "text", { x: sx, y: bottom + 15, "text-anchor": "middle" }).textContent = formatTick(x, step);
        }
      }
      for (const y of ticks(yMin, yMax, interval)) {
        const sy = y0 - y * scale;
        lines += "M" + left + "," + sy + "H" + right;
        if (!minor && sy > top + 15 && sy <= bottom - 3) {
          element(this.grid, "text", { x: left - 8, y: sy + 3, "text-anchor": "end" }).textContent = formatTick(y, step);
        }
      }
      element(this.grid, "path", { d: lines, fill: "none", stroke: minor ? "#e8ece5" : "#d6ddd3", "stroke-width": minor ? 0.6 : 0.85 });
    }
    element(this.grid, "path", { d: "M" + left + "," + top + "V" + bottom + "H" + right, fill: "none", stroke: "#aab6aa" });
    const { ox, oy, unit: worldUnit } = this.bounds;
    const localGrid = ox !== 0 || oy !== 0 || worldUnit !== 1;
    const unit = localGrid ? null : this.doc?.unit;
    if (localGrid) {
      const label = "XY = grid × " + worldUnit.toPrecision(4) + " + (" + ox.toPrecision(5) + ", " + oy.toPrecision(5) + ")";
      element(this.grid, "text", { x: right, y: top - 3, "text-anchor": "end" }).textContent = label;
    }
    element(this.grid, "text", { x: right, y: bottom + 15, "text-anchor": "end", "font-weight": 600 }).textContent = unit ? "X (" + unit + ")" : "X";
    element(this.grid, "text", { x: left - 4, y: top + 6, "text-anchor": "end", "font-weight": 600 }).textContent = unit ? "Y (" + unit + ")" : "Y";
  }
}
