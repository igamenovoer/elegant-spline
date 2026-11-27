"""Fixed-knot B-spline geometric-curvature smoothing.

This module provides a reusable, project-independent smoother that reduces the
geometric curvature of an existing SciPy :class:`~scipy.interpolate.BSpline`
while keeping its knots, degree, parameter domain, evaluation-axis layout, and
nonperiodic extrapolation setting fixed. Only control values change.

The objective combines three soft terms.

- The fidelity term uses original-arc-length-weighted squared displacement from the
  input curve, or normalized weighted squared error against caller-supplied
  observations at fixed parameters.
- The bending term integrates region-weighted squared geometric curvature over
  candidate arc length and scales it by the original curve length.
- The outside term uses squared displacement from the original curve outside the
  affected regions, integrated against original arc length.

The report records the measured fidelity and curvature tradeoffs of the
verified candidate. Application-specific error, turning-radius, and topology
requirements need their own checks.

Error conventions
-----------------

- :class:`TypeError` marks wrong types: non-numeric parameter values, booleans
  anywhere a number is expected, non-``int`` count fields (integral floats are
  rejected), non-string enum fields, non-``BSpline`` splines, non-sequence
  regions, and non-numeric observation arrays.
- :class:`ValueError` marks right types with unusable values: nonfinite
  numbers, out-of-range values, unknown enum strings, inconsistent settings
  (``region_mode="auto"`` without a threshold), shape mismatches,
  out-of-domain observation parameters, and unsupported spline conditions
  (scalar-valued, tensor batch, periodic extrapolation, degree below three,
  knot structures incompatible with C2 continuity or finite derivative
  controls).

Outcome taxonomy
----------------

- ``"completed"``: a candidate was produced and passed independent numerical
  verification (reasons: ``"solver_complete"``,
  ``"zero_strength_reused_initialization"``).
- ``"unchanged"``: a benign no-op retained the input curve (reasons:
  ``"no_regions"``, ``"no_free_controls"``, ``"zero_length_curve"``,
  ``"zero_strength_without_observations"``).
- ``"failed"``: numerical failure or incomplete work retained the input curve
  (reasons: ``"initialization_failed"``, ``"optimization_failed"``,
  ``"verification_failed"``, ``"basis_parity_failed"``,
  ``"numerical_failure"``).

Imports are restricted to the standard library, NumPy, and SciPy. Importing
this module has no operational effects.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields, is_dataclass
from numbers import Integral, Real
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.interpolate import BSpline  # type: ignore[import-untyped]
from scipy.linalg import null_space  # type: ignore[import-untyped]
from scipy.optimize import least_squares, minimize_scalar  # type: ignore[import-untyped]
from scipy.sparse import diags  # type: ignore[import-untyped]

__all__ = [
    "BSplineCurvatureSmoother",
    "BSplineCurvatureSmoothingParams",
    "BSplineSmoothingError",
    "BSplineSmoothingResult",
    "Measurement",
    "MeasurementSet",
    "SmoothingReport",
    "SolveRecord",
]

# Versioned sampling policy (version 1). These grid sizes cap the numerical
# work per call; they are deterministic and reported, not adaptive.
_DETECTION_BASE_PROBES = 16385  # uniform probes for detection/length audit
_SPAN_PROBES_PER_SPAN = 65  # extra probes per nonzero knot span during detection
_OBJECTIVE_BASE_PROBES = 2049  # uniform probes for the optimizer quadrature grid
_VERIFICATION_COARSE_PROBES = 16385  # coarse independent verification grid
_VERIFICATION_FINE_PROBES = 32769  # fine independent verification grid
_REFINEMENT_BRACKET_PROBES = 33  # resampling probes per refined extremum bracket
_REFINEMENT_MAX_PEAKS = 12  # strongest sampled curvature peaks refined
_REFINEMENT_MAX_SLOW = 12  # slowest sampled tangents refined

_CONVERGENCE_RELATIVE_TOLERANCE = 0.01  # coarse/fine agreement for curvature/bending
# Basis/direct-evaluation parity: the sparse difference composition accumulates
# cancellation noise proportional to the summed term magnitude, not to the result
# magnitude, so the per-element tolerance is the floating-point term-magnitude
# bound ``_BASIS_PARITY_SAFETY * eps * (|B| @ |c|)``, floored at
# ``_BASIS_PARITY_ATOL``, plus a relative backstop on the direct value. Genuine
# convention errors (wrong knots, axis mixups, endpoint handling) are O(result
# scale) and exceed the term-magnitude bound by orders of magnitude.
_BASIS_PARITY_SAFETY = 64.0
_BASIS_PARITY_RTOL = 1e-10
_BASIS_PARITY_ATOL = 1e-12
_ENDPOINT_RELATIVE_TOLERANCE = 1e-8  # endpoint value/derivative preservation gate
_SPEED_FLOOR_RELATIVE = 1e-8  # eps = _SPEED_FLOOR_RELATIVE * max(L0, 1) / domain width

_OUTCOME_COMPLETED = "completed"
_OUTCOME_UNCHANGED = "unchanged"
_OUTCOME_FAILED = "failed"

_REFERENCE_ORIGINAL_CURVE = "original-curve"
_REFERENCE_OBSERVATIONS = "observations"

_FloatArray = NDArray[np.float64]
_IndexArray = NDArray[np.int64]

_REGION_MODES = ("all", "auto")
_ENDPOINT_POLICIES = ("free", "position", "position_and_tangent")
_INITIALIZATIONS = ("original", "fidelity")

_MACHINE_EPSILON = float(np.finfo(np.float64).eps)


class _NonfiniteResidualsError(Exception):
    """Raised when a trial residual vector contains nonfinite values."""


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


def _require_real(
    name: str,
    value: object,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    inclusive: bool = True,
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None:
        if inclusive and result < minimum:
            raise ValueError(f"{name} must be >= {minimum}, got {result}")
        if not inclusive and result <= minimum:
            raise ValueError(f"{name} must be > {minimum}, got {result}")
    if maximum is not None:
        if inclusive and result > maximum:
            raise ValueError(f"{name} must be <= {maximum}, got {result}")
        if not inclusive and result >= maximum:
            raise ValueError(f"{name} must be < {maximum}, got {result}")
    return result


def _require_optional_real(
    name: str,
    value: object,
    *,
    minimum: float | None = None,
    inclusive: bool = True,
) -> float | None:
    if value is None:
        return None
    return _require_real(name, value, minimum=minimum, inclusive=inclusive)


def _require_count(name: str, value: object, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer, got {type(value).__name__}")
    result = int(value)
    if result < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {result}")
    return result


def _require_enum(name: str, value: object, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, got {type(value).__name__}")
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class BSplineCurvatureSmoothingParams:
    """Immutable algorithm parameters for :class:`BSplineCurvatureSmoother`.

    Real-valued fields accept ordinary Python ``int`` values and normalize them
    to ``float`` so ``dataclasses.asdict`` output is canonical. Count fields
    (``padding_spans``, ``transition_spans``, ``max_nfev``) require actual
    integers: floats (even integral ones) and booleans are rejected. Booleans
    are rejected anywhere a number is expected. ``curvature_threshold`` and
    ``outside_scale`` are nullable; an explicit ``None`` keeps its documented
    resolution semantics through JSON round trips.
    """

    lambda_curvature: float
    fidelity_scale: float
    region_mode: str = "all"
    curvature_threshold: float | None = None
    padding_spans: int = 2
    transition_spans: int = 1
    outside_scale: float | None = None
    outside_weight: float = 50.0
    endpoint_policy: str = "position_and_tangent"
    initialization: str = "fidelity"
    max_nfev: int = 600
    ftol: float = 1e-9
    xtol: float = 1e-9
    gtol: float = 1e-9

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "lambda_curvature",
            _require_real("lambda_curvature", self.lambda_curvature, minimum=0.0),
        )
        object.__setattr__(
            self,
            "fidelity_scale",
            _require_real("fidelity_scale", self.fidelity_scale, minimum=0.0, inclusive=False),
        )
        object.__setattr__(
            self, "region_mode", _require_enum("region_mode", self.region_mode, _REGION_MODES)
        )
        object.__setattr__(
            self,
            "curvature_threshold",
            _require_optional_real(
                "curvature_threshold", self.curvature_threshold, minimum=0.0, inclusive=False
            ),
        )
        object.__setattr__(
            self, "padding_spans", _require_count("padding_spans", self.padding_spans, minimum=0)
        )
        object.__setattr__(
            self,
            "transition_spans",
            _require_count("transition_spans", self.transition_spans, minimum=0),
        )
        object.__setattr__(
            self,
            "outside_scale",
            _require_optional_real(
                "outside_scale", self.outside_scale, minimum=0.0, inclusive=False
            ),
        )
        object.__setattr__(
            self,
            "outside_weight",
            _require_real("outside_weight", self.outside_weight, minimum=0.0),
        )
        object.__setattr__(
            self,
            "endpoint_policy",
            _require_enum("endpoint_policy", self.endpoint_policy, _ENDPOINT_POLICIES),
        )
        object.__setattr__(
            self,
            "initialization",
            _require_enum("initialization", self.initialization, _INITIALIZATIONS),
        )
        object.__setattr__(self, "max_nfev", _require_count("max_nfev", self.max_nfev, minimum=1))
        for name in ("ftol", "xtol", "gtol"):
            object.__setattr__(
                self,
                name,
                _require_real(name, getattr(self, name), minimum=_MACHINE_EPSILON, inclusive=False),
            )
        if self.region_mode == "auto" and self.curvature_threshold is None:
            raise ValueError("curvature_threshold is required when region_mode='auto'")


# ---------------------------------------------------------------------------
# Report records
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("report contains a nonfinite value")
        return value
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    raise TypeError(f"unsupported report value type: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class Measurement:
    """A finite measured value, or ``None`` with a machine-readable reason."""

    value: float | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class BeforeAfterMeasurement:
    """Before/after pair of :class:`Measurement` records."""

    before: Measurement
    after: Measurement


@dataclass(frozen=True, slots=True)
class MeasurementSet:
    """Before/after geometric measurements of the original and candidate curves."""

    length: BeforeAfterMeasurement
    reference_error: BeforeAfterMeasurement
    bending_energy: BeforeAfterMeasurement
    peak_curvature: BeforeAfterMeasurement
    peak_curvature_parameter: BeforeAfterMeasurement
    minimum_radius: BeforeAfterMeasurement
    minimum_tangent_norm: BeforeAfterMeasurement
    minimum_tangent_parameter: BeforeAfterMeasurement


@dataclass(frozen=True, slots=True)
class SolveRecord:
    """Termination and work record for one least-squares solve."""

    kind: str
    performed: bool
    success: bool | None = None
    status: int | None = None
    message: str | None = None
    nfev: int | None = None
    njev: int | None = None
    optimality: float | None = None
    cost: float | None = None
    residual_calls: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    """Cosine transition bands attached to one expanded region edge."""

    left: tuple[float, float] | None
    right: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class RegionRecord:
    """Selected, expanded, transition, free-control, and strict-outside detail."""

    selected: list[tuple[float, float]]
    expanded: list[tuple[float, float]]
    transitions: list[TransitionRecord]
    free_control_indices: list[int]
    free_support_union: list[tuple[float, float]]
    strict_outside: list[tuple[float, float]]
    strict_outside_arc_length: Measurement
    strict_outside_arc_fraction: Measurement


@dataclass(frozen=True, slots=True)
class DetectionRecord:
    """Threshold-detection audit record (``region_mode="auto"`` only)."""

    performed: bool
    reason: str | None
    probe_count: int | None
    refinement_probe_count: int | None
    refinement_success_count: int | None
    baseline_peak_curvature: Measurement
    baseline_min_speed: Measurement
    speed_floor_probe_count: int | None


@dataclass(frozen=True, slots=True)
class EndpointRecord:
    """Endpoint value/first-derivative preservation record."""

    policy: str
    checked: bool
    value_change_max: Measurement
    first_derivative_change_max: Measurement
    tolerance: float | None


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    """Independent verification record for the accepted candidate."""

    performed: bool
    reason: str | None
    coarse_grid_size: int | None
    fine_grid_size: int | None
    refinement_probe_count: int | None
    refinement_success_count: int | None
    knots_preserved: bool | None
    degree_preserved: bool | None
    frozen_controls_preserved: bool | None
    endpoints_preserved: bool | None
    regularity_ok: bool | None
    curvature_converged: bool | None
    bending_converged: bool | None
    unresolved_reasons: list[str]


@dataclass(frozen=True, slots=True)
class SmoothingReport:
    """Typed, JSON-safe smoothing report."""

    outcome: str
    reason: str
    fidelity_reference: str
    parameters: dict[str, Any]
    original_length: float
    speed_floor: float
    initialization: SolveRecord
    main_solve: SolveRecord
    measurements: MeasurementSet
    endpoints: EndpointRecord
    regions: RegionRecord
    outside_max_displacement: Measurement
    detection: DetectionRecord
    verification: VerificationRecord

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary containing only finite values or nulls."""
        result = _jsonable(self)
        if not isinstance(result, dict):  # pragma: no cover - defensive
            raise TypeError("report serialization produced a non-dictionary")
        return result


