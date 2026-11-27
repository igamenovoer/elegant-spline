"""Fit clamped cubic B-splines to ordered planar observations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import MISSING, dataclass, fields
from math import ceil, isfinite
from numbers import Integral, Real
from typing import Literal
import warnings

import numpy as np
from numpy.typing import ArrayLike, NDArray
import scipy
from scipy.interpolate import BSpline, make_lsq_spline, make_smoothing_spline, make_splprep

from .curvature_smoothing import (
    BSplineCurvatureSmoother,
    BSplineCurvatureSmoothingParams,
    SmoothingReport,
)

__all__ = [
    "DistanceFitOptions",
    "DistanceSplineFitter",
    "FitMetrics",
    "FitReport",
    "FitResult",
    "FixedKnotFitDetails",
    "FixedKnotSplineFitter",
    "GuideReport",
    "PlanarFitOptions",
    "SmoothingSplineFitter",
]

FloatArray = NDArray[np.float64]
Point = tuple[float, float]
FitStatus = Literal["fitted", "fallback", "unavailable"]
StageStatus = Literal["completed", "failed", "skipped", "disabled", "unchanged"]
Fallback = Literal["none", "endpoint"]
Recovery = Literal["line", "constant"]
FitMethod = Literal["distance", "smoothing", "fixed-knot"]
_DEFAULT_MAXIMUM_FIT_POINTS = 4096


@dataclass(frozen=True, slots=True)
class PlanarFitOptions:
    """Shared guide preparation and stage controls for a planar cubic fit."""

    resample_spacing: float
    merge_diameter: float = 0.0
    endpoint_weight_multiplier: float = 1.0
    maximum_fit_points: int = _DEFAULT_MAXIMUM_FIT_POINTS
    maximum_fit_attempts: int = 1
    correct_endpoints: bool = True
    fairing: BSplineCurvatureSmoothingParams | None = None
    fallback: Fallback = "none"

    def __post_init__(self) -> None:
        _validate_planar_options(self)


@dataclass(frozen=True, slots=True)
class DistanceFitOptions:
    """Immutable controls for a single residual-budget cubic fit."""

    rms_allowance: float
    resample_spacing: float
    merge_diameter: float = 0.0
    endpoint_weight_multiplier: float = 1.0
    maximum_fit_points: int = _DEFAULT_MAXIMUM_FIT_POINTS
    maximum_fit_attempts: int = 1
    correct_endpoints: bool = True
    fairing: BSplineCurvatureSmoothingParams | None = None
    fallback: Fallback = "none"

    def __post_init__(self) -> None:
        allowance = _finite_setting("rms_allowance", self.rms_allowance)
        object.__setattr__(self, "rms_allowance", allowance)
        _validate_planar_options(self)


def _finite_setting(name: str, value: float, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a finite real number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be a finite real number") from error
    if not isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        bounds = "nonnegative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {bounds}")
    return number


def _validate_planar_options(options: PlanarFitOptions | DistanceFitOptions) -> None:
    for name in ("resample_spacing", "merge_diameter", "endpoint_weight_multiplier"):
        number = _finite_setting(name, getattr(options, name), allow_zero=name == "merge_diameter")
        object.__setattr__(options, name, number)

    for name in ("maximum_fit_points", "maximum_fit_attempts"):
        count = getattr(options, name)
        if isinstance(count, bool) or not isinstance(count, Integral):
            raise TypeError(f"{name} must be an integer")
        object.__setattr__(options, name, int(count))
    if options.maximum_fit_points < 4:
        raise ValueError("maximum_fit_points must be at least four")
    if options.maximum_fit_attempts not in (0, 1):
        raise ValueError("maximum_fit_attempts must be zero or one")
    if not isinstance(options.correct_endpoints, bool):
        raise TypeError("correct_endpoints must be a bool")
    if options.fallback not in ("none", "endpoint"):
        raise ValueError("fallback must be 'none' or 'endpoint'")
    if options.fairing is not None:
        if not isinstance(options.fairing, BSplineCurvatureSmoothingParams):
            raise TypeError("fairing must be BSplineCurvatureSmoothingParams or None")
        if options.fairing.endpoint_policy != "position_and_tangent":
            raise ValueError("integrated fairing requires position_and_tangent preservation")


@dataclass(frozen=True, slots=True)
class GuideReport:
    """Guide preparation and its correspondence to the input observations."""

    cluster_membership: tuple[int, ...]
    cluster_diameters: tuple[float, ...]
    unique_count: int
    guide_points: tuple[Point, ...]
    length: float
    detail_loss: float
    requested_spacing: float
    effective_spacing: float | None
    cap_applied: bool
    points: tuple[Point, ...]
    parameters: tuple[float, ...]
    weights: tuple[float, ...]
    weight_adjustment: str | None


@dataclass(frozen=True, slots=True)
class FitMetrics:
    """Source and weighted guide errors measured on a particular curve."""

    source_rms: float | None
    max_source_error: float | None
    endpoint_errors: Point | None
    weighted_residual_sum: float | None
    weighted_rms: float | None
    budget_met: bool | None
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class FixedKnotFitDetails:
    """Nominal spacing and the corresponding initial solver basis."""

    requested_spacing: float
    requested_span_count: int | None = None
    selected_span_count: int | None = None
    effective_spacing: float | None = None


@dataclass(frozen=True, slots=True)
class FitReport:
    """Auditable evidence for the fitting stages and resulting geometry."""

    guide: GuideReport
    numpy_version: str
    scipy_version: str
    residual_budget: float | None
    solver_attempts: int
    solver_status: StageStatus
    solver_reason: str | None
    solver_warnings: tuple[str, ...]
    correction_status: StageStatus
    correction_reason: str | None
    fairing_status: StageStatus
    fairing_reason: str | None
    fairing_report: SmoothingReport | None
    recovery: Recovery | None
    recovery_reason: str | None
    initial_metrics: FitMetrics | None
    corrected_metrics: FitMetrics | None
    final_metrics: FitMetrics | None
    method: FitMethod = "distance"
    smoothing_strength: float | None = None
    fixed_knot: FixedKnotFitDetails | None = None

    def __setstate__(self, state: list[object]) -> None:
        """Restore defaults for fields added after a report was pickled."""
        for index, field in enumerate(fields(self)):
            value = state[index] if index < len(state) else field.default
            if value is MISSING:
                raise ValueError(f"missing serialized fit report field {field.name!r}")
            object.__setattr__(self, field.name, value)


@dataclass(frozen=True, slots=True)
class FitResult:
    """A fitted curve, an explicit fallback, or an unavailable result."""

    status: FitStatus
    curve: BSpline | None
    source_parameters: tuple[float, ...]
    initial_curve: BSpline | None
    pre_fairing_curve: BSpline | None
    report: FitReport


@dataclass(frozen=True, slots=True)
class _InitialFit:
    solve: Callable[[], BSpline]
    method: FitMethod = "distance"
    minimum_fit_points: int = 4
    residual_budget: float | None = None
    skip_reason: str | None = None
    smoothing_strength: float | None = None
    fixed_knot: FixedKnotFitDetails | None = None


def _input_points(points: ArrayLike) -> FloatArray:
    message = "points must be a nonempty finite array of real coordinate pairs"
    try:
        values = np.asarray(points)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(message) from error
    if values.ndim != 2 or values.shape[1:] != (2,) or not len(values):
        raise ValueError(message)
    if values.dtype.kind == "O":
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in values.flat):
            raise ValueError(message)
    elif values.dtype.kind not in "fiu":
        raise ValueError(message)
    try:
        with np.errstate(over="ignore"):
            result = np.asarray(values, dtype=np.float64)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(message) from error
    if not np.all(np.isfinite(result)):
        raise ValueError(message)
    return result


def _lengths(vectors: FloatArray) -> FloatArray:
    return np.hypot(vectors[..., 0], vectors[..., 1])


def _cumulative_chords(points: FloatArray) -> FloatArray:
    with np.errstate(over="ignore", invalid="ignore"):
        distances = np.r_[0.0, np.cumsum(_lengths(np.diff(points, axis=0)))]
    if not np.all(np.isfinite(distances)):
        raise ValueError("cumulative chord distance is outside the representable coordinate range")
    return distances


def _as_points(points: FloatArray) -> tuple[Point, ...]:
    return tuple((float(x), float(y)) for x, y in points)


def _cluster_guide(source: FloatArray, diameter_limit: float) -> tuple[
    FloatArray, int, tuple[int, ...], tuple[float, ...], float
]:
    # Duplicating a consecutive point leaves the solver's guide unchanged.
    changed = np.r_[True, np.any(source[1:] != source[:-1], axis=1)]
    distinct = source[changed]
    source_to_unique = np.cumsum(changed) - 1
    boundaries = [0]
    diameters: list[float] = []
    diameter = 0.0
    for index in range(1, len(distinct)):
        distances = _lengths(distinct[boundaries[-1] : index] - distinct[index])
        expanded = max(diameter, float(np.max(distances)))
        if expanded > diameter_limit:
            boundaries.append(index)
            diameters.append(diameter)
            diameter = 0.0
        else:
            diameter = expanded
    boundaries.append(len(distinct))
    diameters.append(diameter)

    guide = np.empty((len(diameters), 2), dtype=np.float64)
    detail_loss = 0.0
    for cluster, (first, stop) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        members = distinct[first:stop]
        with np.errstate(over="ignore"):
            representative = np.mean(members, axis=0)
        if not np.all(np.isfinite(representative)):
            # Anchor the mean when summing large same-sign coordinates overflows.
            offsets = (members - members[0]) / len(members)
            representative = members[0] + np.sum(offsets, axis=0)
        guide[cluster] = representative
        detail_loss = max(detail_loss, float(np.max(_lengths(members - representative))))
    membership = np.searchsorted(boundaries[1:], source_to_unique, side="right")
    return guide, len(distinct), tuple(map(int, membership)), tuple(diameters), detail_loss


def _fit_weights(parameters: FloatArray, endpoint_multiplier: float) -> tuple[FloatArray, str | None]:
    # Parameters with a collapsed interval are ineligible for the cubic solver.
    if len(parameters) == 1 or np.any(np.diff(parameters) <= 0):
        return np.ones(len(parameters)), None
    support = np.r_[
        (parameters[1] - parameters[0]) / 2,
        (parameters[2:] - parameters[:-2]) / 2,
        (parameters[-1] - parameters[-2]) / 2,
    ]
    weights = np.sqrt(support)
    with np.errstate(over="ignore", under="ignore"):
        weights[[0, -1]] *= endpoint_multiplier
        square_sum = float(np.sum(weights**2))
    if np.all(weights > 0) and isfinite(square_sum) and square_sum > 0:
        scale = len(weights) / square_sum
        if isfinite(scale) and square_sum >= np.finfo(np.float64).tiny:
            return weights * np.sqrt(scale), None

    # Scale the interval widths before taking logarithms so subnormal widths
    # can be used even when their half-widths round to zero.
    widths = np.r_[
        parameters[1] - parameters[0],
        parameters[2:] - parameters[:-2],
        parameters[-1] - parameters[-2],
    ]
    log_weights = 0.5 * np.log(widths)
    log_weights[[0, -1]] += np.log(endpoint_multiplier)
    with np.errstate(under="ignore"):
        scaled = np.exp(log_weights - np.max(log_weights))
    scaled = np.maximum(scaled, np.nextafter(0.0, 1.0))
    return scaled * np.sqrt(len(scaled) / np.sum(scaled**2)), "log_normalization"


def _prepare_guide(source: FloatArray, options: PlanarFitOptions | DistanceFitOptions) -> GuideReport:
    guide, unique_count, membership, diameters, detail_loss = _cluster_guide(
        source, options.merge_diameter
    )
    distances = _cumulative_chords(guide)
    length = float(distances[-1])
    spacing: float | None = None
    cap_applied = False
    if length > 0:
        spacing = options.resample_spacing
        cap_applied = length / spacing > options.maximum_fit_points - 1
        if cap_applied:
            locations = np.linspace(0.0, length, options.maximum_fit_points)
            spacing = length / (options.maximum_fit_points - 1)
        else:
            locations = np.arange(0.0, length, spacing)
            locations = np.r_[locations[locations < length], length]
            if len(locations) > options.maximum_fit_points:
                cap_applied = True
                locations = np.linspace(0.0, length, options.maximum_fit_points)
                spacing = length / (options.maximum_fit_points - 1)
        fit_points = np.column_stack(
            [np.interp(locations, distances, guide[:, axis]) for axis in range(2)]
        )
        fit_points[[0, -1]] = guide[[0, -1]]
        parameters = locations / length
    else:
        fit_points = guide[:1]
        parameters = np.zeros(1)
    weights, adjustment = _fit_weights(parameters, options.endpoint_weight_multiplier)
    return GuideReport(
        cluster_membership=membership,
        cluster_diameters=diameters,
        unique_count=unique_count,
        guide_points=_as_points(guide),
        length=length,
        detail_loss=detail_loss,
        requested_spacing=options.resample_spacing,
        effective_spacing=spacing,
        cap_applied=cap_applied,
        points=_as_points(fit_points),
        parameters=tuple(map(float, parameters)),
        weights=tuple(map(float, weights)),
        weight_adjustment=adjustment,
    )


def _validate_curve(curve: BSpline) -> None:
    knots, controls = curve.t, curve.c
    if (
        curve.k != 3
        or curve.axis != 0
        or curve.extrapolate is not False
        or controls.shape != (len(knots) - 4, 2)
        or not np.all(np.isfinite(knots))
        or not np.all(np.isfinite(controls))
        or not np.all(knots[:4] == 0)
        or not np.all(knots[-4:] == 1)
    ):
        raise ValueError("invalid clamped cubic coefficients")
    interior = knots[4:-4]
    if np.any((interior <= 0) | (interior >= 1)) or np.any(np.diff(interior) <= 0):
        raise ValueError("the cubic must have simple interior knots strictly inside [0, 1]")
    probes = np.unique(np.r_[np.linspace(0.0, 1.0, 33), interior])
    with np.errstate(over="ignore", under="ignore", invalid="ignore", divide="ignore"):
        for order in range(3):
            derivative = curve.derivative(order)
            if not np.all(np.isfinite(derivative(probes))):
                raise ValueError("nonfinite cubic evaluation")
            left = derivative(np.nextafter(interior, 0.0))
            right = derivative(np.nextafter(interior, 1.0))
            if not np.all(np.isfinite(left)) or not np.all(np.isfinite(right)):
                raise ValueError("nonfinite one-sided cubic evaluation")
            scale = np.maximum(1.0, np.maximum(_lengths(left), _lengths(right)))
            if np.any(_lengths(left - right) > 1e-7 * scale):
                raise ValueError("the cubic failed numerical C2 verification")


def _fit_cubic(guide: GuideReport, budget: float) -> BSpline:
    points = np.asarray(guide.points)
    parameters = np.asarray(guide.parameters)
    curve, _ = make_splprep(points.T, u=parameters, k=3, w=np.asarray(guide.weights), s=budget)
    # SciPy stores canonical coefficients even for coordinate-first evaluation.
    cubic = BSpline(curve.t, curve.c, curve.k, extrapolate=False, axis=0)
    probes = np.linspace(0.0, 1.0, 9)
    expected = np.moveaxis(curve(probes), curve.axis, 0)
    if not np.allclose(cubic(probes), expected, rtol=1e-12, atol=1e-12):
        raise ValueError("normalizing the coordinate axis changed the fitted curve")
    return cubic


def _fit_smoothing_spline(guide: GuideReport, smoothing_strength: float) -> BSpline:
    with np.errstate(under="ignore"):
        squared_weights = np.square(guide.weights)
    if np.any(squared_weights <= 0.0):
        raise ValueError("squared guide weights must remain positive")

    parameters = np.asarray(guide.parameters)
    points = np.asarray(guide.points)
    # SciPy 1.15 accepts scalar ordinates only. An explicit strength gives both axes one basis.
    with np.errstate(divide="raise", over="raise", invalid="raise"):
        x_curve, y_curve = (
            make_smoothing_spline(parameters, ordinates, w=squared_weights, lam=smoothing_strength)
            for ordinates in points.T
        )
    if not np.array_equal(x_curve.t, y_curve.t):
        raise ValueError("the coordinate smoothing splines have different knots")
    controls = np.column_stack((x_curve.c, y_curve.c))
    cubic = BSpline(x_curve.t, controls, 3, extrapolate=False)
    if smoothing_strength == 0.0 and not np.allclose(
        cubic(parameters), points, rtol=1e-9, atol=1e-12
    ):
        raise ValueError("the zero-strength spline failed guide interpolation verification")
    return cubic


def _fit_fixed_knot_spline(guide: GuideReport, span_count: int) -> BSpline:
    knots = np.r_[np.zeros(4), np.arange(1, span_count) / span_count, np.ones(4)]
    curve = make_lsq_spline(
        guide.parameters, guide.points, knots, k=3, w=guide.weights, method="qr"
    )
    return BSpline(curve.t, curve.c, curve.k, extrapolate=False)


def _correct_endpoints(curve: BSpline, endpoints: FloatArray) -> BSpline:
    greville = np.asarray([np.mean(curve.t[i + 1 : i + 4]) for i in range(len(curve.c))])
    offsets = endpoints - curve([0.0, 1.0])
    controls = curve.c + (1 - greville[:, None]) * offsets[0] + greville[:, None] * offsets[1]
    controls[[0, -1]] = endpoints
    candidate = BSpline(curve.t.copy(), controls, 3, extrapolate=False)
    _validate_curve(candidate)
    if np.any(_lengths(candidate([0.0, 1.0]) - endpoints) > 1e-9):
        raise ValueError("the corrected curve failed endpoint verification")
    return candidate


def _recover(endpoints: FloatArray) -> BSpline:
    start, end = endpoints
    fractions = np.array([0.0, 1 / 3, 2 / 3, 1.0])[:, None]
    controls = start + fractions * (end - start)
    controls[[0, -1]] = endpoints
    candidate = BSpline([0.0] * 4 + [1.0] * 4, controls, 3, extrapolate=False)
    _validate_curve(candidate)
    return candidate


def _verify_faired(candidate: BSpline, reference: BSpline) -> None:
    _validate_curve(candidate)
    if not np.array_equal(candidate.t, reference.t):
        raise ValueError("fairing changed the knots")
    for order in (0, 1):
        expected = reference([0.0, 1.0], nu=order)
        actual = candidate([0.0, 1.0], nu=order)
        tolerance = 1e-8 * max(1.0, float(np.max(_lengths(expected))))
        if np.any(_lengths(actual - expected) > tolerance):
            raise ValueError("fairing changed a required endpoint value or tangent")


def _measure(
    curve: BSpline,
    source: FloatArray,
    source_parameters: FloatArray,
    guide: GuideReport,
    budget: float | None,
) -> FitMetrics:
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        source_errors = _lengths(curve(source_parameters) - source)
        endpoints = _lengths(curve([0.0, 1.0]) - source[[0, -1]])
        guide_errors = curve(np.asarray(guide.parameters)) - guide.points
        weights = np.asarray(guide.weights)
        total = float(np.sum((weights[:, None] * guide_errors)**2))
        square_sum = float(np.sum(weights**2))
    reasons = []
    if np.all(np.isfinite(source_errors)):
        maximum = float(np.max(source_errors))
        source_rms = (
            maximum * float(np.sqrt(np.mean((source_errors / maximum) ** 2)))
            if maximum else 0.0
        )
    else:
        maximum = source_rms = None
        reasons.append("source errors exceed finite arithmetic")
    endpoint_errors = (
        (float(endpoints[0]), float(endpoints[1])) if np.all(np.isfinite(endpoints)) else None
    )
    if endpoint_errors is None:
        reasons.append("endpoint errors exceed finite arithmetic")
    if isfinite(total) and isfinite(square_sum) and square_sum > 0:
        weighted_rms = float(np.sqrt(total / square_sum))
        residual = total
        budget_met = total <= budget if budget is not None else None
    else:
        reasons.append("weighted guide residual exceeds finite arithmetic")
        weighted_rms = residual = budget_met = None
    return FitMetrics(
        source_rms=source_rms,
        max_source_error=maximum,
        endpoint_errors=endpoint_errors,
        weighted_residual_sum=residual,
        weighted_rms=weighted_rms,
        budget_met=budget_met,
        unavailable_reason=", ".join(reasons) or None,
    )


def _failure(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def _prepare_distance_fit(guide: GuideReport, rms_allowance: float) -> _InitialFit:
    requested_budget = len(guide.points) * rms_allowance * rms_allowance
    finite_budget = isfinite(requested_budget)
    return _InitialFit(
        solve=lambda: _fit_cubic(guide, requested_budget),
        residual_budget=requested_budget if finite_budget else None,
        skip_reason=None if finite_budget else "residual_budget_outside_finite_arithmetic",
    )


def _prepare_smoothing_fit(guide: GuideReport, smoothing_strength: float) -> _InitialFit:
    return _InitialFit(
        solve=lambda: _fit_smoothing_spline(guide, smoothing_strength),
        method="smoothing",
        minimum_fit_points=5,
        smoothing_strength=smoothing_strength,
    )


def _prepare_fixed_knot_fit(guide: GuideReport, knot_spacing: float) -> _InitialFit:
    span_cap = len(guide.points) - 3
    span_ratio = guide.length / knot_spacing
    requested_spans = max(1, ceil(span_ratio)) if isfinite(span_ratio) else None
    selected_spans = min(requested_spans or span_cap, span_cap)
    details = FixedKnotFitDetails(
        requested_spacing=knot_spacing,
        requested_span_count=requested_spans,
        selected_span_count=selected_spans if selected_spans > 0 else None,
        effective_spacing=guide.length / selected_spans if selected_spans > 0 else None,
    )
    return _InitialFit(
        solve=lambda: _fit_fixed_knot_spline(guide, selected_spans),
        method="fixed-knot",
        fixed_knot=details,
    )


class DistanceSplineFitter:
    """Reusable planar fitter with isolated state for each call."""

    def __init__(self, options: DistanceFitOptions) -> None:
        if not isinstance(options, DistanceFitOptions):
            raise TypeError("options must be DistanceFitOptions")
        self._options = options

    @property
    def options(self) -> DistanceFitOptions:
        return self._options

    def fit(self, points_xy: ArrayLike) -> FitResult:
        """Fit ordered observations and report the curve retained at each stage."""
        return _fit_planar(
            points_xy,
            self._options,
            lambda guide: _prepare_distance_fit(guide, self._options.rms_allowance),
        )


class SmoothingSplineFitter:
    """Fit a planar cubic with a penalty on coordinate second derivatives."""

    def __init__(self, *, smoothing_strength: float, options: PlanarFitOptions) -> None:
        if not isinstance(options, PlanarFitOptions):
            raise TypeError("options must be PlanarFitOptions")
        self._options = options
        self._smoothing_strength = _finite_setting(
            "smoothing_strength", smoothing_strength, allow_zero=True
        )

    @property
    def options(self) -> PlanarFitOptions:
        return self._options

    def fit(self, points_xy: ArrayLike) -> FitResult:
        """Fit ordered observations and report the curve retained at each stage."""
        return _fit_planar(
            points_xy,
            self._options,
            lambda guide: _prepare_smoothing_fit(guide, self._smoothing_strength),
        )


class FixedKnotSplineFitter:
    """Fit a planar cubic on a knot basis sized by nominal guide spacing."""

    def __init__(self, *, knot_spacing: float, options: PlanarFitOptions) -> None:
        if not isinstance(options, PlanarFitOptions):
            raise TypeError("options must be PlanarFitOptions")
        self._options = options
        self._knot_spacing = _finite_setting("knot_spacing", knot_spacing)

    @property
    def options(self) -> PlanarFitOptions:
        return self._options

    def fit(self, points_xy: ArrayLike) -> FitResult:
        """Fit ordered observations and report the curve retained at each stage."""
        return _fit_planar(
            points_xy,
            self._options,
            lambda guide: _prepare_fixed_knot_fit(guide, self._knot_spacing),
        )


def _fit_planar(
    points_xy: ArrayLike,
    options: PlanarFitOptions | DistanceFitOptions,
    prepare_initial_fit: Callable[[GuideReport], _InitialFit],
) -> FitResult:
    source = _input_points(points_xy)
    distances = _cumulative_chords(source)
    source_parameters = distances / distances[-1] if distances[-1] else distances
    guide = _prepare_guide(source, options)
    fit = prepare_initial_fit(guide)
    budget = fit.residual_budget

    initial = None
    solver_attempts = 0
    solver_status: StageStatus = "skipped"
    solver_reason = None
    solver_warnings = ()
    if fit.skip_reason is not None:
        solver_reason = fit.skip_reason
    elif guide.unique_count < 4 or len(guide.parameters) < fit.minimum_fit_points:
        solver_reason = "insufficient_observations"
    elif any(b <= a for a, b in zip(guide.parameters, guide.parameters[1:])):
        solver_reason = "fit_parameters_are_not_strictly_increasing"
    elif options.maximum_fit_attempts == 0:
        solver_reason = "attempt_budget_exhausted"
    else:
        solver_attempts = 1
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            try:
                candidate = fit.solve()
                _validate_curve(candidate)
                initial = candidate
                solver_status = "completed"
            except Exception as error:
                solver_status = "failed"
                solver_reason = _failure(error)
        solver_warnings = tuple(
            f"{item.category.__name__}: {item.message}" for item in recorded
        )

    endpoints = source[[0, -1]]
    selected = initial
    corrected = None
    correction_status: StageStatus = "skipped" if options.correct_endpoints else "disabled"
    correction_reason = None
    if selected is not None and options.correct_endpoints:
        try:
            corrected = _correct_endpoints(selected, endpoints)
            selected = corrected
            correction_status = "completed"
        except Exception as error:
            correction_status = "failed"
            correction_reason = _failure(error)

    pre_fairing = None
    fairing_status: StageStatus = "skipped" if options.fairing else "disabled"
    fairing_reason = None
    fairing_report = None
    if selected is not None and options.fairing is not None:
        pre_fairing = selected
        try:
            result = BSplineCurvatureSmoother(options.fairing).smooth_with_report(
                selected, points=guide.points, parameters=guide.parameters
            )
            fairing_report = result.report
            if fairing_report.outcome == "completed":
                _verify_faired(result.spline, selected)
                selected = result.spline
                fairing_status = "completed"
            elif fairing_report.outcome == "unchanged":
                fairing_status = "unchanged"
            else:
                fairing_status = "failed"
            fairing_reason = fairing_report.reason
        except Exception as error:
            fairing_status = "failed"
            fairing_reason = _failure(error)

    status: FitStatus = "fitted" if selected is not None else "unavailable"
    recovery: Recovery | None = None
    recovery_reason = None
    if selected is None and options.fallback == "endpoint":
        try:
            selected = _recover(endpoints)
            recovery = "constant" if np.array_equal(endpoints[0], endpoints[1]) else "line"
            status = "fallback"
        except Exception as error:
            recovery_reason = _failure(error)

    initial_metrics = (
        _measure(initial, source, source_parameters, guide, budget)
        if initial is not None else None
    )
    corrected_metrics = (
        _measure(corrected, source, source_parameters, guide, budget)
        if corrected is not None else None
    )
    if selected is initial:
        final_metrics = initial_metrics
    elif selected is corrected:
        final_metrics = corrected_metrics
    else:
        final_metrics = _measure(selected, source, source_parameters, guide, budget)

    fixed_knot = fit.fixed_knot
    if fixed_knot is not None and solver_attempts == 0:
        fixed_knot = FixedKnotFitDetails(requested_spacing=fixed_knot.requested_spacing)

    return FitResult(
        status=status,
        curve=selected,
        source_parameters=tuple(map(float, source_parameters)),
        initial_curve=initial,
        pre_fairing_curve=pre_fairing,
        report=FitReport(
            guide=guide,
            numpy_version=np.__version__,
            scipy_version=scipy.__version__,
            residual_budget=budget,
            solver_attempts=solver_attempts,
            solver_status=solver_status,
            solver_reason=solver_reason,
            solver_warnings=solver_warnings,
            correction_status=correction_status,
            correction_reason=correction_reason,
            fairing_status=fairing_status,
            fairing_reason=fairing_reason,
            fairing_report=fairing_report,
            recovery=recovery,
            recovery_reason=recovery_reason,
            initial_metrics=initial_metrics,
            corrected_metrics=corrected_metrics,
            final_metrics=final_metrics,
            method=fit.method,
            smoothing_strength=fit.smoothing_strength,
            fixed_knot=fixed_knot,
        ),
    )
