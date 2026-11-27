# Design

## Context

The three planar fitters return the same `FitResult`. It carries a SciPy cubic B-spline, any retained intermediate curves, source parameters, and a `GuideReport` with cluster membership, representatives and resampled solver observations. The caller owns the original XY observations and the intended domain. The package currently has a locked Python environment and no browser app. [Fit contract](../../../docs/distance-fitting.md) · [Shared fitter tests](../../../tests/integration/test_planar_fitters.py)

## Goals / Non-Goals

The first viewer is a read-only instrument for recorded planar fits. Selecting a control or handle inspects its coordinates and moving around the plot changes only the camera. A live curve editor would also need decisions about rerunning preprocessing, fitting and spatial verification after a drag. Those decisions belong to a separate change. The proposed viewer draws the intended domain and any crossing curve. Establishing whole-curve containment belongs to the fitting and verification algorithm.

## Decisions

### Export geometry where the fit was computed

Add a small public export helper in `src/elegant_spline/` that takes the original point sequence, its `FitResult`, an optional domain and an optional unit label. Produce strict JSON suitable for a local file. The version-1 document contains the following records.

| Record | Contents and interpretation |
| --- | --- |
| Domain | One outer XY ring, zero or more hole rings and an optional nonnegative clearance in coordinate units. Rings describe the intended region. |
| Observations | Original XY pairs in caller order, each with its source parameter. Array index identifies the observation, even on a return visit. |
| Preprocessing | One cluster index per observation, `guide_points` as the representatives, and `points` and `parameters` as the resampled solver input. Copy them from the report. |
| Fit | Fitting method, `fitted`, `fallback` or `unavailable` status, and the applicable recovery or failure reason. Include the final curve when available and named initial and pre-fairing stages when the result supplies them. |
| Curve stage | Native B-spline control points in coefficient order and the ordered nonempty cubic spans. Each span stores its parameter endpoints and four Bézier points in world coordinates. |

A sampled polyline would lose the handles and introduce a zoom-dependent approximation. Use the existing SciPy spline to compute the four exact Bézier points for each nonempty knot interval `[a, b]`. With `h = b - a`, these are `C(a)`, `C(a) + h*C'(a)/3`, `C(b) - h*C'(b)/3` and `C(b)`. The span width matters at a nonuniform knot. Skip zero-width intervals at clamped ends. SVG can use these four points directly for a cubic path, so the stroke and the inspected handles have one source. Keep the native coefficient polygon separately for inspecting the fitted basis. [SciPy spline evaluation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.BSpline.html) · [SVG cubic paths](https://www.w3.org/TR/SVG2/paths.html#PathDataCubicBezierCommands)

### Use one viewport for the four layers

Render an SVG group for each layer under a shared world-to-screen transform. Use a uniform scale and invert the screen Y axis once. Give the domain an even-odd fill so holes work in either winding direction. Draw an optional clearance band by stroking the rings at twice the specified radius with round joins and clipping the band to the permitted polygon. Keep the curves outside that clip so excursions remain visible. Frame all geometry when opening a file or on an explicit reset. Give a coincident point finite framing bounds.

Use labeled checkboxes for the four groups. Start the example with all four visible. Within Fitted curve, the stroke, native control polygon with its points, and Bézier handles with their anchors each have a switch. An available-stage selector defaults to the final curve. Keep the camera, layer settings and the document separate in view state. Use the source index, cluster index, or curve stage and control or span index for selection. An indexed selector lets users inspect coincident points. Distinguish resampled points, representatives and source points by marker shape, and show a selected cluster’s member indices beside the plot.

### Keep the app local and use libraries for interaction and validation

Use Bun to install and lock the dependencies in `web/spline-viewer/`, run the HTML entry in development, and produce a static build. TypeScript and SVG cover the four layers. A Canvas renderer would also draw the curves, but would need custom hit testing for the points and handles. Use `d3-selection` for keyed SVG elements and `d3-zoom` to handle pan, wheel and touch zoom with one transform. Browser dependencies belong to the app’s own `package.json` and checked-in `bun.lock`. [Bun HTML builds](https://bun.com/docs/bundler/html-static) · [Bun lockfile](https://bun.com/docs/pm/lockfile) · [D3 selections](https://d3js.org/d3-selection/joining) · [D3 zoom](https://d3js.org/d3-zoom)

Use Zod at the file boundary for runtime validation and TypeScript type inference. Validate the version, finite coordinate pairs, ring shapes, index and array correspondence, span structure and fit status. Parse a user-selected file locally, then replace the displayed document in one update after validation. On failure, show the field or version that failed. A bundled, reproducible example exercises this same parser. A live Python service would couple inspection to a running solver. A saved document also works when a colleague opens it later with only the browser app. [Zod parsing and inferred types](https://zod.dev/basics)

## Risks / Trade-offs

| Risk | Mitigation |
| --- | --- |
| The producer and viewer interpret a field differently | Generate the checked-in example with the public exporter on a polygon with a hole and an actual merge. Use that file in browser tests. Compare exported Bézier evaluations against SciPy at interior probes on unequal knot spans. |
| A user reads a displayed clearance band as a successful verification | Label the band as the requested clearance and present the library’s fit status as a fitting outcome. A crossing curve stays visible. |
| Overlapping points or a constant fallback disappear at the current scale | Provide indexed selection, distinct marker shapes and finite framing for degenerate extents. Clear stage-specific selection when the stage or document changes. |