class BSplineSmoothingError(Exception):
    """Numerical smoothing failure carrying the full :class:`SmoothingReport`."""

    def __init__(self, message: str, report: SmoothingReport) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True, slots=True)
class BSplineSmoothingResult:
    """Detailed smoothing outcome.

    ``spline`` is always a distinct object: the smoothed curve on
    ``"completed"``, a retained copy of the input on ``"unchanged"`` and
    ``"failed"``. ``attempted_spline`` exposes the finite, evaluable attempted
    candidate on failures when one exists, else ``None``.
    """

    spline: BSpline
    report: SmoothingReport
    attempted_spline: BSpline | None


# ---------------------------------------------------------------------------
# Input validation and normalization
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SplineInfo:
    t: _FloatArray  # copy of the full knot vector
    k: int
    n: int  # active control count: len(t) - k - 1
    u0: float
    u1: float
    axis: int
    extrapolate: bool
    dim: int
    coefficients: _FloatArray  # point-first copy, shape (n_total, dim)
    active: _FloatArray  # view of the first n rows of ``coefficients``
    trailing: _FloatArray  # inactive trailing coefficients, shape (n_total - n, dim)
    clamped: bool


@dataclass(frozen=True, slots=True)
class _Observations:
    points: _FloatArray  # (N, dim) copy
    parameters: _FloatArray  # (N,) copy
    weights: _FloatArray  # (N,) copy


def _validate_spline(spline: object) -> _SplineInfo:
    if not isinstance(spline, BSpline):
        raise TypeError(f"spline must be a scipy.interpolate.BSpline, got {type(spline).__name__}")
    if np.iscomplexobj(spline.t) or np.iscomplexobj(spline.c):
        raise ValueError("spline knots and coefficients must be real-valued")
    t = np.array(spline.t, dtype=np.float64, copy=True)
    k = int(spline.k)
    if k < 3:
        raise ValueError(f"spline degree must be at least 3, got {k}")
    n = len(t) - k - 1
    if n < 1:
        raise ValueError("spline must define at least one active control")
    if not np.all(np.isfinite(t)):
        raise ValueError("spline knots must be finite")
    if np.any(np.diff(t) < 0):
        raise ValueError("spline knots must be nondecreasing")
    u0, u1 = float(t[k]), float(t[n])
    if not u0 < u1:
        raise ValueError(
            f"spline base domain [t[k], t[n]] must have positive length, got [{u0}, {u1}]"
        )
    if spline.extrapolate == "periodic":
        raise ValueError("periodic extrapolation is not supported")
    interior = t[(t > u0) & (t < u1)]
    if len(interior):
        _, counts = np.unique(interior, return_counts=True)
        if np.any(counts > k - 2):
            raise ValueError(
                "interior knot multiplicity exceeds k-2; C2 continuity cannot be preserved"
            )
    den1 = t[k + 1 : -1] - t[1 : -(k + 1)]
    if not np.all(den1 > 0):
        raise ValueError(
            "knot structure does not define finite first-derivative controls "
            "(zero derivative denominator)"
        )
    d1_t = t[1:-1]
    den2 = d1_t[k:-1] - d1_t[1:-k]
    if not np.all(den2 > 0):
        raise ValueError(
            "knot structure does not define finite second-derivative controls "
            "(zero derivative denominator)"
        )
    # SciPy stores coefficients point-first internally regardless of the user's
    # evaluation axis; ``spline.axis`` only records the evaluation layout.
    point_first = np.array(spline.c, dtype=np.float64, copy=True)
    axis = int(spline.axis)
    if point_first.ndim == 1:
        raise ValueError(
            "scalar-valued splines are not supported; a coordinate dimension is required"
        )
    if point_first.ndim != 2:
        raise ValueError(
            f"tensor-batch spline coefficients are not supported; got {point_first.ndim} dimensions"
        )
    n_total, dim = point_first.shape
    if n_total < n:
        raise ValueError("spline must supply at least len(t) - k - 1 coefficients")
    if dim < 2:
        raise ValueError(f"spline must be vector-valued with at least 2 coordinates, got {dim}")
    if not np.all(np.isfinite(point_first)):
        raise ValueError("spline coefficients must be finite")
    clamped = bool(np.all(t[: k + 1] == u0) and np.all(t[n:] == u1))
    return _SplineInfo(
        t=t,
        k=k,
        n=n,
        u0=u0,
        u1=u1,
        axis=axis,
        extrapolate=bool(spline.extrapolate),
        dim=dim,
        coefficients=point_first,
        active=point_first[:n],
        trailing=point_first[n:],
        clamped=clamped,
    )


