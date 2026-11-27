# bspline-curvature-smoothing Specification

## Purpose

Fair an existing vector-valued B-spline using geometric curvature while preserving its representation and the boundary conditions selected by the caller.

## Requirements

### Requirement: Fairing preserves the spline representation

The smoother SHALL accept finite, nonperiodic, real vector B-splines of degree at least three, with at least two coordinates and global `C2` continuity. It SHALL leave input arrays intact and preserve degree, knots, base domain, coordinate-axis layout, and extrapolation setting in its returned curve.

#### Scenario: A supported spline uses a non-unit parameter domain

- **WHEN** a caller fairs a vector spline on a domain other than `[0, 1]`
- **THEN** the returned curve SHALL use the same parameter interval, degree, knots, and evaluation layout

#### Scenario: Equivalent splines use different coordinate axes

- **WHEN** equivalent splines are supplied in supported coordinate-first and parameter-first layouts
- **THEN** their resulting geometries SHALL agree within documented precision and each result SHALL preserve its input layout

### Requirement: Fidelity uses a fixed reference

The smoother SHALL use the input curve as its fidelity reference unless the caller supplies observations with matching fixed parameters. Supplied weights SHALL be positive and multiply squared observation residuals directly. Invalid settings and incomplete, mismatched, or out-of-domain observations SHALL raise an input or settings error.

#### Scenario: No observations are supplied

- **WHEN** the smoother receives only a spline
- **THEN** fidelity SHALL measure displacement from the original curve with weighting by original arc length

#### Scenario: Observations revisit a location

- **WHEN** observations share a location or have repeated valid parameters
- **THEN** fidelity SHALL evaluate the fitted curve at the given parameter for each observation

### Requirement: Fairing optimizes geometric bending

The smoother SHALL balance fidelity with squared geometric curvature integrated over candidate arc length. It SHALL normalize bending by original length and support an optional fidelity term outside selected regions. Reports SHALL identify the objective terms and measure the resulting source error and bending.

#### Scenario: A caller rotates the spline and observations

- **WHEN** the spline and its fitting reference undergo the same rigid transformation
- **THEN** measured fidelity and bending SHALL remain equivalent within documented numerical precision

#### Scenario: A numerically usable candidate misses a quality goal

- **WHEN** a completed candidate has higher measured error or peak curvature than the input
- **THEN** the report SHALL present the measured values and distinguish numerical validity from the quality outcome

### Requirement: Region selection defines the smoothing scope

The smoother SHALL support whole-domain selection, automatic curvature-threshold detection, and explicit parameter intervals. Explicit intervals SHALL take precedence. The report SHALL identify selected and expanded intervals, affected control support, and any coverage outside the affected region.

#### Scenario: Explicit intervals overlap

- **WHEN** the caller supplies overlapping valid parameter intervals in any order
- **THEN** their union SHALL determine region selection prior to configured padding and transitions

#### Scenario: No interval is selected

- **WHEN** explicit selection is empty or automatic selection finds no qualifying interval
- **THEN** the smoother SHALL retain the input geometry and report an unchanged outcome without a solve

### Requirement: Boundary policies preserve requested values

The smoother SHALL support free endpoints, preserved endpoint positions, and preserved positions plus first parameter derivatives. Preservation SHALL refer to the evaluated spline endpoints and inward derivatives. The smoother SHALL report an unchanged result when constraints leave no free control directions.

#### Scenario: An unclamped spline requests position-and-tangent preservation

- **WHEN** a supported unclamped spline is smoothed with position-and-tangent preservation
- **THEN** the result SHALL retain both evaluated endpoint values and inward first derivatives within documented tolerance

### Requirement: Fairing verifies candidates and retains a usable reference

The smoother SHALL report completed, unchanged, or failed outcomes and bound its initialization and main solve work. It SHALL verify a completed candidate independently of the optimization samples. Incomplete work, failed verification, or unresolved candidate regularity SHALL retain the input geometry with work and failure evidence.

#### Scenario: Verification cannot establish regularity

- **WHEN** verification cannot establish valid curvature measurements near a stationary tangent
- **THEN** the smoother SHALL retain the input curve and identify the unresolved regularity or measurement coverage

#### Scenario: The same smoother is reused

- **WHEN** identical valid data and settings are evaluated before and after an unrelated call under the same numerical versions
- **THEN** spline geometry and semantic outcome evidence SHALL be equivalent within documented numerical precision
