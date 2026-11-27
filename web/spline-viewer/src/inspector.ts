import type { FitDocument, Point } from "./document";
import type { LayerState, Pick, StageName } from "./plot";

export const pointLabels: Record<Pick["kind"], string> = {
  source: "Observation", cluster: "Cluster", sample: "Solver point", control: "Control point", handle: "Bézier handle",
};

export function availablePoints(doc: FitDocument, layers: LayerState, stage: StageName) {
  const curve = doc.fit.stages[stage];
  return {
    source: layers.data ? doc.observations.length : 0,
    cluster: layers.preprocessing ? doc.preprocessing.representatives.length : 0,
    sample: layers.preprocessing ? doc.preprocessing.points.length : 0,
    control: layers.curve && layers.controls && curve ? curve.controls.length : 0,
    handle: layers.curve && layers.handles && curve ? curve.spans.length * 2 : 0,
  };
}

export function inspect(doc: FitDocument, stage: StageName, pick: Pick): { xy: Point; detail: string } {
  const { index, kind } = pick;
  const guide = doc.preprocessing;
  switch (kind) {
    case "source": {
      const point = doc.observations[index];
      return { xy: point.xy, detail: "Source " + index + " · Cluster " + guide.membership[index] + " · u = " + point.u.toFixed(4) };
    }
    case "cluster": {
      const members = guide.membership.flatMap((cluster, i) => cluster === index ? [i] : []);
      return { xy: guide.representatives[index], detail: "Source indices " + members.join(", ") };
    }
    case "sample":
      return { xy: guide.points[index], detail: "Solver point " + index + " · u = " + guide.parameters[index].toFixed(4) };
    case "control":
      return { xy: doc.fit.stages[stage]!.controls[index], detail: "B-spline coefficient " + index };
    case "handle": {
      const spanIndex = Math.floor(index / 2);
      const span = doc.fit.stages[stage]!.spans[spanIndex];
      const outgoing = index % 2 === 0;
      return { xy: span.points[outgoing ? 1 : 2], detail: (outgoing ? "Outgoing" : "Incoming") + " · Span " + spanIndex + " · u = " + (outgoing ? span.a : span.b).toFixed(4) };
    }
  }
}

export function formatCoordinate(value: number): string {
  const absolute = Math.abs(value);
  return absolute !== 0 && (absolute < 0.0001 || absolute >= 100000) ? value.toExponential(4) : value.toFixed(4);
}