def _as_numeric_array(name: str, value: object) -> _FloatArray:
    try:
        array = np.asarray(value)
        if np.iscomplexobj(array):
            raise TypeError("complex values are not supported")
        return np.array(array, dtype=np.float64, copy=True)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a rectangular real numeric array") from exc


def _validate_observations(
    info: _SplineInfo,
    points: object,
    parameters: object,
    weights: object,
) -> _Observations | None:
    if points is None and parameters is None:
        if weights is not None:
            raise ValueError("weights require observations (points and parameters)")
        return None
    if points is None or parameters is None:
        raise ValueError("points and parameters must be supplied together")
    pts = _as_numeric_array("points", points)
    params = _as_numeric_array("parameters", parameters)
    if pts.ndim != 2 or pts.shape[1] != info.dim:
        raise ValueError(f"points must have shape (N, {info.dim}), got {pts.shape}")
    if params.ndim != 1 or params.shape[0] != pts.shape[0]:
        raise ValueError("parameters must have shape (N,) matching points")
    if pts.shape[0] == 0:
        raise ValueError("observations must be nonempty")
    if not np.all(np.isfinite(pts)):
        raise ValueError("points must be finite")
    if not np.all(np.isfinite(params)):
        raise ValueError("parameters must be finite")
    if np.any(np.diff(params) < 0):
        raise ValueError("parameters must be nondecreasing")
    if np.any((params < info.u0) | (params > info.u1)):
        raise ValueError("parameters must lie inside the spline base domain")
    if weights is None:
        w = np.ones(pts.shape[0], dtype=np.float64)
    else:
        w = _as_numeric_array("weights", weights)
        if w.ndim != 1 or w.shape[0] != pts.shape[0]:
            raise ValueError("weights must have shape (N,) matching points")
        if not np.all(np.isfinite(w)):
            raise ValueError("weights must be finite")
        if np.any(w <= 0):
            raise ValueError("weights must be positive")
    return _Observations(points=pts, parameters=params, weights=w)


