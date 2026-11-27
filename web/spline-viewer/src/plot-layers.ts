import { select } from "d3-selection";
import type { FitDocument, Point } from "./document";

export type StageName = "initial" | "preFairing" | "final";
export type LayerState = Record<
  "domain" | "clearance" | "data" | "preprocessing" | "curve" | "stroke" | "controls" | "handles",
  boolean
>;
export type Pick = { kind: "source" | "cluster" | "sample" | "control" | "handle"; index: number };

const NS = "http://www.w3.org/2000/svg";
type Attributes = Record<string, string | number>;

export function element<K extends keyof SVGElementTagNameMap>(
  parent: SVGElement, tag: K, attributes: Attributes = {},
): SVGElementTagNameMap[K] {
  const child = document.createElementNS(NS, tag);
  for (const [name, value] of Object.entries(attributes)) child.setAttribute(name, String(value));
  parent.append(child);
  return child;
}

function line(points: Point[]): string {
  return points.length ? "M" + points.join("L") : "";
}

function path(parent: SVGElement, d: string, attrs: Attributes) {
  return element(parent, "path", { d, fill: "none", "vector-effect": "non-scaling-stroke", ...attrs });
}

function visible(node: SVGElement, show: boolean) {
  node.setAttribute("display", show ? "inline" : "none");
}

const palette = {
  domain: "#89947d", fit: "#107153", source: "#bc592d", cluster: "#7d5e9e",
  sample: "#8a73a5", control: "#567989", handle: "#47907a",
};

const glyphs = {
  source: { d: "M-4.3,0a4.3,4.3 0 1,0 8.6,0a4.3,4.3 0 1,0 -8.6,0", fill: "#fff9ee" },
  cluster: { d: "M0,-3.7L3.7,0 0,3.7 -3.7,0Z", fill: "none" },
  sample: { d: "M-1.45,0a1.45,1.45 0 1,0 2.9,0a1.45,1.45 0 1,0 -2.9,0", fill: palette.sample },
  control: { d: "M-2.8,-2.8h5.6v5.6h-5.6Z", fill: "#f6f9f7" },
  handle: { d: "M-2.25,0a2.25,2.25 0 1,0 4.5,0a2.25,2.25 0 1,0 -4.5,0", fill: "#fbfcf7" },
};

let plotSequence = 0;

export class PlotLayers {
  private readonly prefix = "spline-plot-" + ++plotSequence;
  private readonly symbols: SVGGElement[] = [];
  private readonly clip: SVGPathElement;
  private readonly hatch: SVGPatternElement;
  private readonly domainGroup: SVGGElement;
  private readonly clearanceGroup: SVGGElement;
  private readonly data: SVGGElement;
  private readonly prep: SVGGElement;
  private readonly curve: SVGGElement;
  private readonly stroke: SVGGElement;
  private readonly controls: SVGGElement;
  private readonly handles: SVGGElement;
  private endpointLabels: SVGTextElement[] = [];
  private projection = { ox: 0, oy: 0, unit: 1, dx: 1, dy: 1 };
  private activeStage?: FitDocument["fit"]["stages"][StageName];

