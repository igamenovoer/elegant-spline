# Fit a planar cubic with smoothing or knot spacing

Supply ordered coordinate pairs and a `PlanarFitOptions` object to either fitter. A successful fit returns a clamped cubic SciPy `BSpline` on normalized chord progress `[0, 1]` with C² continuity and extrapolation disabled. Use the same coordinate units for the points and all distance settings.

## Example

```python
from elegant_spline import PlanarFitOptions

points = [(0.0, 0.0), (0.5, 0.1), (1.0, 0.6), (1.5, 1.0), (2.1, 0.8), (2.8, 0.2)]
options = PlanarFitOptions(
    resample_spacing=0.1,
    merge_diameter=0.03,
    endpoint_weight_multiplier=2.0,
    maximum_fit_points=64,
)
```

Fit with a smoothing strength.

```python
from elegant_spline import SmoothingSplineFitter

smooth = SmoothingSplineFitter(smoothing_strength=1e-3, options=options).fit(points)
assert smooth.status == "fitted", smooth.report.solver_reason
assert smooth.curve is not None and smooth.report.final_metrics is not None
print(smooth.report.method, smooth.curve([0.0, 0.5, 1.0]))
print("Final weighted RMS:", smooth.report.final_metrics.weighted_rms)
```

Fit with a nominal knot spacing using the same points and options.

```python
from elegant_spline import FixedKnotSplineFitter

fixed = FixedKnotSplineFitter(knot_spacing=0.6, options=options).fit(points)
assert fixed.status == "fitted", fixed.report.solver_reason
assert fixed.curve is not None and fixed.report.final_metrics is not None
print(fixed.report.method, fixed.curve([0.0, 0.5, 1.0]))
print("Final weighted RMS:", fixed.report.final_metrics.weighted_rms)
basis = fixed.report.fixed_knot
assert basis is not None
print("Selected spans:", basis.selected_span_count)
print("Effective spacing on the guide:", basis.effective_spacing)
```

## Shared options

| Option | Effect |
| --- | --- |
| `resample_spacing` | Required positive spacing for sampling along the prepared guide. |
| `merge_diameter` | Maximum diameter of a consecutive group of observations. The default of zero keeps distinct consecutive points separate. |
| `endpoint_weight_multiplier` | Positive multiplier for the endpoint residual weights in the initial fit. The default is one. |
| `maximum_fit_points` | Maximum number of prepared points, at least four. The default is 4096. The spacing becomes coarser when needed to keep both guide endpoints within this limit. |

Both fitters collapse consecutive duplicates and retain the original observation order, including return visits. The result stores one `source_parameters` entry per original observation. `report.guide` records the correspondence, normalized weights, and requested and effective resampling spacing.

## Smoothing strength

`SmoothingSplineFitter` balances the weighted squared guide residuals against the integrated squared second derivatives of the coordinates over normalized progress. Set a finite nonnegative `smoothing_strength`. A strength of zero interpolates the prepared points at the initial stage, verified componentwise with relative tolerance `1e-9` and absolute tolerance `1e-12` in coordinate units. A larger strength gives more weight to the derivative penalty. The fitter requires at least five strictly increasing prepared parameters and four source observations after consecutive duplicates are collapsed. The report records the requested strength in `smoothing_strength`.

## Fixed-knot spacing

`FixedKnotSplineFitter` uses weighted least squares with fixed knots. Set a finite positive `knot_spacing` in coordinate units. The fitter divides the prepared guide length by this spacing and rounds up to at least one span. It uses at most the number of prepared points minus three spans and spaces the interior knots uniformly in progress. The fitter requires at least four strictly increasing prepared parameters and four source observations after consecutive duplicates are collapsed.

`report.fixed_knot` gives `requested_spacing`, `requested_span_count` when representable, and `selected_span_count` once the basis is built. `effective_spacing` is the prepared guide length divided by that selected count. These values describe the initial fitting basis. The fitted curve has its own arc length.

## Outcomes and measurements

By default, endpoint correction targets the first and last original points. Pass `correct_endpoints=False` to keep the initial endpoints. Supply `fairing` settings to fair the cubic after endpoint processing. By default, a skipped or failed initial fit yields status `unavailable`. Set `fallback="endpoint"` to request a cubic line or a constant for coincident endpoints. Set `maximum_fit_attempts=0` to skip the initial fit. Each smoothing fit counts the pair of coordinate solves as one attempt.

Check `solver_status`, `correction_status`, and `fairing_status` for the outcome of each stage. The report measures ordered source errors and weighted guide residuals separately on the initial and final curves. It sets `residual_budget` and metric `budget_met` to `None` for these two methods. Choose an RMS allowance with the [distance fitter](distance-fitting.md), or see the [fairing reference](curvature-smoothing.md) for geometric curvature controls.
