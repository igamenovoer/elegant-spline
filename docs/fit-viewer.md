# Inspect a planar fit

From the Elegant Spline repository root, launch the viewer and open the localhost URL printed by Bun.

```sh
cd web/spline-viewer
bun install --frozen-lockfile
bun run dev
```

The **Island bend** example opens with all four layers on the same XY grid. The first and last observations mark the ends of the ordered guide. **Open fit** reads an exported JSON file from your computer. A file that fails validation leaves the current view in place. [Export your own fit](viewer-format.md)

1. **Inspect the domain.** The hatched island is a hole. The shaded band shows the requested clearance of 0.45 m. Toggle **Clearance band** to inspect the original boundary. A curve can cross a hole or its band and remain visible. The **Fitted** badge records the solver outcome.
2. **Trace a merge.** In **Point inspector**, choose **Cluster** and enter index `2`. The plot highlights source indices `2, 3, 4` at the representative `(3.55, 4.70)` m and its nearby member locations. Choose **Observation** and step between indices `2` and `3` to inspect the two visits at the same coordinates. Purple diamonds mark representatives and small dots mark the resampled solver input.
3. **Inspect the curve.** Select **Final curve**. Control point `4` is near `(5.0703, 7.7632)` m. Bézier handle `4` is the outgoing handle on span `2`, near `(4.2632, 6.3632)` m. Toggle **Control polygon** and **Bézier handles** individually to see which points belong to each construction. Selecting **Before fairing** changes the displayed curve and its controls together.
4. **Inspect a corner at scale.** Drag the plot to pan, then zoom using the wheel, pinch or zoom buttons. Hide **Data points** or **Preprocessing** to isolate the geometry. Layer changes keep the current view. **Frame** returns to the full extent.

The package exports recorded curves, including line and constant fallbacks. An unavailable fit still opens with the observations and preprocessing data. The standalone viewer reads the saved file after the Python process exits. [Static build and checks](../web/spline-viewer/README.md)
