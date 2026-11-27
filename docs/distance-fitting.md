# Fit a planar curve

Supply an ordered array of planar points to `DistanceSplineFitter`. Coordinates, the RMS allowance, merge diameter, and resample spacing share the caller's coordinate units. A fit returns a SciPy cubic `BSpline` on normalized progress `[0, 1]` with extrapolation disabled.

```python
from elegant_spline import DistanceFitOptions, DistanceSplineFitter

points = [(0, 0), (3, 0), (4, 1), (5, -0.4), (6, 4), (7, 4)]
options = DistanceFitOptions(rms_allowance=0.142, resample_spacing=0.1)
result = DistanceSplineFitter(options).fit(points)

assert result.status == "fitted"
assert result.curve is not None
print(result.curve([0.0, 0.5, 1.0]))
print(result.report.initial_metrics.weighted_rms)
print(result.report.final_metrics.weighted_rms)
```

## Guide and residuals

`source_parameters` gives one cumulative chord parameter for each original point, including consecutive duplicates and return visits. `report.guide` gives the resampled points, separate solver parameters, and normalized weights. Its cluster membership contains one cluster index per original point. Set `merge_diameter` to combine nearby points by whole-group diameter. `maximum_fit_points` caps resampling while retaining the guide endpoints.

The fitter performs one initial solve with a budget of the fit observation count times the squared RMS allowance. The report measures weighted guide error and ordered source error separately on the initial and final curves. Weighted RMS is the square root of the weighted squared residual sum divided by the squared weight sum. The final curve can exceed the initial allowance after correction or fairing. `budget_met` reports the measured outcome for each available stage.

## Stage outcomes and recovery

By default the fitter corrects the endpoints of a usable initial curve. It accepts an endpoint correction when each endpoint is within `1e-9` coordinate units of the requested value. The cubic verification checks for simple interior knots and also compares one-sided values and derivatives through order two at each join, with a tolerance of `1e-7` times the larger of one and the local value or derivative magnitude.

A successful initial solve yields status `fitted` even if correction fails, in which case the fitter retains the initial curve for subsequent processing. An initial solve that fails or is skipped yields status `unavailable` by default. Set `fallback="endpoint"` to request a cubic line between the endpoints or a constant for coincident endpoints. A verified recovery has status `fallback` and includes errors measured against the original observations. If finite arithmetic prevents verification of the recovery curve, the result stays `unavailable` and `recovery_reason` records the failure.

Pass fairing settings to run one fixed-knot pass after endpoint processing. The result records the input to fairing as `pre_fairing_curve` and distinguishes a verified result, a no-op, and a failure. Failed fairing retains its input. [Combined example](fit-and-fair.md)
