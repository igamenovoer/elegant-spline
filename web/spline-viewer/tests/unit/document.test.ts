import { describe, expect, test } from "bun:test";
import exportedExample from "../../example.json";
import { parseDocument, type FitDocument, type Stage } from "../../src/document";

function example(): FitDocument {
  const curve: Stage = {
    controls: [[0, 0], [1, 1], [2, 1], [3, 0]],
    spans: [{ a: 0, b: 1, points: [[0, 0], [1, 1], [2, 1], [3, 0]] }],
  };
  return {
    version: 1, unit: null, domain: null,
    observations: [{ xy: [0, 0], u: 0 }, { xy: [0, 0], u: 0 }, { xy: [3, 0], u: 1 }],
    preprocessing: {
      membership: [0, 0, 1], representatives: [[0, 0], [3, 0]],
      points: [[0, 0], [3, 0]], parameters: [0, 1],
    },
    fit: { method: "distance", status: "fitted", reason: null, stages: { final: curve } },
  };
}

describe("fit document v1", () => {
  test("opens the checked-in Python export with a hole, merge and cubic spans", () => {
    const fit = parseDocument(exportedExample);
    expect(fit.domain?.holes.length).toBeGreaterThan(0);
    expect(fit.preprocessing.representatives.length).toBeLessThan(fit.observations.length);
    expect(fit.fit.stages.final?.spans.length).toBeGreaterThan(1);
  });

  test("keeps ordered duplicates and their reported membership", () => {
    const fit = example();
    expect(parseDocument(JSON.parse(JSON.stringify(fit)))).toEqual(fit);
  });

  test("accepts open and explicitly closed polygon rings", () => {
    const fit = example();
    fit.domain = {
      outer: [[-5, -4], [5, -4], [-5, 5]],
      holes: [[[-3, -3], [-2, -3], [-3, -2], [-3, -3]]], clearance: 0.25,
    };
    expect(parseDocument(fit).domain).toEqual(fit.domain);
    fit.domain.outer = [[0, 0], [1, 0], [0, 0]];
    expect(() => parseDocument(fit)).toThrow("domain.outer");
  });

  test("names unknown version, malformed pair and nonfinite coordinate", () => {
    const fit = example();
    expect(() => parseDocument({ ...fit, version: 4 })).toThrow("version");
    expect(() => parseDocument({ ...fit, observations: [{ xy: [0], u: 0 }] })).toThrow("observations.0.xy");
    fit.observations[1].xy[0] = Infinity;
    expect(() => parseDocument(fit)).toThrow("observations.1.xy.0");
  });

  test("checks the observation and solver array correspondences", () => {
    const fit = example();
    fit.preprocessing.membership[1] = 3;
    expect(() => parseDocument(fit)).toThrow("preprocessing.membership.1");
    fit.preprocessing.membership = [0];
    expect(() => parseDocument(fit)).toThrow("preprocessing.membership");
    fit.preprocessing.membership = [0, 0, 1];
    fit.preprocessing.parameters.pop();
    expect(() => parseDocument(fit)).toThrow("preprocessing.parameters");
  });

  test("checks shared span boundaries in progress and XY", () => {
    const fit = example();
    const spans = fit.fit.stages.final!.spans;
    spans[0].b = 0.5;
    spans.push({ ...spans[0], a: 0.7, b: 1 });
    expect(() => parseDocument(fit)).toThrow("fit.stages.final.spans.1.a");
    spans[1].a = 0.5;
    expect(() => parseDocument(fit)).toThrow("fit.stages.final.spans.1.points.0");
    spans[1].points = [[3, 0], [4, -1], [5, -1], [6, 0]];
    expect(parseDocument(fit).fit.stages.final!.spans).toEqual(spans);
  });

  test("distinguishes fallback, unavailable and missing geometry", () => {
    const fit = example();
    fit.fit.status = "fallback";
    fit.fit.reason = "line";
    expect(parseDocument(fit).fit.status).toBe("fallback");
    fit.fit.status = "unavailable";
    fit.fit.reason = "insufficient_source_points";
    expect(() => parseDocument(fit)).toThrow("fit.stages");
    fit.fit.stages = {};
    expect(parseDocument(fit).fit.stages).toEqual({});
    fit.fit.status = "fitted";
    expect(() => parseDocument(fit)).toThrow("fit.stages.final");
  });
});