  constructor(private world: SVGGElement, defs: SVGDefsElement, private onPick: (pick: Pick) => void) {
    for (const kind of Object.keys(glyphs) as Pick["kind"][]) {
      const glyph = glyphs[kind];
      const group = element(defs, "g", { id: this.prefix + "-" + kind });
      this.symbols.push(group);
      element(group, "circle", { r: 5, fill: "transparent" });
      element(group, "circle", { r: 7.3, fill: "none", stroke: "var(--pick-ring, transparent)", "stroke-width": 1.8 });
      element(group, "path", { d: glyph.d, fill: glyph.fill, stroke: palette[kind], "stroke-width": kind === "sample" ? 0.7 : 1.35 });
    }
    const anchor = element(defs, "g", { id: this.prefix + "-anchor" });
    this.symbols.push(anchor);
    element(anchor, "path", { d: "M0,-3L3,0 0,3 -3,0Z", fill: "#ecf6ee", stroke: palette.fit, "stroke-width": 1.1 });
    this.hatch = element(defs, "pattern", { id: this.prefix + "-hatch", patternUnits: "userSpaceOnUse", width: 8, height: 8 });
    element(this.hatch, "rect", { width: 8, height: 8, fill: "#e7e7df" });
    element(this.hatch, "path", { d: "M-2,2L2,-2M0,8L8,0M6,10L10,6", fill: "none", stroke: "#bbc0b1", "stroke-width": 0.8 });
    const clipPath = element(defs, "clipPath", { id: this.prefix + "-clip", clipPathUnits: "userSpaceOnUse" });
    this.clip = element(clipPath, "path", { "clip-rule": "evenodd" });

    this.domainGroup = element(world, "g", { "data-layer": "domain" });
    this.clearanceGroup = element(this.domainGroup, "g", { "data-sublayer": "clearance" });
    this.curve = element(world, "g", { "data-layer": "curve" });
    this.controls = element(this.curve, "g", { "data-sublayer": "controls" });
    this.stroke = element(this.curve, "g", { "data-sublayer": "stroke", "pointer-events": "none" });
    this.handles = element(this.curve, "g", { "data-sublayer": "handles" });
    this.data = element(world, "g", { "data-layer": "data" });
    this.prep = element(world, "g", { "data-layer": "preprocessing" });
  }

  private marks(group: SVGGElement, kind: Pick["kind"], points: Point[]) {
    select(group).selectAll<SVGUseElement, Point>('use[data-kind="' + kind + '"]')
      .data(points, (_, i) => i)
      .join("use")
      .attr("href", "#" + this.prefix + "-" + kind)
      .attr("transform", p => "translate(" + p + ")")
      .attr("data-kind", kind)
      .attr("data-index", (_, i) => i)
      .attr("cursor", "pointer")
      .on("click", (event: MouseEvent) => {
        const node = event.currentTarget as SVGUseElement;
        this.onPick({ kind, index: Number(node.dataset.index) });
      });
  }

  private local = ([x, y]: Point): Point => [
    (x - this.projection.ox) / this.projection.unit,
    (y - this.projection.oy) / this.projection.unit,
  ];

  setDocument(doc: FitDocument, projection: PlotLayers["projection"]) {
    this.projection = projection;
    this.domainGroup.replaceChildren();
    this.clearanceGroup.replaceChildren();
    if (doc.domain) {
      const outer = doc.domain.outer.map(this.local);
      const holes = doc.domain.holes.map(ring => ring.map(this.local));
      const clearance = doc.domain.clearance;
      const rings = [outer, ...holes].map(ring => line(ring) + "Z").join("");
      this.clip.setAttribute("d", rings);
      path(this.domainGroup, rings, { "data-part": "domain-fill", fill: "#d9e4d5", "fill-opacity": 0.43, "fill-rule": "evenodd" });
      for (const ring of holes) path(this.domainGroup, line(ring) + "Z", { fill: "url(#" + this.prefix + "-hatch)" });
      if (clearance !== null) {
        element(this.clearanceGroup, "path", { d: rings, fill: "none", stroke: "#bba96c", "stroke-opacity": 0.32,
          "stroke-width": 2 * Math.min(clearance / projection.unit, 2 * Math.max(projection.dx, projection.dy)), "stroke-linejoin": "round", "clip-path": "url(#" + this.prefix + "-clip)" });
      }
      this.domainGroup.append(this.clearanceGroup);
      path(this.domainGroup, rings, { stroke: palette.domain, "stroke-width": 1.25, "data-part": "boundary" });
    } else {
      this.clip.removeAttribute("d");
      this.domainGroup.append(this.clearanceGroup);
    }
    this.data.replaceChildren();
    const source = doc.observations.map(observation => this.local(observation.xy));
    path(this.data, line(source), { stroke: palette.source, "stroke-width": 1.25, "stroke-dasharray": "4 4", "stroke-opacity": 0.75, "pointer-events": "none" });
    this.marks(this.data, "source", source);
    this.endpointLabels = [];
    const last = source.length - 1;
    const together = source[0][0] === source[last][0] && source[0][1] === source[last][1];
    const ends = together ? [0] : [0, last];
    for (const index of ends) {
      const position = element(this.data, "g", { transform: "translate(" + source[index] + ")", "pointer-events": "none" });
      const label = element(position, "text", { x: index === 0 ? -7 : 7, y: index === 0 ? 13 : -7,
        "text-anchor": index === 0 ? "end" : "start", "font-family": "'IBM Plex Mono',monospace", "font-size": 10,
        fill: "#944b29", stroke: "#fbfcf6", "stroke-width": 2.5, "paint-order": "stroke", "stroke-linejoin": "round" });
      label.textContent = together && last > 0 ? "P0 / P" + last : "P" + index;
      this.endpointLabels.push(label);
    }
    this.prep.replaceChildren();
    const { membership } = doc.preprocessing;
    const representatives = doc.preprocessing.representatives.map(this.local);
    const points = doc.preprocessing.points.map(this.local);
    let links = "";
    source.forEach((p, i) => {
      const target = representatives[membership[i]];
      if (p[0] !== target[0] || p[1] !== target[1]) links += "M" + p + "L" + target;
    });
    path(this.prep, links, { stroke: palette.cluster, "stroke-width": 1, "pointer-events": "none" });
    this.marks(this.prep, "sample", points);
    this.marks(this.prep, "cluster", representatives);
    this.activeStage = undefined;
    this.controls.replaceChildren();
    this.handles.replaceChildren();
    this.stroke.replaceChildren();
  }

