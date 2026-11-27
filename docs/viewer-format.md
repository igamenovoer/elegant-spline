# Export a fit for the viewer

Pass the same ordered observations used to fit the curve and the returned `FitResult` to `export_viewer_document`. It returns a mapping suitable for writing as JSON. All coordinates and the optional clearance share the input’s length unit. [Planar fitting](planar-fitting.md)

```python
import json
from pathlib import Path

from elegant_spline import FixedKnotSplineFitter, PlanarFitOptions, export_viewer_document

points = [(0, 0), (1, 1), (1, 1), (1.04, 1), (2, 1.5), (3, 1), (4, 0)]
options = PlanarFitOptions(resample_spacing=0.2, merge_diameter=0.08)
result = FixedKnotSplineFitter(knot_spacing=1.3, options=options).fit(points)
domain = {
    "outer": [(-1, -1), (5, -1), (5, 3), (-1, 3)],
    "holes": [[(1.5, 0), (2.5, 0), (2, 0.8)]],
    "clearance": 0.15,
}
document = export_viewer_document(points, result, domain=domain, unit="m")
Path("fit.json").write_text(json.dumps(document, allow_nan=False), encoding="utf-8")
```

`domain` and `unit` default to `None`. A domain needs an outer ring with at least three distinct vertices. Its holes default to an empty list, and its clearance defaults to `None`. Give the exporter a simple outer ring and simple, disjoint holes inside it. Rings close implicitly and may be supplied in either winding order. The domain describes where the caller intends the curve to lie. Fitting status and clearance verification describe separate properties.

## Version 1 document

| Field | Contents |
| --- | --- |
| `version`, `unit` | Integer `1` and the optional unit string. Absent units serialize as `null`. |
| `domain` | `null` or an object with `outer`, `holes`, and `clearance`. Each ring lists XY pairs. The clearance is a finite nonnegative number or `null`. |
| `observations` | An ordered array of objects with an `xy` pair and normalized source parameter `u`. The zero-based array index identifies a visit, including visits that coincide in space. |
| `preprocessing.membership`, `preprocessing.representatives` | Each observation maps to one zero-based cluster index. That index addresses the representative XY in `representatives`. |
| `preprocessing.points`, `preprocessing.parameters` | Ordered solver observations and their corresponding normalized guide parameters after resampling. |
| `fit.method`, `fit.status`, `fit.reason` | Fitter name, one of `fitted`, `fallback` and `unavailable`, and the applicable recovery or solver reason. A successful ordinary solve has a null reason. |
| `fit.stages` | Available stages keyed by `initial`, `preFairing` and `final`. A fallback has final geometry only. An unavailable result has an empty stages object. |
| `stage.controls` | The native cubic B-spline’s XY coefficients in control-polygon order. |
| `stage.spans` | Ordered nonempty knot intervals. Each stores endpoints `a` and `b` in normalized spline progress and four cubic Bézier `points` in XY coordinates. These are the start anchor, outgoing handle, incoming handle, and end anchor. |

## Reproduce the island example

From the Elegant Spline checkout, generate the bundled document or supply another output path.

```sh
pixi run --locked python scripts/export_viewer_example.py
pixi run --locked python scripts/export_viewer_example.py island-fit.json
```

The example fits 13 ordered observations around a polygonal island. Source indices 2 and 3 both visit `(3.5, 4.6)`. Index 4 visits `(3.6, 4.8)`. These three belong to cluster 2, whose representative is `(3.55, 4.70)`. The solver receives 37 resampled points and returns a curve with eight spans. The document retains the initial, pre-fairing and final stages. [Example generator](../scripts/export_viewer_example.py) · [Bundled document](../web/spline-viewer/example.json)
