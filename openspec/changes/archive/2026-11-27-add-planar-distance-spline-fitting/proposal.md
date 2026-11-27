# Proposal

## Why

Elegant Spline needs a first usable fitting API for ordered planar observations whose accuracy and smoothness matter. Callers need to inspect the resulting curve, its correspondence to their data, and the outcome of each numerical stage before using it.

## What Changes

- Add a distance-based cubic B-spline fitter with bounded guide preparation, a caller-supplied weighted RMS allowance, and endpoint correction.
- Add an independently callable fixed-knot curvature smoother for vector-valued B-splines. The planar fitter can invoke it once after endpoint correction.
- Return structured fitting and smoothing results with measured residuals, stage outcomes, and the curve retained after numerical difficulty. Make line or constant recovery an explicit fitting option.
- Add a standalone usage example and verification using synthetic points and splines.

## Capabilities

### New Capabilities

- `planar-distance-spline-fitting` covers ordered planar input, guide preparation, residual-budget fitting, endpoint correction, and fit outcomes.
- `bspline-curvature-smoothing` covers geometric-curvature fairing of an existing vector spline with fixed knots, configurable endpoint preservation, and numerical verification.

### Modified Capabilities

## Impact

Adds public numerical APIs under `src/elegant_spline/` with NumPy and SciPy dependencies. Updates package metadata, the Pixi lockfile, usage documentation, and feature tests. This change establishes a fitting and fairing baseline for later work on required spatial containment and clearance.
