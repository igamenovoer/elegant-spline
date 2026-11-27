# Design

## Context

Elegant Spline has an installable Python 3.13 package, a locked Pixi environment with SciPy, and an installation smoke suite. The package currently exposes no fitting API. The [proposal](proposal.md) establishes the initial capabilities.

## Goals / Non-Goals

**Goals**

- Expose a typed Python API that works on arrays and SciPy splines supplied by any caller.
- Keep observation correspondence, fit stages, and failure outcomes inspectable.
- Make the curvature smoother independently usable and compose it into the planar fitter.

**Non-Goals**

- Hard spatial containment, obstacle clearance, and required interpolation at interior waypoints.
- A portable spline file format or shared algorithm registry.

## Decisions

### Use a SciPy spline as the common curve type

```text
Ordered XY + DistanceFitOptions
    |
    v
DistanceSplineFitter.fit() --> optional BSplineCurvatureSmoother
    |
    v
FitResult --> BSpline, source parameters, intermediate curves, FitReport

Existing vector BSpline + BSplineCurvatureSmoothingParams
    |
    v
BSplineCurvatureSmoother.smooth_with_report() --> BSplineSmoothingResult
```

Both objects hold validated immutable settings and keep per-call numerical state local. Reuse SciPy's representation and derivative API. A package-specific curve class was considered for serialization and would require a second evaluator and conversion contract before the library has a file format.

`DistanceFitOptions` requires a positive `rms_allowance` and `resample_spacing` in coordinate units. Defaults are `merge_diameter=0`, `endpoint_weight_multiplier=1`, `maximum_fit_points=4096`, `maximum_fit_attempts=1`, `correct_endpoints=True`, `fairing=None`, and `fallback="none"`. The fit-point cap accepts integers of at least four and the attempt budget accepts zero or one. Set `fallback="endpoint"` to request line or constant recovery. A settings object keeps repeated fits explicit and reproducible without reading global configuration.

`FitResult` exposes the final `curve`, `source_parameters`, an optional `initial_curve`, an optional `pre_fairing_curve`, and a `FitReport`. Its status is `fitted`, `fallback`, or `unavailable`. The unavailable result has no final curve. The report records the preprocessing ledger, numerical versions, solver work and warnings, correction and fairing outcomes, stage-specific measured residuals, and reasons for unavailable values.

### Pass prepared observations to one residual-budget cubic solve

Compute source parameters from cumulative chords of the original points. Use zero for every source parameter on a zero-length path. Collapse consecutive duplicates for guide construction and use the mean of the deduplicated coordinates in each whole-diameter cluster. Resample the guide in chord distance, retaining both ends. If sampling would exceed the cap, use the complete extent with spacing `guide_length / (maximum_fit_points - 1)`.

Compute trapezoidal support from the normalized fit parameters. Take its square root for each residual weight, apply the endpoint multiplier, then scale the weight vector to squared norm equal to the observation count. Keep the positive-weight normalization in the log domain as a recovery path for extreme representable scales. Use these weights and the explicit fit parameters with SciPy `make_splprep` at degree three. Adaptive knots suit the caller's residual allowance. A fixed knot count would expose a complexity control with different accuracy semantics.

Normalize returned coefficients to parameter-first evaluation with two coordinates per control. Require a finite clamped cubic on `[0, 1]` with simple interior knots and extrapolation disabled. Check values and the first two derivatives across interior joins. Skip the solve when fewer than four observations remain after consecutive deduplication, fewer than four strictly increasing fit parameters are available, or the attempt budget is zero.

### Preserve each usable stage

Evaluate endpoint offsets from the initial curve to the original source endpoints. Apply their affine interpolation at the cubic Greville abscissae to the control values and set the endpoint controls to the requested coordinates. Accept the corrected curve after structural and numerical verification. The affine correction preserves the basis and smoothness without a second solve. A joint endpoint-constrained optimization would change the initial residual-budget solver and feasible set.

Retain the initial fit if correction is disabled or its candidate fails verification. When integrated fairing is configured, require position-and-tangent preservation and pass the selected curve, prepared points, and fit parameters with equal fidelity weights. Accept a verified fairing result or keep the curve supplied to fairing. The first fit, the input to fairing, and the final curve remain separately inspectable where available.

An unavailable initial fit uses the explicit recovery setting. Endpoint recovery constructs a clamped cubic with four controls at fractions `0, 1/3, 2/3, 1` of the endpoint segment. This also represents a constant for coincident endpoints. Measure source error over the original observations. Record the initial and final weighted guide errors independently of requested budget and outcome. Compute measured weighted RMS from the weighted squared residual sum divided by the actual squared weight sum, then take its square root. Keep unauditable values unavailable with reasons.

### Preserve the existing spline basis during curvature fairing

The independent fairer accepts whole-domain, threshold-based, and explicit-interval selection. Optimize control values in the permitted support, using the null space of the evaluated endpoint constraints for boundary policies that pin positions or derivatives. Use one bounded optional fidelity initialization and one main least-squares solve. Fairing balances squared positional fidelity with geometric bending, and can add fidelity outside the selected support. Knot refitting would change the curve representation and its downstream correspondence. A coordinate second-derivative penalty has a different dependence on parameterization than geometric bending.

Use a separate verification grid and bounded refinement for basis parity, endpoint values, tangent regularity, and measured curvature. Report failed verification or insufficient work and preserve the input geometry. Keep sampled measurements identified as such.

## Risks / Trade-offs

- Closely spaced points, extreme weights, and nearly stationary tangents can cause numerical instability. Validate each candidate and report the stage and available measurements.
- Guide and source parameters serve different purposes. Preserve both and test duplicate and return-visit correspondence.
- NumPy and SciPy versions can affect solver decisions. Put deterministic fixture comparisons on the same numerical stack and test geometric invariants independently.
- Fairing can improve bending while increasing fit error. Report initial and final residuals and their respective budget findings.
