# Fixed-knot curvature smoothing

`BSplineCurvatureSmoother` fairs an existing real vector-valued SciPy `BSpline` by adjusting its control values. The input must be nonperiodic and globally C2, with degree at least three and at least two coordinates. The result preserves the degree, knots, parameter domain, evaluation layout, and extrapolation setting.

## Smooth a bend

```python
import numpy as np
from scipy.interpolate import BSpline

from elegant_spline.curvature_smoothing import (
    BSplineCurvatureSmoother,
    BSplineCurvatureSmoothingParams,
)

knots = np.r_[np.zeros(4), np.linspace(0, 1, 10)[1:-1], np.ones(4)]
controls = np.column_stack((np.linspace(0, 10, 12), np.zeros(12)))
controls[5, 1] = 2.0
curve = BSpline(knots, controls, 3, extrapolate=False)
parameters = np.linspace(0, 1, 101)

smoother = BSplineCurvatureSmoother(
    BSplineCurvatureSmoothingParams(
        lambda_curvature=0.01,
        fidelity_scale=0.1,
        region_mode="auto",
        curvature_threshold=2.0,
        outside_scale=0.05,
    )
)
result = smoother.smooth_with_report(
    curve, points=curve(parameters), parameters=parameters
)
print(result.report.outcome, result.report.reason)
print(result.report.regions.selected)
print(result.report.measurements.peak_curvature)
```

## Choose the fitting reference and support

- Supply observations and their nondecreasing parameters together to measure fidelity at fixed correspondences. Optional positive observation weights multiply the squared positional errors. With just a spline, fidelity measures displacement from the original curve, weighted by its arc length.
- `fidelity_scale` and `outside_scale` use the units of the input coordinates. The bending term integrates squared geometric curvature along the candidate curve over the selected regions and scales the integral by the original curve length. `lambda_curvature` controls its weight relative to fidelity.
- `region_mode="all"` selects the whole spline. `region_mode="auto"` takes a positive curvature threshold in reciprocal coordinate units. To specify the scope directly, pass in-domain `regions` as parameter intervals. Their union takes precedence over automatic selection. Pass an empty list to request no smoothing. Padding and transition widths are measured in knot spans.
- `endpoint_policy="free"` permits changes at both ends. `"position"` keeps endpoint values, and the default `"position_and_tangent"` also keeps first parameter derivatives. Endpoint checks use the evaluated spline on its base domain, including for unclamped splines.

## Read the result

`smooth_with_report()` returns a `spline` and a `report`. A `completed` result passed an independent numerical audit. An `unchanged` result retained the input geometry because no solve was needed, for example when the selected support has no free controls. A `failed` result retains the input geometry and provides the reason and any finite `attempted_spline` separately. For a spline-only API that raises on numerical failure, call `smooth()`.

Read `regions` to see the selected intervals, their padded extent, the free controls, and the portion of the curve strictly outside their influence. Read `verification` for audit grid sizes, endpoint checks, tangent regularity, and convergence findings. The solve records include any fidelity initialization and the main solve. Each solve uses the configured `max_nfev` limit. `measurements` includes before and after values. A value of `None` carries a reason, including unavailable curvature on a constant curve. Use `report.to_dict()` to serialize numerical evidence. Treat reported curvature and bending as sampled measurements and check application-specific limits separately.
