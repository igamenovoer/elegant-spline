# Tasks

## 1. Numerical dependencies

- [x] 1.1 Declare NumPy as a direct runtime dependency, retain the SciPy floor, and update the Pixi lock. Verify `pixi lock --check` and import both packages from the locked environment.

## 2. Planar distance fitting

- [x] 2.1 Implement and validate immutable fitting options and ordered guide preparation. Add unit tests for rejected inputs, unchanged input values, duplicates, return visits, whole-group diameter, chord parameters, and capped resampling that preserves the guide endpoints.
- [x] 2.2 Implement the weighted cubic solve and endpoint correction. Compare an eligible synthetic fit against an independently prepared SciPy reference under the same numerical versions. Check position and the first two derivatives across interior knots, both endpoint errors, and a post-correction residual above the initial budget.
- [x] 2.3 Expose `DistanceSplineFitter`, `FitResult`, and the fit report. Verify separated source and guide errors, retained stage curves, and explicit statuses on a short track, a zero attempt budget, a forced solver failure, a failed endpoint correction, and a closed path with constant recovery. Document the fit API, units, recovery option, and measured residuals with a runnable synthetic example.

## 3. Independent curvature smoothing

- [x] 3.1 Expose `BSplineCurvatureSmoother` with validated immutable settings and structured outcomes. Test malformed settings and observations, unsupported splines, non-unit domains, both coordinate layouts, and input immutability.
- [x] 3.2 Implement fixed-basis fairing with caller-selected endpoint policies and region selection. Verify evaluated positions and first derivatives on unclamped splines, automatic and explicit region selection, overlapping intervals, and unchanged outcomes for empty support or unavailable free directions.
- [x] 3.3 Implement the bounded fidelity and geometric-bending solves with an independent candidate audit. Verify preserved observation correspondence, rigid-transform invariance, repeated calls, constant curves, work exhaustion, and unresolved stationary tangents. Document a runnable fairing example with interpretation of coverage and failure reports.

## 4. Pipeline and distribution verification

- [x] 4.1 Compose optional fairing into the planar fitter with position-and-tangent preservation and equal observation weights. Test one call after endpoint processing, both curve states and final evidence, disabled fairing, and retention after fairing failure. Exercise the combined usage example from the documentation.
- [x] 4.2 Run `pixi run --locked test`, build the wheel, and install it in a clean environment outside the checkout. Verify that the installed fitting and smoothing APIs run the synthetic examples with their declared dependencies.
