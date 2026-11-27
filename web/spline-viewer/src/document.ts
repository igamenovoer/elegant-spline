import { z } from "zod";

const point = z.tuple([z.number(), z.number()]);
const ring = z.array(point).min(3).refine(
  (points) => new Set(points.map(([x, y]) => x + "," + y)).size >= 3,
  "A ring needs at least three distinct vertices.",
);
const progress = z.number().min(0).max(1);

const span = z.object({
  a: progress,
  b: progress,
  points: z.tuple([point, point, point, point]),
}).refine((value) => value.a < value.b, {
  path: ["b"],
  message: "A cubic span must end after its start.",
});

const stage = z.object({
  controls: z.array(point).min(4),
  spans: z.array(span).min(1),
}).superRefine(({ spans }, ctx) => {
  let expectedStart = 0;
  for (const [i, entry] of spans.entries()) {
    if (entry.a !== expectedStart) {
      ctx.addIssue({ code: "custom", path: ["spans", i, "a"], message: "Expected contiguous spans starting at zero." });
      return;
    }
    if (i > 0) {
      const previousEnd = spans[i - 1].points[3];
      const start = entry.points[0];
      if (previousEnd[0] !== start[0] || previousEnd[1] !== start[1]) {
        ctx.addIssue({
          code: "custom", path: ["spans", i, "points", 0],
          message: "The start anchor must match the preceding span’s end anchor.",
        });
        return;
      }
    }
    expectedStart = entry.b;
  }
  if (expectedStart !== 1) {
    ctx.addIssue({ code: "custom", path: ["spans"], message: "The last span must end at one." });
  }
});

const fitDocument = z.object({
  version: z.literal(1),
  unit: z.string().nullable(),
  domain: z.object({
    outer: ring,
    holes: z.array(ring),
    clearance: z.number().nonnegative().nullable(),
  }).nullable(),
  observations: z.array(z.object({ xy: point, u: progress })).min(1),
  preprocessing: z.object({
    membership: z.array(z.int().nonnegative()),
    representatives: z.array(point).min(1),
    points: z.array(point).min(1),
    parameters: z.array(progress).min(1),
  }),
  fit: z.object({
    method: z.string().min(1),
    status: z.enum(["fitted", "fallback", "unavailable"]),
    reason: z.string().nullable(),
    stages: z.strictObject({
      initial: stage.optional(),
      preFairing: stage.optional(),
      final: stage.optional(),
    }),
  }),
}).superRefine(({ observations, preprocessing, fit }, ctx) => {
  const issue = (path: (string | number)[], message: string) =>
    ctx.addIssue({ code: "custom", path, message });

  if (preprocessing.membership.length !== observations.length) {
    issue(["preprocessing", "membership"], "Expected one cluster index per observation.");
  }
  for (const [i, cluster] of preprocessing.membership.entries()) {
    if (cluster >= preprocessing.representatives.length) {
      issue(["preprocessing", "membership", i], "Cluster index has no corresponding representative.");
      break;
    }
  }
  if (preprocessing.parameters.length !== preprocessing.points.length) {
    issue(["preprocessing", "parameters"], "Expected one parameter per resampled solver point.");
  }
  const outOfOrderObservation = observations.findIndex((p, i) => i > 0 && p.u < observations[i - 1].u);
  if (outOfOrderObservation >= 0) {
    issue(["observations", outOfOrderObservation, "u"], "Source parameters must be nondecreasing.");
  }
  const outOfOrderSample = preprocessing.parameters.findIndex((u, i, a) => i > 0 && u < a[i - 1]);
  if (outOfOrderSample >= 0) {
    issue(["preprocessing", "parameters", outOfOrderSample], "Solver parameters must be nondecreasing.");
  }

  if (fit.status === "unavailable") {
    if (Object.values(fit.stages).some(Boolean)) {
      issue(["fit", "stages"], "An unavailable fit cannot contain a curve.");
    }
  } else if (!fit.stages.final) {
    issue(["fit", "stages", "final"], "A fitted or fallback result requires its final curve.");
  }
  if (fit.status !== "fitted" && !fit.reason?.trim()) {
    issue(["fit", "reason"], "Expected a reason for a fallback or unavailable result.");
  }
});

export type FitDocument = z.infer<typeof fitDocument>;
export type Point = z.infer<typeof point>;
export type Stage = z.infer<typeof stage>;

export function parseDocument(input: unknown): FitDocument {
  const parsed = fitDocument.safeParse(input);
  if (parsed.success) return parsed.data;
  const error = parsed.error.issues[0];
  const path = error.path.join(".") || "document";
  throw new Error(path + ": " + error.message);
}
