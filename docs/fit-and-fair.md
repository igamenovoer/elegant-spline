# Fit and fair a planar curve

A distance fit can include a fixed-knot curvature pass. The fitter applies endpoint correction before fairing. The fairing pass uses the prepared observations and preserves the corrected curve's basis, endpoint values, and first derivatives.

Run this example in the installed environment. It fits an ordered set of points sampled along a U-shaped path.

```python
import numpy as np

from elegant_spline import (
    BSplineCurvatureSmoothingParams,
    DistanceFitOptions,
    DistanceSplineFitter,
)

outbound = np.column_stack((np.linspace(0.0, 4.0, 60), np.zeros(60)))
angle = np.linspace(0.0, np.pi, 41)
bend = np.column_stack((4.0 + 0.35 * np.sin(angle), 0.35 - 0.35 * np.cos(angle)))
inbound = np.column_stack((np.linspace(4.0, 0.0, 60), np.full(60, 0.7)))
points = np.vstack((outbound, bend[1:], inbound))

options = DistanceFitOptions(
    rms_allowance=0.15,
    resample_spacing=0.1,
    merge_diameter=0.1,
    endpoint_weight_multiplier=4.0,
    fairing=BSplineCurvatureSmoothingParams(
        lambda_curvature=0.01,
        fidelity_scale=0.1,
        outside_scale=0.05,
        region_mode="auto",
        curvature_threshold=2.0,
    ),
)
result = DistanceSplineFitter(options).fit(points)

assert result.status == "fitted"
assert result.curve is not None and result.pre_fairing_curve is not None
ends = [0.0, 1.0]
np.testing.assert_allclose(result.curve(ends), points[[0, -1]], atol=1e-9)
np.testing.assert_allclose(
    result.curve(ends, nu=1), result.pre_fairing_curve(ends, nu=1), atol=1e-8
)
print(result.report.fairing_status)
```

Use the fit report to distinguish a verified fairing result, a no-op, and a numerical failure. When fairing cannot produce a usable result, the returned curve retains the geometry supplied to the fairer. The weighted RMS allowance applies to the initial solve. The final report measures residuals again after endpoint correction and fairing. [Distance fitting](distance-fitting.md) · [Curvature smoothing](curvature-smoothing.md)
