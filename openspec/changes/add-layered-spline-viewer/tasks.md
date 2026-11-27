# Tasks

## 1. Export an inspectable fit

- [x] 1.1 Implement the version-1 document exporter in the Python package. Cover all three planar fitting methods, the optional domain and unit, duplicate observations, a later return visit, a real cluster merge and the resampled solver input. In Python tests, compare the exported coordinates, source parameters and membership directly with the input and fit report and serialize with nonfinite values disallowed.
- [x] 1.2 Export each available stage’s native coefficients and cubic Bézier spans. Verify endpoints, interior positions and first derivatives against SciPy on unequal-width spans with clamped ends. Cover line and constant fallbacks, absent stages and an unavailable result with its reason.
- [x] 1.3 Add a runnable synthetic example under `scripts/` and its exported JSON under `web/spline-viewer/`. Include a holed domain, an ordered guide with a merge, and a multi-span fit. Document the exporter and file format under `docs/`. Run the documented example in the locked Python environment and verify that its geometry and cluster membership agree with the checked-in fixture within numerical tolerance.

## 2. Open documents in the standalone Bun app

- [x] 2.1 Add the app’s HTML and TypeScript entry, `package.json` and `bun.lock`. Use Bun for development and static builds. Add D3 selection and zoom, Zod, and browser test tooling scoped to the app. Document the local install and run commands and verify `bun install --frozen-lockfile` and `bun run build` from the app directory.
- [x] 2.2 Validate and open the bundled example and local JSON through the same reader. Test an unknown version, malformed coordinates and invalid cluster references. In a browser, load a valid file followed by an invalid one and verify that the error identifies the problem and the previous plot is still usable.

## 3. Inspect the four layers

- [x] 3.1 Implement the equal-scale XY viewport, pan, zoom, frame and four independent layer controls. Render the polygon, hole rings and optional clearance band. With an asymmetric fixture, verify axis orientation, round-trip layer toggling at a zoomed location, an open hole, and a curve segment still visible inside that hole. Exercise a document with no domain.
- [x] 3.2 Draw ordered source observations, merge representatives, member associations and resampled points with distinguishable marks. Provide selection by index for coincident points. Verify that a representative selects exactly its recorded members, each revisit is individually inspectable and hiding a layer removes its marks from picking.
- [x] 3.3 Draw the selected stage’s exact cubic path, native controls and polygon, and anchored Bézier handles. Test their individual switches, a change of stage at fixed zoom and inspection at a nonuniform knot. Open a constant fallback and then an unavailable fit and verify framing, status, reason and removal of stale geometry.
- [x] 3.4 Add a short viewing guide and link it from the project’s getting-started documentation. Follow it on the bundled example to inspect a hole, trace a merged observation and identify a native control point and a span handle by their reported coordinates.

## 4. Verify the export-to-browser workflow

- [x] 4.1 Run the locked Python suite and the viewer tests. Exercise the production build in a real browser with a newly exported file, then toggle each layer, inspect a merged cluster and switch curve stage. Verify that the viewer works from the built assets and the local document with the Python producer stopped.
