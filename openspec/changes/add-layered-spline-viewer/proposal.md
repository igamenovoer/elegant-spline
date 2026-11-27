# Proposal

## Why

A planar fit can follow its target points closely and still cut across a hole in the intended domain. Seeing the original observations, the points actually used by the solver, and the final spline together lets a developer locate where the deviation arose.

## What Changes

- Add a standalone browser viewer in `web/spline-viewer/`, with Bun-managed dependencies, a bundled example, and a local file picker for saved fits.
- Show the polygonal domain and its holes, the target points in traversal order, the reported preprocessing decisions, and the fitted curve as four independently toggleable layers on one equal-scale XY plot.
- Let the reader trace a merged point back to its source indices, inspect resampled solver points, and independently reveal the curve stroke, native B-spline controls and per-span Bézier handles. Keep the same view while switching layers or inspecting another available fit stage.
- Provide a Python exporter that uses the original observations and an Elegant Spline `FitResult` to write the viewer document. Include a reproducible example with an interior hole and a real point merge.

## Capabilities

### New Capabilities

- `planar-fit-viewer` covers exporting a planar fit and inspecting its geometry, preprocessing and curve construction in a local web app.

### Modified Capabilities

## Impact

The change adds a viewer exporter to the Python package, a browser app with its own `package.json` and `bun.lock`, and usage documentation and tests in Elegant Spline. The existing planar fitters already supply the guide report, intermediate curves and final curve. The viewer consumes those results and accepts the intended domain from the caller. [Current fit API](../../../docs/distance-fitting.md)
