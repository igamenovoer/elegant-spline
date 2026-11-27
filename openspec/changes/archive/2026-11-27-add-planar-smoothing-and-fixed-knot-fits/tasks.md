# Tasks

## 1. Share planar fitting stages

- [x] 1.1 Introduce immutable `PlanarFitOptions` and use one validation and preparation path for common options. Preserve the `DistanceFitOptions` constructor and exports. Verify the existing distance tests still pass, including guide weights, point caps, and source correspondence.
- [x] 1.2 Move the existing stage flow behind a private initial-fit boundary. Preserve curve validation, correction, fairing, recovery, and per-stage metrics. Add defaulted method evidence to `FitReport`. Verify distance outputs still match the SciPy reference and that existing correction and fairing failure cases retain the expected curve.

## 2. Add the smoothing fitter

- [x] 2.1 Export `SmoothingSplineFitter` and implement the paired coordinate solve with explicit strength and squared guide weights. Verify public initial-curve evaluation against independent scalar SciPy references on a curved guide with nonuniform weights. Verify zero strength interpolates the prepared points.
- [x] 2.2 Verify the five-point threshold, one-attempt accounting, and unavailable or explicit fallback outcomes when an axis solve fails or its transformed weights are unusable. Document smoothing strength, the prepared-point threshold, and shared options in a runnable standalone example.

## 3. Add the fixed-knot fitter

- [x] 3.1 Export `FixedKnotSplineFitter` and implement the spacing-derived QR fit and its basis report. Verify public initial-curve evaluation against a weighted QR reference and cover the four-point case, one span, span capping, and an unrepresentable spacing ratio.
- [x] 3.2 Check both new fitters against the shared guide and output contract using a synthetic path with repeated observations and a return visit. Verify preprocessing options and the cap affect the reported guide, the returned curves retain the requested endpoints and C² joins, and final metrics describe the returned curve. Exercise optional fairing with at least one new fitter.
- [x] 3.3 Document nominal and effective knot spacing, their relation to the guide, and the available report fields. Add links to both methods in the standalone usage index and run the examples with synthetic data.

## 4. Verify the standalone package

- [x] 4.1 Run `pixi run --locked test` from the Elegant Spline root. Build the wheel and run the public fitting examples from outside the source checkout in isolated environments with the minimum supported SciPy release and the locked release. Verify imports, curve evaluation, and method reports with only the declared runtime dependencies.
