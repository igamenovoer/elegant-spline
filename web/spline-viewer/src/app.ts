import bundledExample from "../example.json";
import { parseDocument } from "./document";
import type { FitDocument } from "./document";
import { availablePoints, formatCoordinate, inspect, pointLabels } from "./inspector";
import { SplinePlot, type LayerState, type Pick, type StageName } from "./plot";

function byId<T extends Element = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error("Missing viewer element " + id);
  return node as unknown as T;
}

const stageLabels: Record<StageName, string> = { final: "Final curve", preFairing: "Before fairing", initial: "Initial fit" };
const methodLabels: Record<string, string> = { "fixed-knot": "Fixed-knot fit", distance: "Distance fit", smoothing: "Smoothing fit" };
const layerGroups = [
  { key: "domain", label: "Domain", symbol: "domain-key", color: "#54746a", children: [["clearance", "Clearance band"]] },
  { key: "data", label: "Data points", symbol: "data-key", color: "#bc592d", children: [] },
  { key: "preprocessing", label: "Preprocessing", symbol: "prep-key", color: "#7d5e9e", children: [] },
  { key: "curve", label: "Fitted curve", symbol: "curve-key", color: "#107153",
    children: [["stroke", "Curve stroke"], ["controls", "Control polygon"], ["handles", "Bézier handles"]] },
] as const;
const layers: LayerState = { domain: true, clearance: true, data: true, preprocessing: true, curve: true, stroke: true, controls: true, handles: true };

let doc: FitDocument;
let stage: StageName = "final";
let pick: Pick | null = null;
let loadNumber = 0;
const selectStage = byId<HTMLSelectElement>("stage");
const selectKind = byId<HTMLSelectElement>("pick-kind");
const selectIndex = byId<HTMLInputElement>("pick-index");
const fileInput = byId<HTMLInputElement>("file-input");

function updateInspector() {
  const sizes = availablePoints(doc, layers, stage);
  if (pick && !(pick.index >= 0 && pick.index < sizes[pick.kind])) pick = null;
  selectKind.replaceChildren(new Option("Select a point", ""));
  for (const kind of Object.keys(sizes) as Pick["kind"][]) {
    if (sizes[kind]) selectKind.add(new Option(pointLabels[kind], kind));
  }
  selectKind.value = pick?.kind ?? "";
  selectKind.disabled = selectKind.options.length === 1;
  selectIndex.disabled = !pick;
  selectIndex.value = pick ? String(pick.index) : "";
  selectIndex.max = pick ? String(sizes[pick.kind] - 1) : "";
  byId("index-limit").textContent = pick ? "/ " + selectIndex.max : "";
  const selected = pick ? inspect(doc, stage, pick) : null;
  byId("coord-x").textContent = selected ? formatCoordinate(selected.xy[0]) : "—";
  byId("coord-y").textContent = selected ? formatCoordinate(selected.xy[1]) : "—";
  byId("pick-detail").textContent = selected?.detail ?? "Select a visible point to inspect.";
}

function updateView() {
  for (const group of layerGroups) {
    const available = group.key === "domain" ? !!doc.domain : group.key === "curve" ? !!doc.fit.stages[stage] : true;
    const main = byId<HTMLInputElement>("layer-" + group.key);
    main.disabled = !available;
    main.checked = available && layers[group.key];
    byId("availability-" + group.key).hidden = available;
    for (const [key] of group.children) {
      const box = byId<HTMLInputElement>("layer-" + key);
      const present = available && (key !== "clearance" || doc.domain?.clearance != null);
      box.disabled = !present || !main.checked;
      box.checked = present && layers[key];
    }
  }
  byId("span-count").textContent = String(doc.fit.stages[stage]?.spans.length ?? 0);
  updateInspector();
  plot.update(layers, stage, pick);
}

const plot = new SplinePlot(byId<SVGSVGElement>("plot"), (selected) => {
  pick = selected;
  updateView();
}, (zoom) => { byId("zoom-level").textContent = Math.round(zoom * 100) + "%"; });

