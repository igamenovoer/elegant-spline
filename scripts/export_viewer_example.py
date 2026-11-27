"""Fit a guide around an island and save the geometry for the browser viewer."""

import argparse
import json
from pathlib import Path

from elegant_spline import (
    BSplineCurvatureSmoothingParams,
    FixedKnotSplineFitter,
    PlanarFitOptions,
    export_viewer_document,
)


def make_example() -> dict:
    domain = {
        "outer": [(0, 0), (13, 0), (16, 2), (16, 9), (14, 10), (2, 10), (0, 8)],
        "holes": [[(5, 4), (6.2, 2.4), (8.6, 2.2), (10.3, 3.5),
                   (10.5, 5.5), (9.1, 6.8), (6.7, 6.6), (5, 5.4)]],
        "clearance": 0.45,
    }
    points = [
        (1.0, 2.0), (2.3, 2.7), (3.5, 4.6), (3.5, 4.6), (3.6, 4.8),
        (4.6, 7.1), (6.8, 8.2), (8.7, 7.8), (10.1, 7.15),
        (11.6, 6.2), (12.2, 4.45), (13.4, 3.3), (15.0, 3.7),
    ]
    options = PlanarFitOptions(
        resample_spacing=0.55,
        merge_diameter=0.3,
        fairing=BSplineCurvatureSmoothingParams(lambda_curvature=0.01, fidelity_scale=0.2),
    )
    result = FixedKnotSplineFitter(knot_spacing=2.5, options=options).fit(points)
    if result.status != "fitted":
        raise RuntimeError(f"Example fit failed: {result.report.solver_reason}")
    return export_viewer_document(points, result, domain=domain, unit="m")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", nargs="?", type=Path,
        default=Path(__file__).resolve().parents[1] / "web/spline-viewer/example.json",
    )
    output = parser.parse_args().output
    serialized = json.dumps(make_example(), allow_nan=False, indent=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized + "\n", encoding="utf-8")
    print(output)