def _region_endpoint(name: str, value: object, u0: float, u1: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if result < u0 or result > u1:
        raise ValueError(f"{name} must lie inside the base domain [{u0}, {u1}], got {result}")
    return result


def _validate_regions(regions: object, u0: float, u1: float) -> list[tuple[float, float]] | None:
    if regions is None:
        return None
    if isinstance(regions, (str, bytes)):
        raise TypeError("regions must be a sequence of (a, b) numeric intervals")
    try:
        items = list(regions)  # type: ignore[call-overload]
    except TypeError as exc:
        raise TypeError("regions must be a sequence of (a, b) numeric intervals") from exc
    pairs: list[tuple[float, float]] = []
    for item in items:
        if isinstance(item, (str, bytes)):
            raise TypeError("regions must contain (a, b) numeric pairs")
        try:
            a_raw, b_raw = item
        except (TypeError, ValueError) as exc:
            raise TypeError("regions must contain (a, b) numeric pairs") from exc
        a = _region_endpoint("region start", a_raw, u0, u1)
        b = _region_endpoint("region end", b_raw, u0, u1)
        if a > b:
            raise ValueError(f"region start must not exceed region end, got [{a}, {b}]")
        pairs.append((a, b))
    return _merge_intervals(pairs)


def _merge_intervals(intervals: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(float(a), float(b)) for a, b in merged]


# ---------------------------------------------------------------------------
# Numerical helpers
# ---------------------------------------------------------------------------


def _trapezoid_weights(u: _FloatArray) -> _FloatArray:
    q = np.empty_like(u)
    q[0] = (u[1] - u[0]) / 2
    q[-1] = (u[-1] - u[-2]) / 2
    q[1:-1] = (u[2:] - u[:-2]) / 2
    return q


def _wedge_components(d1: _FloatArray, d2: _FloatArray) -> _FloatArray:
    """Return the wedge-product components ``C'_i*C''_j - C'_j*C''_i`` (i < j).

    In 2D this is exactly the signed planar cross product (one component). In
    higher dimensions the squared component norm equals
    ``kappa^2 * speed^6``, so no Gram-determinant square root is needed.
    """
    ii, jj = np.triu_indices(d1.shape[1], k=1)
    return d1[:, ii] * d2[:, jj] - d1[:, jj] * d2[:, ii]


def _speed_and_curvature(
    curve: BSpline, u: _FloatArray, eps: float
) -> tuple[_FloatArray, _FloatArray]:
    d1 = np.asarray(curve(u, nu=1), dtype=np.float64)
    d2 = np.asarray(curve(u, nu=2), dtype=np.float64)
    speed = np.linalg.norm(d1, axis=1)
    wedge = _wedge_components(d1, d2)
    kappa = np.sqrt(np.sum(wedge * wedge, axis=1)) / np.maximum(speed, eps) ** 3
    return speed, kappa


def _derivative_matrices(t: _FloatArray, k: int) -> tuple[Any, Any]:
    """Sparse difference-scaling matrices for first/second derivative controls."""
    n = len(t) - k - 1
    den1 = t[k + 1 : -1] - t[1 : -(k + 1)]
    e1 = diags([-k / den1, k / den1], offsets=[0, 1], shape=(n - 1, n), format="csr")
    d1_t = t[1:-1]
    den2 = d1_t[k:-1] - d1_t[1:-k]
    e2 = diags(
        [-(k - 1) / den2, (k - 1) / den2], offsets=[0, 1], shape=(n - 2, n - 1), format="csr"
    )
    return e1, e2


def _basis_matrices(t: _FloatArray, k: int, u: _FloatArray) -> tuple[Any, Any, Any]:
    """Sparse position/first-/second-derivative basis matrices on ``u``."""
    e1, e2 = _derivative_matrices(t, k)
    b0 = BSpline.design_matrix(u, t, k, extrapolate=False)
    b1 = BSpline.design_matrix(u, t[1:-1], k - 1, extrapolate=False) @ e1
    b2 = BSpline.design_matrix(u, t[2:-2], k - 2, extrapolate=False) @ (e2 @ e1)
    return b0, b1, b2


def _basis_parity_ok(
    basis: Any, controls: _FloatArray, computed: _FloatArray, direct: _FloatArray
) -> bool:
    """Check basis-matrix evaluation against direct spline evaluation.

    The tolerance is the floating-point term-magnitude bound
    ``_BASIS_PARITY_SAFETY * eps * (|B| @ |c|)`` per element (cancellation noise
    inside the sparse difference composition scales with the summed term size,
    not the result), floored at ``_BASIS_PARITY_ATOL``, plus a relative backstop
    on the direct value.
    """
    term_bound = np.abs(basis) @ np.abs(controls)
    tolerance = np.maximum(
        _BASIS_PARITY_ATOL, _BASIS_PARITY_SAFETY * _MACHINE_EPSILON * term_bound
    ) + _BASIS_PARITY_RTOL * np.abs(direct)
    return bool(np.all(np.abs(computed - direct) <= tolerance))


def _region_weight(
    u: _FloatArray,
    expanded: Sequence[tuple[float, float]],
    transitions: Sequence[TransitionRecord],
) -> _FloatArray:
    """Frozen cosine mask: 1 inside expanded cores with cosine transition bands."""
    values = np.asarray(u, dtype=np.float64)
    weights = np.zeros_like(values)
    for (a, b), transition in zip(expanded, transitions, strict=True):
        local = np.zeros_like(values)
        local[(values >= a) & (values <= b)] = 1.0
        if transition.left is not None:
            l0, l1 = transition.left
            if l1 > l0:
                where = (values > l0) & (values < l1)
                local[where] = 0.5 * (1 - np.cos(np.pi * (values[where] - l0) / (l1 - l0)))
        if transition.right is not None:
            r0, r1 = transition.right
            if r1 > r0:
                where = (values > r0) & (values < r1)
                local[where] = 0.5 * (1 + np.cos(np.pi * (values[where] - r0) / (r1 - r0)))
        weights = np.maximum(weights, local)
    return weights


def _refine_extrema(
    curve: BSpline,
    probes: _FloatArray,
    kappa: _FloatArray,
    speed: _FloatArray,
    eps: float,
) -> tuple[_FloatArray, int]:
    """Refine the strongest sampled curvature peaks and slowest sampled tangents.

    Each selected local extremum is refined with ``minimize_scalar`` (bounded
    method) on its sample bracket; successful refinements contribute the
    33-probe bracket resampling and the refined parameter itself.
    """
    peak_ids = np.flatnonzero((kappa[1:-1] >= kappa[:-2]) & (kappa[1:-1] >= kappa[2:])) + 1
    slow_ids = np.flatnonzero((speed[1:-1] <= speed[:-2]) & (speed[1:-1] <= speed[2:])) + 1
    if len(peak_ids):
        peak_ids = peak_ids[np.argsort(kappa[peak_ids])[-_REFINEMENT_MAX_PEAKS:]]
    if len(slow_ids):
        slow_ids = slow_ids[np.argsort(speed[slow_ids])[:_REFINEMENT_MAX_SLOW]]
    refinements: list[float] = []
    success_count = 0
    for index in np.unique(np.concatenate((peak_ids, slow_ids))):
        a, b = float(probes[index - 1]), float(probes[index + 1])
        if index in slow_ids:

            def objective(x: float) -> float:
                probe = np.asarray([x], dtype=np.float64)
                return float(_speed_and_curvature(curve, probe, eps)[0][0])

        else:

            def objective(x: float) -> float:
                probe = np.asarray([x], dtype=np.float64)
                return -float(_speed_and_curvature(curve, probe, eps)[1][0])

        refined = minimize_scalar(objective, bounds=(a, b), method="bounded")
        if refined.success:
            success_count += 1
            refinements.extend(np.linspace(a, b, _REFINEMENT_BRACKET_PROBES).tolist())
            refinements.append(float(refined.x))
    return np.asarray(refinements, dtype=np.float64), success_count


def _detect_regions(
    curve: BSpline,
    breaks: _FloatArray,
    eps: float,
    threshold: float,
) -> tuple[list[tuple[float, float]], _FloatArray, dict[str, Any]]:
    """Detect contiguous bad runs: curvature above threshold or near-singular speed."""
    uniform = np.linspace(breaks[0], breaks[-1], _DETECTION_BASE_PROBES)
    span_probes = [
        np.linspace(a, b, _SPAN_PROBES_PER_SPAN)
        for a, b in zip(breaks[:-1], breaks[1:], strict=True)
    ]
    probes = np.unique(np.concatenate((uniform, breaks, *span_probes)))
    speed, kappa = _speed_and_curvature(curve, probes, eps)
    refined_probes, refinement_successes = _refine_extrema(curve, probes, kappa, speed, eps)
    if len(refined_probes):
        probes = np.unique(np.concatenate((probes, refined_probes)))
        speed, kappa = _speed_and_curvature(curve, probes, eps)
    bad = (kappa > threshold) | (speed <= eps)
    starts = np.flatnonzero(bad & ~np.r_[False, bad[:-1]])
    ends = np.flatnonzero(bad & ~np.r_[bad[1:], False])
    intervals: list[tuple[float, float]] = []
    for first, last in zip(starts, ends, strict=True):
        a = probes[first] if first == 0 else (probes[first - 1] + probes[first]) / 2
        b = probes[last] if last == len(probes) - 1 else (probes[last] + probes[last + 1]) / 2
        intervals.append((float(a), float(b)))
    stats: dict[str, Any] = {
        "probe_count": int(len(probes)),
        "refinement_probe_count": int(len(refined_probes)),
        "refinement_success_count": int(refinement_successes),
        "baseline_peak_curvature": float(np.max(kappa)),
        "baseline_min_speed": float(np.min(speed)),
        "speed_floor_probe_count": int(np.count_nonzero(speed <= eps)),
    }
    return _merge_intervals(intervals), refined_probes, stats


def _expand_regions(
    breaks: _FloatArray,
    selected: Sequence[tuple[float, float]],
    padding_spans: int,
    transition_spans: int,
) -> tuple[list[tuple[float, float]], list[TransitionRecord]]:
    """Pad selected intervals by whole nonzero spans and attach cosine transitions."""
    span_count = len(breaks) - 1
    cores_raw: list[tuple[float, float]] = []
    for a, b in selected:
        left_span = int(np.clip(np.searchsorted(breaks, a, side="right") - 1, 0, span_count - 1))
        right_span = int(np.clip(np.searchsorted(breaks, b, side="left") - 1, 0, span_count - 1))
        cores_raw.append(
            (
                float(breaks[max(0, left_span - padding_spans)]),
                float(breaks[min(span_count, right_span + 1 + padding_spans)]),
            )
        )
    cores = _merge_intervals(cores_raw)
    transitions: list[TransitionRecord] = []
    for a, b in cores:
        ia = int(np.searchsorted(breaks, a))
        ib = int(np.searchsorted(breaks, b))
        left = (float(breaks[max(0, ia - transition_spans)]), a) if ia > 0 else None
        right = (
            (b, float(breaks[min(span_count, ib + transition_spans)])) if ib < span_count else None
        )
        transitions.append(TransitionRecord(left=left, right=right))
    return cores, transitions


def _support_scopes(
    expanded: Sequence[tuple[float, float]],
    transitions: Sequence[TransitionRecord],
) -> list[tuple[float, float]]:
    return [
        (
            a if transition.left is None else transition.left[0],
            b if transition.right is None else transition.right[1],
        )
        for (a, b), transition in zip(expanded, transitions, strict=True)
    ]


def _strict_outside(
    support_regions: Sequence[tuple[float, float]], u0: float, u1: float
) -> list[tuple[float, float]]:
    strict: list[tuple[float, float]] = []
    cursor = u0
    for a, b in support_regions:
        if a > cursor:
            strict.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < u1:
        strict.append((cursor, u1))
    if not support_regions:
        strict = [(u0, u1)]
    return strict


def _curve_measurements(
    curve: BSpline,
    reference: BSpline,
    grid: _FloatArray,
    refined: _FloatArray,
    eps: float,
    original_length: float,
    observations: _Observations | None,
) -> dict[str, float | None]:
    """Measure one curve on the union of the verification grid and refined probes."""
    parts = [grid, refined] if len(refined) else [grid]
    u = np.unique(np.concatenate(parts))
    positions = np.asarray(curve(u), dtype=np.float64)
    d1 = np.asarray(curve(u, nu=1), dtype=np.float64)
    d2 = np.asarray(curve(u, nu=2), dtype=np.float64)
    speed = np.linalg.norm(d1, axis=1)
    q = _trapezoid_weights(u)
    wedge = _wedge_components(d1, d2)
    kappa = np.sqrt(np.sum(wedge * wedge, axis=1)) / np.maximum(speed, eps) ** 3
    length = float(np.sum(q * speed))
    bending = float(original_length * np.sum(q * kappa**2 * np.maximum(speed, eps)))
    peak_index = int(np.argmax(kappa))
    peak = float(kappa[peak_index])
    slow_index = int(np.argmin(speed))
    if observations is not None:
        obs_positions = np.asarray(curve(observations.parameters), dtype=np.float64)
        squared = np.sum((obs_positions - observations.points) ** 2, axis=1)
        reference_error = float(
            np.sqrt(np.sum(observations.weights * squared) / np.sum(observations.weights))
        )
    else:
        reference_positions = np.asarray(reference(u), dtype=np.float64)
        reference_speed = np.linalg.norm(np.asarray(reference(u, nu=1), dtype=np.float64), axis=1)
        displacement2 = np.sum((positions - reference_positions) ** 2, axis=1)
        reference_error = float(
            np.sqrt(np.sum(q * displacement2 * reference_speed) / original_length)
        )
    return {
        "length": length,
        "reference_error": reference_error,
        "bending_energy": bending,
        "peak_curvature": peak,
        "peak_curvature_parameter": float(u[peak_index]),
        "minimum_radius": (1.0 / peak) if peak > 0 else None,
        "minimum_tangent_norm": float(speed[slow_index]),
        "minimum_tangent_parameter": float(u[slow_index]),
    }


def _measurement_set(
    before: dict[str, float | None],
    after: dict[str, float | None] | None,
    after_reason: str | None,
    zero_length: bool = False,
) -> MeasurementSet:
    def pair(name: str, curvature_dependent: bool = False) -> BeforeAfterMeasurement:
        before_value = before.get(name)
        before_reason: str | None = None
        if curvature_dependent and zero_length:
            before_value = None
            before_reason = "zero_length_curve"
        if after is None:
            return BeforeAfterMeasurement(
                Measurement(before_value, before_reason), Measurement(None, after_reason)
            )
        return BeforeAfterMeasurement(
            Measurement(before_value, before_reason), Measurement(after.get(name), None)
        )

    return MeasurementSet(
        length=pair("length"),
        reference_error=pair("reference_error"),
        bending_energy=pair("bending_energy", curvature_dependent=True),
        peak_curvature=pair("peak_curvature", curvature_dependent=True),
        peak_curvature_parameter=pair("peak_curvature_parameter", curvature_dependent=True),
        minimum_radius=pair("minimum_radius", curvature_dependent=True),
        minimum_tangent_norm=pair("minimum_tangent_norm"),
        minimum_tangent_parameter=pair("minimum_tangent_parameter"),
    )


# ---------------------------------------------------------------------------
# Smoother
# ---------------------------------------------------------------------------


class BSplineCurvatureSmoother:
    """Reusable fixed-knot curvature smoother.

    The instance stores only the immutable parameter dataclass; calls keep all
    state local, so identical calls reproduce identical results.
    """

    def __init__(self, params: BSplineCurvatureSmoothingParams) -> None:
        if not isinstance(params, BSplineCurvatureSmoothingParams):
            raise TypeError(
                f"params must be a BSplineCurvatureSmoothingParams, got {type(params).__name__}"
            )
        self._params = params

    @property
    def params(self) -> BSplineCurvatureSmoothingParams:
        return self._params

    def smooth(
        self,
        spline: BSpline,
        points: ArrayLike | None = None,
        parameters: ArrayLike | None = None,
        weights: ArrayLike | None = None,
        regions: Sequence[tuple[float, float]] | None = None,
    ) -> BSpline:
        """Return the smoothed spline, raising on numerical failure.

        On ``"completed"`` and ``"unchanged"`` outcomes the resulting spline is
        returned; on ``"failed"`` a :class:`BSplineSmoothingError` carrying the
        report is raised. Malformed arguments raise :class:`TypeError` or
        :class:`ValueError` before any numerical work.
        """
        result = self.smooth_with_report(spline, points, parameters, weights, regions)
        if result.report.outcome == _OUTCOME_FAILED:
            raise BSplineSmoothingError(
                f"B-spline curvature smoothing failed: {result.report.reason}", result.report
            )
        return result.spline

    def smooth_with_report(
        self,
        spline: BSpline,
        points: ArrayLike | None = None,
        parameters: ArrayLike | None = None,
        weights: ArrayLike | None = None,
        regions: Sequence[tuple[float, float]] | None = None,
    ) -> BSplineSmoothingResult:
        """Run one smoothing call and return the detailed result record."""
        return _smooth_impl(self._params, spline, points, parameters, weights, regions)


def _effective_parameters(params: BSplineCurvatureSmoothingParams) -> dict[str, Any]:
    effective = asdict(params)
    effective["outside_scale"] = (
        params.fidelity_scale if params.outside_scale is None else params.outside_scale
    )
    return effective


def _not_performed_solve(kind: str, reason: str) -> SolveRecord:
    return SolveRecord(kind=kind, performed=False, reason=reason)


def _solve(
    kind: str,
    residual: Any,
    x0: _FloatArray,
    params: BSplineCurvatureSmoothingParams,
) -> tuple[SolveRecord, _FloatArray | None]:
    """Run one bounded least-squares solve with an own residual-call counter."""
    calls = 0

    def counted(x: _FloatArray) -> _FloatArray:
        nonlocal calls
        calls += 1
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            values = np.asarray(residual(x), dtype=np.float64)
        if not np.all(np.isfinite(values)):
            raise _NonfiniteResidualsError(f"{kind} residuals became nonfinite")
        return values

    try:
        result = least_squares(
            counted,
            x0,
            method="trf",
            loss="linear",
            jac="2-point",
            x_scale="jac",
            ftol=params.ftol,
            xtol=params.xtol,
            gtol=params.gtol,
            max_nfev=params.max_nfev,
        )
    except Exception as exc:  # noqa: BLE001 - solver failures become failed outcomes
        return (
            SolveRecord(
                kind=kind,
                performed=True,
                success=False,
                message=f"{type(exc).__name__}: {exc}",
                residual_calls=calls,
                reason="solver_exception",
            ),
            None,
        )
    record = SolveRecord(
        kind=kind,
        performed=True,
        success=bool(result.success),
        status=int(result.status),
        message=str(result.message),
        nfev=int(result.nfev),
        njev=int(result.njev) if result.njev is not None else None,
        optimality=float(result.optimality),
        cost=float(result.cost),
        residual_calls=calls,
    )
    if not result.success or int(result.status) <= 0:
        record = SolveRecord(
            kind=kind,
            performed=True,
            success=False,
            status=int(result.status),
            message=str(result.message),
            nfev=int(result.nfev),
            njev=int(result.njev) if result.njev is not None else None,
            optimality=float(result.optimality),
            cost=float(result.cost),
            residual_calls=calls,
            reason="solver_incomplete",
        )
    return record, np.asarray(result.x, dtype=np.float64)


def _smooth_impl(
    params: BSplineCurvatureSmoothingParams,
    spline: BSpline,
    points: object,
    parameters: object,
    weights: object,
    regions: object,
) -> BSplineSmoothingResult:
    info = _validate_spline(spline)
    observations = _validate_observations(info, points, parameters, weights)
    explicit_regions = _validate_regions(regions, info.u0, info.u1)
    reference_kind = (
        _REFERENCE_OBSERVATIONS if observations is not None else _REFERENCE_ORIGINAL_CURVE
    )
    effective = _effective_parameters(params)
    outside_scale = effective["outside_scale"]

    t, k, n, u0, u1 = info.t, info.k, info.n, info.u0, info.u1
    c0 = np.array(info.active, dtype=np.float64, copy=True)
    original = BSpline(t, info.coefficients, k, axis=0, extrapolate=False)
    breaks = np.unique(t[k : n + 1])

    def retained_copy() -> BSpline:
        return _build_output_spline(info, info.active)

    def finish(
        outcome: str,
        reason: str,
        *,
        detection: DetectionRecord,
        regions_record: RegionRecord,
        initialization: SolveRecord,
        main_solve: SolveRecord,
        measurements: MeasurementSet,
        endpoints: EndpointRecord,
        outside: Measurement,
        verification: VerificationRecord,
        candidate: BSpline | None,
        original_length: float,
        speed_floor: float,
    ) -> BSplineSmoothingResult:
        report = SmoothingReport(
            outcome=outcome,
            reason=reason,
            fidelity_reference=reference_kind,
            parameters=effective,
            original_length=original_length,
            speed_floor=speed_floor,
            initialization=initialization,
            main_solve=main_solve,
            measurements=measurements,
            endpoints=endpoints,
            regions=regions_record,
            outside_max_displacement=outside,
            detection=detection,
            verification=verification,
        )
        if outcome == _OUTCOME_COMPLETED:
            assert candidate is not None
            return BSplineSmoothingResult(spline=candidate, report=report, attempted_spline=None)
        return BSplineSmoothingResult(
            spline=retained_copy(), report=report, attempted_spline=candidate
        )

    # Original length on the detection grid, frozen for the whole call.
    length_grid = np.unique(np.concatenate((np.linspace(u0, u1, _DETECTION_BASE_PROBES), breaks)))
    length_speed = np.linalg.norm(np.asarray(original(length_grid, nu=1), dtype=np.float64), axis=1)
    original_length = float(np.sum(_trapezoid_weights(length_grid) * length_speed))
    eps = _SPEED_FLOOR_RELATIVE * max(original_length, 1.0) / (u1 - u0)
    fine_grid = np.unique(np.concatenate((np.linspace(u0, u1, _VERIFICATION_FINE_PROBES), breaks)))
    no_refinement = np.empty(0, dtype=np.float64)

    def empty_regions() -> RegionRecord:
        strict = [(u0, u1)]
        return RegionRecord(
            selected=[],
            expanded=[],
            transitions=[],
            free_control_indices=[],
            free_support_union=[],
            strict_outside=strict,
            strict_outside_arc_length=Measurement(original_length),
            strict_outside_arc_fraction=Measurement(1.0 if original_length > 0 else None),
        )

    def unchanged_result(
        reason: str,
        *,
        detection: DetectionRecord,
        regions_record: RegionRecord,
        zero_length: bool = False,
    ) -> BSplineSmoothingResult:
        before = (
            {
                "length": 0.0,
                "reference_error": _constant_reference_error(observations, info),
                "bending_energy": None,
                "peak_curvature": None,
                "peak_curvature_parameter": None,
                "minimum_radius": None,
                "minimum_tangent_norm": 0.0,
                "minimum_tangent_parameter": u0,
            }
            if zero_length
            else _curve_measurements(
                original, original, fine_grid, no_refinement, eps, original_length, observations
            )
        )
        measurements = _measurement_set(before, None, "unchanged_outcome", zero_length=zero_length)
        endpoints = _endpoint_record(
            original, original, params.endpoint_policy, measured=True, reason=None
        )
        return finish(
            _OUTCOME_UNCHANGED,
            reason,
            detection=detection,
            regions_record=regions_record,
            initialization=_not_performed_solve("initialization", reason),
            main_solve=_not_performed_solve("main", reason),
            measurements=measurements,
            endpoints=endpoints,
            outside=Measurement(None, "unchanged_outcome"),
            verification=VerificationRecord(
                performed=False,
                reason="unchanged_outcome",
                coarse_grid_size=None,
                fine_grid_size=None,
                refinement_probe_count=None,
                refinement_success_count=None,
                knots_preserved=None,
                degree_preserved=None,
                frozen_controls_preserved=None,
                endpoints_preserved=None,
                regularity_ok=None,
                curvature_converged=None,
                bending_converged=None,
                unresolved_reasons=[],
            ),
            candidate=None,
            original_length=original_length,
            speed_floor=eps,
        )

    # Constant (zero-length) curves are benign unchanged outcomes.
    if bool(np.all(c0 == c0[0])) or original_length <= 0.0:
        return unchanged_result(
            "zero_length_curve",
            detection=_detection_record(False, "zero_length_curve"),
            regions_record=empty_regions(),
            zero_length=True,
        )
    # Without observations, zero strength leaves the input curve as the exact
    # minimizer of the reference term: a documented no-solve no-op.
    if observations is None and params.lambda_curvature == 0.0:
        return unchanged_result(
            "zero_strength_without_observations",
            detection=_detection_record(False, "zero_strength_without_observations"),
            regions_record=empty_regions(),
        )

    # Region selection.
    refined_probes = no_refinement
    if explicit_regions is not None:
        selected = explicit_regions
        detection = _detection_record(False, "explicit_regions")
    elif params.region_mode == "all":
        selected = [(u0, u1)]
        detection = _detection_record(False, "region_mode_all")
    else:
        assert params.curvature_threshold is not None
        selected, refined_probes, stats = _detect_regions(
            original, breaks, eps, params.curvature_threshold
        )
        detection = DetectionRecord(
            performed=True,
            reason=None,
            probe_count=stats["probe_count"],
            refinement_probe_count=stats["refinement_probe_count"],
            refinement_success_count=stats["refinement_success_count"],
            baseline_peak_curvature=Measurement(stats["baseline_peak_curvature"]),
            baseline_min_speed=Measurement(stats["baseline_min_speed"]),
            speed_floor_probe_count=stats["speed_floor_probe_count"],
        )
    if not selected:
        return unchanged_result("no_regions", detection=detection, regions_record=empty_regions())

    expanded, transitions = _expand_regions(
        breaks, selected, params.padding_spans, params.transition_spans
    )

    # Objective quadrature grid: base probes, knots, refinement probes, and all
    # expanded/transition interval endpoints.
    grid_parts: list[_FloatArray] = [np.linspace(u0, u1, _OBJECTIVE_BASE_PROBES), breaks]
    if len(refined_probes):
        grid_parts.append(refined_probes)
    for a, b in expanded:
        grid_parts.append(np.asarray([a, b], dtype=np.float64))
    for transition in transitions:
        if transition.left is not None:
            grid_parts.append(np.asarray(transition.left, dtype=np.float64))
        if transition.right is not None:
            grid_parts.append(np.asarray(transition.right, dtype=np.float64))
    grid = np.unique(np.concatenate(grid_parts))
    q = _trapezoid_weights(grid)

    # Precomputed sparse basis evaluations with direct-evaluation parity gates.
    try:
        b0, b1, b2 = _basis_matrices(t, k, grid)
        if not _basis_parity_ok(b0, c0, np.asarray(b0 @ c0), np.asarray(original(grid))):
            raise _BasisParityError("position basis does not reproduce the original curve")
        if not _basis_parity_ok(b1, c0, np.asarray(b1 @ c0), np.asarray(original(grid, nu=1))):
            raise _BasisParityError("first-derivative basis does not reproduce the original curve")
        if not _basis_parity_ok(b2, c0, np.asarray(b2 @ c0), np.asarray(original(grid, nu=2))):
            raise _BasisParityError("second-derivative basis does not reproduce the original curve")
    except _BasisParityError as exc:
        return _failed_result(
            "basis_parity_failed",
            message=str(exc),
            detection=detection,
            selected=selected,
            expanded=expanded,
            transitions=transitions,
            decision_indices=np.empty(0, dtype=np.int64),
            original_length=original_length,
            eps=eps,
            params=params,
            observations=observations,
            info=info,
            original=original,
            fine_grid=fine_grid,
            length_grid=length_grid,
            length_speed=length_speed,
        )

    mask = _region_weight(grid, expanded, transitions)
    original_grid = np.asarray(b0 @ c0, dtype=np.float64)
    original_speed_grid = np.linalg.norm(np.asarray(b1 @ c0, dtype=np.float64), axis=1)

    # Free controls: support overlap with the expanded/transition union, then
    # endpoint constraints.
    support_regions = _merge_intervals(_support_scopes(expanded, transitions))
    eligible = np.zeros(n, dtype=bool)
    for index in range(n):
        support_a, support_b = float(t[index]), float(t[index + k + 1])
        for scope_a, scope_b in support_regions:
            if support_b > scope_a and support_a < scope_b:
                eligible[index] = True
                break

    decision_indices: _IndexArray
    null_basis: _FloatArray | None = None
    if info.clamped and params.endpoint_policy != "free":
        pinned = {0, n - 1}
        if params.endpoint_policy == "position_and_tangent":
            pinned.update({1, n - 2})
        free_mask = eligible.copy()
        for index in pinned:
            free_mask[index] = False
        decision_indices = np.flatnonzero(free_mask).astype(np.int64, copy=False)
    elif params.endpoint_policy == "free" or info.clamped:
        decision_indices = np.flatnonzero(eligible).astype(np.int64, copy=False)
    else:
        eligible_indices = np.flatnonzero(eligible).astype(np.int64, copy=False)
        if not len(eligible_indices):
            decision_indices = eligible_indices
        else:
            ends = np.asarray([u0, u1], dtype=np.float64)
            e1, _ = _derivative_matrices(t, k)
            value_rows = np.asarray(
                BSpline.design_matrix(ends, t, k, extrapolate=False).toarray(),
                dtype=np.float64,
            )
            deriv_rows = np.asarray(
                (BSpline.design_matrix(ends, t[1:-1], k - 1, extrapolate=False) @ e1).toarray(),
                dtype=np.float64,
            )
            rows = [value_rows[0], value_rows[1]]
            if params.endpoint_policy == "position_and_tangent":
                rows = [value_rows[0], deriv_rows[0], value_rows[1], deriv_rows[1]]
            constraint = np.stack(rows)[:, eligible_indices]
            null_basis = np.asarray(null_space(constraint), dtype=np.float64)
            decision_indices = eligible_indices
    if not len(decision_indices) or (null_basis is not None and null_basis.shape[1] == 0):
        regions_record = _regions_record(
            selected,
            expanded,
            transitions,
            decision_indices,
            t,
            k,
            support_regions,
            u0,
            u1,
            length_grid,
            length_speed,
            original_length,
        )
        return unchanged_result(
            "no_free_controls", detection=detection, regions_record=regions_record
        )

    def pack(controls: _FloatArray) -> _FloatArray:
        if null_basis is not None:
            delta = controls[decision_indices] - c0[decision_indices]
            return np.linalg.lstsq(null_basis, delta, rcond=None)[0].ravel()
        return controls[decision_indices].ravel()

    def unpack(x: _FloatArray) -> _FloatArray:
        controls = c0.copy()
        if null_basis is not None:
            z = x.reshape(null_basis.shape[1], info.dim)
            controls[decision_indices] = c0[decision_indices] + null_basis @ z
        else:
            controls[decision_indices] = x.reshape(len(decision_indices), info.dim)
        return controls

    # Precomputed residual weights.
    fidelity_scale = params.fidelity_scale
    if observations is not None:
        b_data = BSpline.design_matrix(observations.parameters, t, k, extrapolate=False)
        if not _basis_parity_ok(
            b_data, c0, np.asarray(b_data @ c0), np.asarray(original(observations.parameters))
        ):
            return _failed_result(
                "basis_parity_failed",
                message="observation basis does not reproduce the original curve",
                detection=detection,
                selected=selected,
                expanded=expanded,
                transitions=transitions,
                decision_indices=decision_indices,
                original_length=original_length,
                eps=eps,
                params=params,
                observations=observations,
                info=info,
                original=original,
                fine_grid=fine_grid,
                length_grid=length_grid,
                length_speed=length_speed,
            )
        fit_weight = np.sqrt(
            observations.weights / (np.sum(observations.weights) * fidelity_scale**2)
        )
        reference_weight = None
    else:
        b_data = None
        fit_weight = None
        reference_weight = np.sqrt(q * original_speed_grid / (original_length * fidelity_scale**2))
    outside_weight = params.outside_weight
    outside_residual_weight = (
        np.sqrt(
            outside_weight
            * q
            * (1 - mask)
            * original_speed_grid
            / (original_length * outside_scale**2)
        )
        if outside_weight > 0.0
        else None
    )
    ii, jj = np.triu_indices(info.dim, k=1)

    def residual(x: _FloatArray, strength: float) -> _FloatArray:
        controls = unpack(x)
        parts: list[_FloatArray] = []
        if observations is not None:
            assert b_data is not None and fit_weight is not None
            parts.append(
                (
                    fit_weight[:, None] * (np.asarray(b_data @ controls) - observations.points)
                ).ravel()
            )
        else:
            assert reference_weight is not None
            parts.append(
                (reference_weight[:, None] * (np.asarray(b0 @ controls) - original_grid)).ravel()
            )
        if strength > 0.0:
            d1 = np.asarray(b1 @ controls, dtype=np.float64)
            d2 = np.asarray(b2 @ controls, dtype=np.float64)
            speed = np.linalg.norm(d1, axis=1)
            wedge = d1[:, ii] * d2[:, jj] - d1[:, jj] * d2[:, ii]
            scale = np.sqrt(strength * original_length * q * mask * np.maximum(speed, eps))
            parts.append((scale[:, None] * (wedge / np.maximum(speed, eps)[:, None] ** 3)).ravel())
        if outside_residual_weight is not None:
            parts.append(
                (
                    outside_residual_weight[:, None] * (np.asarray(b0 @ controls) - original_grid)
                ).ravel()
            )
        return np.concatenate(parts)

    # Initialization: one preliminary zero-curvature solve only with observations.
    initialization = _not_performed_solve("initialization", "original_start")
    start = pack(c0)
    if params.initialization == "fidelity" and observations is not None:
        initialization, init_x = _solve(
            "initialization", lambda x: residual(x, 0.0), pack(c0), params
        )
        if not initialization.success or init_x is None:
            return _failed_result(
                "initialization_failed",
                message=initialization.message or "initialization solve failed",
                detection=detection,
                selected=selected,
                expanded=expanded,
                transitions=transitions,
                decision_indices=decision_indices,
                original_length=original_length,
                eps=eps,
                params=params,
                observations=observations,
                info=info,
                original=original,
                fine_grid=fine_grid,
                length_grid=length_grid,
                length_speed=length_speed,
                initialization=initialization,
            )
        start = init_x
    elif params.initialization == "fidelity":
        initialization = _not_performed_solve("initialization", "curve_reference_zero_error_start")

    # Main solve at the requested strength.
    candidate_controls: _FloatArray | None = None
    if params.lambda_curvature == 0.0 and initialization.performed:
        main_solve = _not_performed_solve("main", "zero_strength_reused_initialization")
        candidate_controls = unpack(start)
    else:
        main_solve, main_x = _solve(
            "main", lambda x: residual(x, params.lambda_curvature), start, params
        )
        if not main_solve.success or main_x is None:
            attempted = None
            if main_x is not None:
                attempted_controls = unpack(main_x)
                if np.all(np.isfinite(attempted_controls)):
                    attempted = _build_output_spline(info, attempted_controls)
            return _failed_result(
                "optimization_failed",
                message=main_solve.message or "main optimization failed",
                detection=detection,
                selected=selected,
                expanded=expanded,
                transitions=transitions,
                decision_indices=decision_indices,
                original_length=original_length,
                eps=eps,
                params=params,
                observations=observations,
                info=info,
                original=original,
                fine_grid=fine_grid,
                length_grid=length_grid,
                length_speed=length_speed,
                initialization=initialization,
                main_solve=main_solve,
                attempted=attempted,
            )
        candidate_controls = unpack(main_x)
    assert candidate_controls is not None
    candidate = BSpline(t, candidate_controls, k, axis=0, extrapolate=False)
    attempted_spline = _build_output_spline(info, candidate_controls)

    # Independent verification and before/after measurement.
    verification, after, unresolved = _verify_candidate(
        original,
        candidate,
        info,
        c0,
        decision_indices,
        params,
        eps,
        original_length,
        breaks,
        fine_grid,
        observations,
    )
    before = _curve_measurements(
        original, original, fine_grid, no_refinement, eps, original_length, observations
    )
    regions_record = _regions_record(
        selected,
        expanded,
        transitions,
        decision_indices,
        t,
        k,
        support_regions,
        u0,
        u1,
        length_grid,
        length_speed,
        original_length,
    )
    if unresolved:
        measurements = _measurement_set(before, None, "candidate_not_accepted")
        endpoints = _endpoint_record(
            original, candidate, params.endpoint_policy, measured=True, reason=None
        )
        return finish(
            _OUTCOME_FAILED,
            "verification_failed",
            detection=detection,
            regions_record=regions_record,
            initialization=initialization,
            main_solve=main_solve,
            measurements=measurements,
            endpoints=endpoints,
            outside=Measurement(None, "candidate_not_accepted"),
            verification=verification,
            candidate=attempted_spline,
            original_length=original_length,
            speed_floor=eps,
        )

    assert after is not None
    measurements = _measurement_set(before, after, None)
    endpoints = _endpoint_record(
        original, candidate, params.endpoint_policy, measured=True, reason=None
    )
    outside = _outside_displacement(original, candidate, expanded, transitions, fine_grid)
    reason = (
        "zero_strength_reused_initialization" if not main_solve.performed else "solver_complete"
    )
    return finish(
        _OUTCOME_COMPLETED,
        reason,
        detection=detection,
        regions_record=regions_record,
        initialization=initialization,
        main_solve=main_solve,
        measurements=measurements,
        endpoints=endpoints,
        outside=outside,
        verification=verification,
        candidate=attempted_spline,
        original_length=original_length,
        speed_floor=eps,
    )


class _BasisParityError(Exception):
    """Raised when precomputed basis matrices disagree with direct evaluation."""


def _build_output_spline(info: _SplineInfo, active_controls: _FloatArray) -> BSpline:
    """Rebuild a distinct output spline in the input's axis/extrapolate layout."""
    if len(info.trailing):
        full = np.vstack((active_controls, info.trailing))
    else:
        full = np.array(active_controls, dtype=np.float64, copy=True)
    out = full if info.axis == 0 else np.moveaxis(full, 0, info.axis)
    return BSpline(
        np.array(info.t, dtype=np.float64, copy=True),
        np.array(out, dtype=np.float64, copy=True),
        info.k,
        axis=info.axis,
        extrapolate=info.extrapolate,
    )


def _detection_record(performed: bool, reason: str | None) -> DetectionRecord:
    return DetectionRecord(
        performed=performed,
        reason=reason,
        probe_count=None,
        refinement_probe_count=None,
        refinement_success_count=None,
        baseline_peak_curvature=Measurement(None, reason or "not_performed"),
        baseline_min_speed=Measurement(None, reason or "not_performed"),
        speed_floor_probe_count=None,
    )


def _constant_reference_error(observations: _Observations | None, info: _SplineInfo) -> float:
    if observations is None:
        return 0.0
    squared = np.sum((observations.points - info.active[0]) ** 2, axis=1)
    return float(np.sqrt(np.sum(observations.weights * squared) / np.sum(observations.weights)))


def _endpoint_record(
    original: BSpline,
    curve: BSpline,
    policy: str,
    *,
    measured: bool,
    reason: str | None,
) -> EndpointRecord:
    """Measure endpoint value/first-derivative changes against the input curve."""
    if not measured:
        return EndpointRecord(
            policy=policy,
            checked=policy != "free",
            value_change_max=Measurement(None, reason),
            first_derivative_change_max=Measurement(None, reason),
            tolerance=None,
        )
    ends = np.asarray([original.t[original.k], original.t[len(original.t) - original.k - 1]])
    original_values = np.asarray(original(ends), dtype=np.float64)
    curve_values = np.asarray(curve(ends), dtype=np.float64)
    original_derivatives = np.asarray(original(ends, nu=1), dtype=np.float64)
    curve_derivatives = np.asarray(curve(ends, nu=1), dtype=np.float64)
    value_change = float(np.max(np.linalg.norm(curve_values - original_values, axis=1)))
    derivative_change = float(
        np.max(np.linalg.norm(curve_derivatives - original_derivatives, axis=1))
    )
    value_scale = max(1.0, float(np.max(np.linalg.norm(original_values, axis=1))))
    derivative_scale = max(1.0, float(np.max(np.linalg.norm(original_derivatives, axis=1))))
    tolerance = _ENDPOINT_RELATIVE_TOLERANCE * max(value_scale, derivative_scale)
    return EndpointRecord(
        policy=policy,
        checked=policy != "free",
        value_change_max=Measurement(value_change),
        first_derivative_change_max=Measurement(derivative_change),
        tolerance=tolerance,
    )


def _regions_record(
    selected: Sequence[tuple[float, float]],
    expanded: Sequence[tuple[float, float]],
    transitions: Sequence[TransitionRecord],
    decision_indices: _IndexArray,
    t: _FloatArray,
    k: int,
    support_regions: Sequence[tuple[float, float]],
    u0: float,
    u1: float,
    length_grid: _FloatArray,
    length_speed: _FloatArray,
    original_length: float,
) -> RegionRecord:
    support_union = _merge_intervals([(float(t[j]), float(t[j + k + 1])) for j in decision_indices])
    strict = _strict_outside(support_regions, u0, u1)
    arc_length = 0.0
    for a, b in strict:
        inside = (length_grid >= a) & (length_grid <= b)
        if np.count_nonzero(inside) >= 2:
            arc_length += float(np.trapezoid(length_speed[inside], length_grid[inside]))
    fraction = arc_length / original_length if original_length > 0 else None
    return RegionRecord(
        selected=list(selected),
        expanded=list(expanded),
        transitions=list(transitions),
        free_control_indices=[int(j) for j in decision_indices],
        free_support_union=support_union,
        strict_outside=strict,
        strict_outside_arc_length=Measurement(arc_length),
        strict_outside_arc_fraction=Measurement(fraction),
    )


def _outside_displacement(
    original: BSpline,
    candidate: BSpline,
    expanded: Sequence[tuple[float, float]],
    transitions: Sequence[TransitionRecord],
    fine_grid: _FloatArray,
) -> Measurement:
    """Maximum candidate displacement on the strict outside (mask == 0).

    ``None`` with a reason when no positive-length strict outside exists; a
    zero displacement is never fabricated.
    """
    mask = _region_weight(fine_grid, expanded, transitions)
    outside = mask == 0.0
    if not np.any(outside):
        return Measurement(None, "no_positive_length_strict_outside")
    original_speed = np.linalg.norm(np.asarray(original(fine_grid, nu=1), dtype=np.float64), axis=1)
    segments = outside[:-1] & outside[1:]
    arc_length = float(
        np.sum(
            np.diff(fine_grid)[segments]
            * (original_speed[:-1][segments] + original_speed[1:][segments])
            / 2
        )
    )
    if arc_length <= 1e-12:
        return Measurement(None, "no_positive_length_strict_outside")
    displacement = np.linalg.norm(
        np.asarray(candidate(fine_grid), dtype=np.float64)
        - np.asarray(original(fine_grid), dtype=np.float64),
        axis=1,
    )
    return Measurement(float(np.max(displacement[outside])))


def _verify_candidate(
    original: BSpline,
    candidate: BSpline,
    info: _SplineInfo,
    c0: _FloatArray,
    decision_indices: _IndexArray,
    params: BSplineCurvatureSmoothingParams,
    eps: float,
    original_length: float,
    breaks: _FloatArray,
    fine_grid: _FloatArray,
    observations: _Observations | None,
) -> tuple[VerificationRecord, dict[str, float | None] | None, list[str]]:
    """Verify the candidate independently of the optimizer's residual samples."""
    unresolved: list[str] = []
    knots_ok = bool(np.array_equal(np.asarray(candidate.t, dtype=np.float64), info.t))
    degree_ok = bool(candidate.k == info.k)
    candidate_controls = np.asarray(candidate.c, dtype=np.float64)
    frozen_mask = np.ones(info.n, dtype=bool)
    frozen_mask[decision_indices] = False
    frozen_ok = bool(np.array_equal(candidate_controls[frozen_mask], c0[frozen_mask]))
    if not knots_ok:
        unresolved.append("knots_changed")
    if not degree_ok:
        unresolved.append("degree_changed")
    if not frozen_ok:
        unresolved.append("frozen_controls_changed")

    ends = np.asarray([info.u0, info.u1], dtype=np.float64)
    original_values = np.asarray(original(ends), dtype=np.float64)
    original_derivatives = np.asarray(original(ends, nu=1), dtype=np.float64)
    value_change = float(
        np.max(
            np.linalg.norm(np.asarray(candidate(ends), dtype=np.float64) - original_values, axis=1)
        )
    )
    derivative_change = float(
        np.max(
            np.linalg.norm(
                np.asarray(candidate(ends, nu=1), dtype=np.float64) - original_derivatives, axis=1
            )
        )
    )
    value_tolerance = _ENDPOINT_RELATIVE_TOLERANCE * max(
        1.0, float(np.max(np.linalg.norm(original_values, axis=1)))
    )
    derivative_tolerance = _ENDPOINT_RELATIVE_TOLERANCE * max(
        1.0, float(np.max(np.linalg.norm(original_derivatives, axis=1)))
    )
    endpoints_ok = True
    if params.endpoint_policy != "free":
        if value_change > value_tolerance:
            unresolved.append("endpoint_values_changed")
            endpoints_ok = False
        if (
            params.endpoint_policy == "position_and_tangent"
            and derivative_change > derivative_tolerance
        ):
            unresolved.append("endpoint_tangents_changed")
            endpoints_ok = False

    coarse_base = np.unique(
        np.concatenate((np.linspace(info.u0, info.u1, _VERIFICATION_COARSE_PROBES), breaks))
    )
    speed_coarse_base, kappa_coarse_base = _speed_and_curvature(candidate, coarse_base, eps)
    refined, refinement_successes = _refine_extrema(
        candidate, coarse_base, kappa_coarse_base, speed_coarse_base, eps
    )
    coarse_grid = np.unique(np.concatenate((coarse_base, refined))) if len(refined) else coarse_base
    fine = np.unique(np.concatenate((fine_grid, refined))) if len(refined) else fine_grid
    speed_coarse, kappa_coarse = _speed_and_curvature(candidate, coarse_grid, eps)
    speed_fine, kappa_fine = _speed_and_curvature(candidate, fine, eps)
    bending_coarse = float(
        np.sum(_trapezoid_weights(coarse_grid) * kappa_coarse**2 * np.maximum(speed_coarse, eps))
    )
    bending_fine = float(
        np.sum(_trapezoid_weights(fine) * kappa_fine**2 * np.maximum(speed_fine, eps))
    )
    peak_coarse = float(np.max(kappa_coarse))
    peak_fine = float(np.max(kappa_fine))
    min_speed = float(np.min(speed_fine))
    curvature_converged = bool(
        abs(peak_fine - peak_coarse) <= _CONVERGENCE_RELATIVE_TOLERANCE * max(peak_fine, 1e-8)
    )
    bending_converged = bool(
        abs(bending_fine - bending_coarse)
        <= _CONVERGENCE_RELATIVE_TOLERANCE * max(bending_fine, 1e-8)
    )
    regularity_ok = bool(min_speed > eps)
    if not regularity_ok:
        unresolved.append("tangent_regularity_unresolved")
    if not curvature_converged:
        unresolved.append("curvature_resolution_unresolved")
    if not bending_converged:
        unresolved.append("bending_resolution_unresolved")

    after = _curve_measurements(
        candidate, original, fine_grid, refined, eps, original_length, observations
    )
    verification = VerificationRecord(
        performed=True,
        reason=None,
        coarse_grid_size=int(len(coarse_grid)),
        fine_grid_size=int(len(fine)),
        refinement_probe_count=int(len(refined)),
        refinement_success_count=int(refinement_successes),
        knots_preserved=knots_ok,
        degree_preserved=degree_ok,
        frozen_controls_preserved=frozen_ok,
        endpoints_preserved=(endpoints_ok if params.endpoint_policy != "free" else None),
        regularity_ok=regularity_ok,
        curvature_converged=curvature_converged,
        bending_converged=bending_converged,
        unresolved_reasons=unresolved,
    )
    return verification, after, unresolved


def _failed_result(
    reason: str,
    message: str,
    *,
    detection: DetectionRecord,
    selected: Sequence[tuple[float, float]],
    expanded: Sequence[tuple[float, float]],
    transitions: Sequence[TransitionRecord],
    decision_indices: _IndexArray,
    original_length: float,
    eps: float,
    params: BSplineCurvatureSmoothingParams,
    observations: _Observations | None,
    info: _SplineInfo,
    original: BSpline,
    fine_grid: _FloatArray,
    length_grid: _FloatArray,
    length_speed: _FloatArray,
    initialization: SolveRecord | None = None,
    main_solve: SolveRecord | None = None,
    attempted: BSpline | None = None,
) -> BSplineSmoothingResult:
    """Assemble a failed outcome that retains the original curve."""
    before = _curve_measurements(
        original,
        original,
        fine_grid,
        np.empty(0, dtype=np.float64),
        eps,
        original_length,
        observations,
    )
    support_regions = _merge_intervals(_support_scopes(expanded, transitions))
    regions_record = _regions_record(
        selected,
        expanded,
        transitions,
        decision_indices,
        info.t,
        info.k,
        support_regions,
        info.u0,
        info.u1,
        length_grid,
        length_speed,
        original_length,
    )
    report = SmoothingReport(
        outcome=_OUTCOME_FAILED,
        reason=reason,
        fidelity_reference=(
            _REFERENCE_OBSERVATIONS if observations is not None else _REFERENCE_ORIGINAL_CURVE
        ),
        parameters=_effective_parameters(params),
        original_length=original_length,
        speed_floor=eps,
        initialization=initialization or _not_performed_solve("initialization", reason),
        main_solve=main_solve
        or SolveRecord(kind="main", performed=False, reason=reason, message=message),
        measurements=_measurement_set(before, None, "candidate_not_accepted"),
        endpoints=_endpoint_record(
            original,
            original,
            params.endpoint_policy,
            measured=False,
            reason="candidate_not_accepted",
        ),
        regions=regions_record,
        outside_max_displacement=Measurement(None, "candidate_not_accepted"),
        detection=detection,
        verification=VerificationRecord(
            performed=False,
            reason=reason,
            coarse_grid_size=None,
            fine_grid_size=None,
            refinement_probe_count=None,
            refinement_success_count=None,
            knots_preserved=None,
            degree_preserved=None,
            frozen_controls_preserved=None,
            endpoints_preserved=None,
            regularity_ok=None,
            curvature_converged=None,
            bending_converged=None,
            unresolved_reasons=[],
        ),
    )
    return BSplineSmoothingResult(
        spline=_build_output_spline(info, info.active), report=report, attempted_spline=attempted
    )