function layerLabel(key: keyof LayerState, label: string, symbol?: string, color?: string) {
  const el = document.createElement("label");
  el.className = symbol ? "layer-main" : "layer-detail";
  if (symbol) el.innerHTML = '<svg class="layer-key" aria-hidden="true" style="color:' + color + '"><use href="#' + symbol + '"/></svg>';
  const caption = document.createElement("span");
  caption.className = "label-text";
  caption.textContent = label;
  const input = document.createElement("input");
  input.type = "checkbox";
  input.id = "layer-" + key;
  input.addEventListener("change", () => { layers[key] = input.checked; updateView(); });
  el.append(caption);
  if (symbol) {
    const status = document.createElement("small");
    status.id = "availability-" + key;
    status.textContent = "Unavailable";
    status.hidden = true;
    el.append(status);
  }
  el.append(input);
  return el;
}
for (const group of layerGroups) {
  const row = document.createElement("div");
  row.className = "layer-block";
  row.append(layerLabel(group.key, group.label, group.symbol, group.color));
  for (const [key, label] of group.children) row.append(layerLabel(key, label));
  byId("layer-list").append(row);
}

function displayDocument(next: FitDocument, file: string, example = false) {
  doc = next;
  stage = "final";
  selectStage.replaceChildren();
  for (const name of Object.keys(stageLabels) as StageName[]) {
    if (doc.fit.stages[name]) selectStage.add(new Option(stageLabels[name], name));
  }
  if (!selectStage.length) selectStage.add(new Option("Unavailable", "final"));
  selectStage.value = stage;
  selectStage.disabled = selectStage.length < 2;
  const name = example ? "Island bend" : file.replace(/\.json$/i, "").replace(/[_-]+/g, " ") || file;
  byId("document-title").textContent = name;
  byId("document-file").textContent = file;
  byId("fit-method").textContent = methodLabels[doc.fit.method] ?? doc.fit.method;
  const status = byId("fit-status");
  status.dataset.status = doc.fit.status;
  status.textContent = doc.fit.status[0].toUpperCase() + doc.fit.status.slice(1);
  document.title = name + " · Elegant Spline";
  byId("load-example").hidden = example;
  byId("error").hidden = true;
  byId("reason").hidden = !doc.fit.reason;
  byId("reason").textContent = doc.fit.reason;
  byId("observations-count").textContent = String(doc.observations.length);
  byId("cluster-count").textContent = String(doc.preprocessing.representatives.length);
  byId("sample-count").textContent = String(doc.preprocessing.points.length);
  const merged = doc.preprocessing.membership.find((id, i, ids) => i > 0 && id === ids[i - 1]);
  pick = merged !== undefined ? { kind: "cluster", index: merged } : { kind: "source", index: 0 };
  plot.setDocument(doc);
  updateView();
}

byId("open-file").addEventListener("click", () => fileInput.click());
byId("load-example").addEventListener("click", () => {
  loadNumber++;
  displayDocument(parseDocument(bundledExample), "example.json", true);
});
fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  if (!file) return;
  fileInput.value = "";
  const request = ++loadNumber;
  try {
    const parsed = parseDocument(JSON.parse(await file.text()));
    if (request === loadNumber) displayDocument(parsed, file.name);
  } catch (error) {
    if (request !== loadNumber) return;
    const alert = byId("error");
    alert.textContent = file.name + " — " + (error instanceof Error ? error.message : "Unable to read document.");
    alert.hidden = false;
  }
});
selectStage.addEventListener("change", () => {
  stage = selectStage.value as StageName;
  if (pick?.kind === "control" || pick?.kind === "handle") pick = null;
  updateView();
});
selectKind.addEventListener("change", () => {
  pick = selectKind.value ? { kind: selectKind.value as Pick["kind"], index: 0 } : null;
  updateView();
});
selectIndex.addEventListener("change", () => {
  const index = selectIndex.valueAsNumber;
  if (pick && Number.isInteger(index) && index >= 0 && index <= Number(selectIndex.max)) pick = { ...pick, index };
  updateView();
});
byId("zoom-out").addEventListener("click", () => plot.zoomBy(1 / 1.4));
byId("zoom-in").addEventListener("click", () => plot.zoomBy(1.4));
byId("frame").addEventListener("click", () => plot.frame());

displayDocument(parseDocument(bundledExample), "example.json", true);
