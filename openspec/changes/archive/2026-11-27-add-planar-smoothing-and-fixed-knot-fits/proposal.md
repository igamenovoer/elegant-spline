# Proposal

## Why

Elegant Spline currently fits ordered planar points using a weighted RMS allowance. Callers also need ways to control the smoothing penalty on coordinate second derivatives or the number of knot spans through a nominal spacing.

## What Changes

- Add a cubic smoothing spline fitter controlled by a caller-supplied smoothing strength and a fixed-knot cubic least-squares fitter controlled by nominal knot spacing.
- Expose shared preprocessing options for resampling, whole-group merge diameter, endpoint weight, and the fit point limit. Express distance settings in the caller's coordinate units.
- Reuse the existing stages for input validation, endpoint correction, optional geometric fairing, explicit recovery, and measurement. Preserve the public distance-fitting contract.
- Describe the new methods with standalone examples and verify them using synthetic observations in the installed package.

## Capabilities

### New Capabilities

- `planar-regularized-and-fixed-knot-fitting` covers the two new fitting criteria, their common options, and the evidence returned by each fitter.

### Modified Capabilities

## Impact

Adds Python APIs under `src/elegant_spline/` and extends the fit report with method evidence. The package continues to run independently with NumPy and SciPy at the existing dependency floor. This change covers ordered planar approximation and its existing optional fairing stage.