  private renderStage(stage: FitDocument["fit"]["stages"][StageName]) {
    if (this.activeStage === stage) return;
    this.activeStage = stage;
    this.controls.replaceChildren();
    this.handles.replaceChildren();
    this.stroke.replaceChildren();
    if (!stage) return;
    const controls = stage.controls.map(this.local);
    path(this.controls, line(controls), { stroke: palette.control, "stroke-opacity": 0.8, "stroke-width": 1, "stroke-dasharray": "5 4" });
    this.marks(this.controls, "control", controls);
    const handles: Point[] = [];
    let links = "", curve = "";
    for (const [i, span] of stage.spans.entries()) {
      const [p0, h0, h1, p1] = span.points.map(this.local);
      if (i === 0) curve = "M" + p0;
      curve += "C" + h0 + " " + h1 + " " + p1;
      links += "M" + p0 + "L" + h0 + "M" + p1 + "L" + h1;
      handles.push(h0, h1);
    }
    path(this.handles, links, { stroke: palette.handle, "stroke-width": 1.2 });
    const anchors = [stage.spans[0].points[0], ...stage.spans.map(span => span.points[3])];
    for (const point of anchors) element(this.handles, "use", { href: "#" + this.prefix + "-anchor",
      transform: "translate(" + this.local(point) + ")", "data-part": "span-anchor", "pointer-events": "none" });
    this.marks(this.handles, "handle", handles);
    path(this.stroke, curve, { "data-part": "fit-path", stroke: palette.fit, "stroke-width": 3.1, "stroke-linecap": "round", "stroke-linejoin": "round" });
  }

  update(doc: FitDocument, layers: LayerState, stage: StageName, pick: Pick | null) {
    this.renderStage(doc.fit.stages[stage]);
    visible(this.domainGroup, !!doc.domain && layers.domain);
    visible(this.clearanceGroup, layers.clearance);
    visible(this.data, layers.data);
    visible(this.prep, layers.preprocessing);
    visible(this.curve, layers.curve && !!doc.fit.stages[stage]);
    visible(this.stroke, layers.stroke);
    visible(this.controls, layers.controls);
    visible(this.handles, layers.handles);
    for (const mark of this.world.querySelectorAll<SVGUseElement>("use[data-kind]")) {
      const { kind, index } = mark.dataset;
      const selected = pick !== null && pick.kind === kind && pick.index === Number(index);
      const member = layers.preprocessing && pick?.kind === "cluster" && kind === "source"
        && doc.preprocessing.membership[Number(index)] === pick.index;
      mark.dataset.highlighted = String(selected || member);
      mark.style.setProperty("--pick-ring", selected ? "#203e34" : member ? palette.cluster : "transparent");
    }
  }

  rescale(scale: number) {
    const transform = "scale(" + (1 / scale) + ")";
    for (const label of this.endpointLabels) label.setAttribute("transform", "scale(" + (1 / scale) + " " + (-1 / scale) + ")");
    for (const symbol of this.symbols) symbol.setAttribute("transform", transform);
    this.hatch.setAttribute("patternTransform", transform);
  }
}
