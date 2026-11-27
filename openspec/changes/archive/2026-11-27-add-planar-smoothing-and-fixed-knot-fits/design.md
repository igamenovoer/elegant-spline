# Design

## Context

`DistanceSplineFitter.fit` already owns ordered point validation, guide preparation, endpoint correction, optional curvature fairing, recovery, and measurement. It also computes the distance solver's residual budget and runs its initial fit. The new fitting criteria vary the initial solve and its diagnostics. See the [proposal](proposal.md) and [behavior contract](specs/planar-regularized-and-fixed-knot-fitting/spec.md).

Elegant Spline declares SciPy 1.15 as its minimum version. Its smoothing spline routine accepts one coordinate at a time at that floor. Read-only probes on SciPy 1.15.0 and 1.18.1 verified the per-coordinate approach and planar QR least squares on synthetic data. On 1.18.1 the separated smoothing solves matched the batched result.

## Goals / Non-Goals

**Goals**

- Give guide preparation, fit-stage policies, and reporting one owner across the three fitters.
- Keep the existing distance API compatible and make each new method directly usable from an installed package.
- Keep each method's numerical preconditions and diagnostics close to its solve.

**Non-Goals**

- Timed trajectories and hard domain containment are separate fitting problems with their own inputs and acceptance criteria.

## Decisions

### Expose two concrete fitters with one shared options object

Export `SmoothingSplineFitter`, `FixedKnotSplineFitter`, and an immutable `PlanarFitOptions` at package level. Each fitter has `fit(points_xy) -> FitResult` and takes its own required method control as a keyword. `PlanarFitOptions` has required `resample_spacing` and the existing common controls `merge_diameter`, `endpoint_weight_multiplier`, `maximum_fit_points`, `maximum_fit_attempts`, `correct_endpoints`, `fairing`, and `fallback`. Use the distance fitter's defaults for those common controls. Endpoint correction is enabled by default, and fairing and endpoint recovery are opt-in.

```python
options = PlanarFitOptions(
    resample_spacing=0.1,
    merge_diameter=0.02,
    endpoint_weight_multiplier=1.0,
    maximum_fit_points=4096,
)
smooth = SmoothingSplineFitter(smoothing_strength=1e-4, options=options).fit(points)
fixed = FixedKnotSplineFitter(knot_spacing=0.5, options=options).fit(points)
```

Keep the existing flat `DistanceFitOptions` fields, constructor argument order, defaults, and import paths. Resolve those common values into the same internal options used by the new fitters. Separate concrete constructors make the valid settings visible in Python signatures. A single public algorithm selector would need conditional validation for its mode-specific arguments.

### Run shared stages around one private initial solve

Share the existing pipeline for source chord progress, bounded guide preparation, initial solver status, curve validation, endpoint correction, fairing, recovery, and metrics. Use a small private callable per method to supply the initial solve and its numerical evidence. All curve normalization and validation feed the same stage flow. Guide weights describe the numerical fit. The optional fairer continues to use its existing equal fidelity weights against the prepared guide.

Append defaulted method evidence to `FitReport` so existing report construction and access remain compatible. Use a method identifier, the requested strength for smoothing, and a small record of requested knot spacing and span counts for the fixed-knot method. Effective knot spacing is prepared guide length divided by the selected count. The basis evidence describes the initial solve, including when a subsequent failure leads to recovery. Common errors are measured on each available stage, and both new methods leave `residual_budget` and `budget_met` unset.

### Solve the two numerical problems with the existing SciPy floor

- **Smoothing.** Apply `make_smoothing_spline` separately to X and Y with the same strictly increasing progress samples and explicit smoothing strength. The shared guide weights `w` multiply residual amplitudes, so pass `w**2` to SciPy's weighting of squared residuals. Verify matching knot vectors and assemble the two coefficient columns into one planar cubic. Count the pair as one initial fit attempt. If either solve or the assembled curve is unusable, use the ordinary failed-fit path.
- **Fixed knots.** Compute the requested span count from guide length and nominal spacing. Cap it at the prepared sample count minus three before allocating the basis. Use simple uniform interior knots in normalized progress and four copies of each endpoint knot. Call `make_lsq_spline` with degree three, guide weights `w`, and `method="qr"`. For an overflowing length-to-spacing ratio, use the available span cap and leave the requested count unavailable.

Reconstruct both fitted outputs with a canonical axis-zero coefficient layout and extrapolation disabled before applying the shared validation. Using scalar smoothing on every supported version gives the package one numerical path to test. The extra solver call buys compatibility with SciPy 1.15.

## Risks / Trade-offs

- **Extreme weights can make the smoothing system unusable.** A positive guide weight can round to zero when squared, or lead to nonfinite arithmetic in the solve. Preserve the requested objective, report a numerical failure, and apply the caller's recovery policy.
- **Postprocessing can change the initial method's measured result.** Report initial and final errors separately. For example, zero smoothing strength interpolates the prepared guide at the initial stage and endpoint correction can change those interpolated positions.
- **Nominal knot spacing and guide resolution interact.** Document the count cap and expose its resulting spacing. The reported spacing is on the prepared guide. The fitted curve has its own arc length.

## Migration Plan

The new fitters are additive package exports. Existing callers keep their current entry point. A standalone caller can opt in by selecting a new fitter and passing common options and the method's required control.
