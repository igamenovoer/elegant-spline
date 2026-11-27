"""Export recorded planar fits for the standalone browser viewer."""

from collections.abc import Sequence
from math import isfinite
from numbers import Real
from typing import NotRequired, TypedDict

import numpy as np
from numpy.typing import ArrayLike
from scipy.interpolate import BSpline

from .distance_fitting import FitResult, _input_points


class ViewerDomain(TypedDict):
    """A polygonal region and its requested clearance, in the input units."""

    outer: ArrayLike
    holes: NotRequired[Sequence[ArrayLike]]
    clearance: NotRequired[float | None]


def _ring(vertices: ArrayLike) -> list[list[float]]:
    points = _input_points(vertices)
    if np.array_equal(points[0], points[-1]):
        points = points[:-1]
    if len(np.unique(points, axis=0)) < 3:
        raise ValueError("a domain ring needs at least three distinct XY vertices")
    return points.tolist()


def _domain_record(domain: ViewerDomain) -> dict:
    clearance = domain.get("clearance")
    if clearance is not None:
        if isinstance(clearance, bool) or not isinstance(clearance, Real):
            raise TypeError("clearance must be a real number")
        clearance = float(clearance)
        if not isfinite(clearance) or clearance < 0:
            raise ValueError("clearance must be finite and nonnegative")
    return {
        "outer": _ring(domain["outer"]),
        "holes": [_ring(hole) for hole in domain.get("holes", ())],
        "clearance": clearance,
    }


def _stage_record(curve: BSpline) -> dict:
    # The planar fitters produce clamped cubics with simple interior knots.
    breaks = np.unique(curve.t[curve.k : len(curve.t) - curve.k])
    anchors = curve(breaks)
    # Differencing coefficients first preserves zero tangents under large translations.
    derivatives = curve.derivative()(breaks)
    widths = np.diff(breaks)[:, None] / 3
    bezier = np.stack(
        (
            anchors[:-1],
            anchors[:-1] + widths * derivatives[:-1],
            anchors[1:] - widths * derivatives[1:],
            anchors[1:],
        ),
        axis=1,
    )
    if not np.isfinite(bezier).all():
        raise ValueError("curve contains unrepresentable Bézier geometry")
    return {
        "controls": curve.c.tolist(),
        "spans": [
            {"a": float(a), "b": float(b), "points": points.tolist()}
            for a, b, points in zip(breaks[:-1], breaks[1:], bezier, strict=True)
        ],
    }


def export_viewer_document(
    points_xy: ArrayLike,
    result: FitResult,
    *,
    domain: ViewerDomain | None = None,
    unit: str | None = None,
) -> dict:
    """Build a JSON-compatible v1 document from a fit and its original inputs.

    Pass the same ordered points used for `fit`. The optional domain and unit
    describe the caller's coordinate system. Serialize the returned mapping
    with `json.dump(document, stream, allow_nan=False)`.
    """
    source = _input_points(points_xy)
    if len(source) != len(result.source_parameters):
        raise ValueError("points_xy length must match the fit's original observation count")
    if unit is not None and not isinstance(unit, str):
        raise TypeError("unit must be a string or None")
    report = result.report
    guide = report.guide
    curves = {
        "initial": result.initial_curve,
        "preFairing": result.pre_fairing_curve,
        "final": result.curve,
    }
    reason = report.recovery_reason or report.solver_reason
    if report.recovery:
        reason = f"{report.recovery} ({reason})" if reason else report.recovery
    return {
        "version": 1,
        "unit": unit,
        "domain": _domain_record(domain) if domain is not None else None,
        "observations": [
            {"xy": xy.tolist(), "u": u}
            for xy, u in zip(source, result.source_parameters, strict=True)
        ],
        "preprocessing": {
            "membership": list(guide.cluster_membership),
            "representatives": [list(point) for point in guide.guide_points],
            "points": [list(point) for point in guide.points],
            "parameters": list(guide.parameters),
        },
        "fit": {
            "method": report.method,
            "status": result.status,
            "reason": reason,
            "stages": {
                name: _stage_record(curve) for name, curve in curves.items() if curve is not None
            },
        },
    }
