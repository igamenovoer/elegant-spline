# planar-regularized-and-fixed-knot-fitting Specification

## Purpose

Fit a planar cubic spline to ordered points using either a coordinate smoothness penalty or a nominal spacing for a fixed knot basis. Let callers control the preparation of their points and inspect the resulting fit.

## Requirements

### Requirement: Both fitters accept standalone planar data and options

The two fitters SHALL be importable from the installed Elegant Spline package and accept a nonempty ordered sequence of finite real coordinate pairs and immutable Python options. Distance settings and distance measurements SHALL use the caller's coordinate units. Fitting SHALL require only the installed package and its declared numerical dependencies.

#### Scenario: An isolated caller fits ordered planar points

- **WHEN** a caller installs the wheel with the minimum supported SciPy release and supplies synthetic coordinates and options to either fitter
- **THEN** the fitter SHALL be importable and SHALL return its result without external project assets, configuration, or environment bindings

#### Scenario: Invalid data reaches a fitter

- **WHEN** the input is empty, malformed, nonfinite, or has unrepresentable chord distances, or a caller supplies an invalid option
- **THEN** the fitter SHALL raise the corresponding input or settings error before numerical fitting

### Requirement: Both fitters share configurable guide preparation

Both fitters SHALL apply the order-preserving and bounded guide preparation defined by `planar-distance-spline-fitting`. Callers SHALL be able to control resampling spacing, whole-group merge diameter, endpoint weight multiplier, and maximum fit points. Reports SHALL expose guide membership, requested and effective resampling spacing, and normalized weights.

#### Scenario: The caller supplies identical guide options

- **WHEN** both fitters receive the same points and preprocessing settings, including a point cap that coarsens sampling
- **THEN** both SHALL report equivalent guide points, membership, parameters, and weights, retain both ends of the guide, and identify that the cap was applied
- **AND** each result SHALL retain one source parameter per original observation, with later return visits assigned their own progress

### Requirement: Smoothing fits penalize coordinate second derivatives

The smoothing fitter SHALL accept a finite nonnegative smoothing strength. It SHALL balance weighted squared guide residuals against the strength times the integral of squared coordinate second derivatives over normalized chord progress. It SHALL require at least four source observations after consecutive deduplication and five strictly increasing fit parameters.

#### Scenario: Smoothing strength is zero

- **WHEN** a usable guide is fitted with zero smoothing strength
- **THEN** the initial spline SHALL interpolate the prepared guide points at their fit parameters within documented numerical tolerance

#### Scenario: The prepared guide has only four points

- **WHEN** the source has at least four observations after consecutive deduplication and the configured point cap leaves four guide points
- **THEN** the smoothing fitter SHALL skip its initial solve and report insufficient prepared observations

### Requirement: Fixed-knot fits use a bounded spacing-derived basis

The fixed-knot fitter SHALL accept a finite positive nominal knot spacing. With at least four source observations after consecutive deduplication and four strictly increasing fit parameters, it SHALL fit by weighted least squares on a clamped basis. The requested span count SHALL be the guide length divided by spacing, rounded up with a minimum of one. The fit SHALL cap this count at the number of prepared points minus three and space interior knots uniformly in progress.

#### Scenario: The requested spacing requires too many spans

- **WHEN** the requested span count exceeds the observation cap on spans
- **THEN** the initial fit SHALL use the capped span count
- **AND** the report SHALL give the nominal spacing, the requested count when representable, the selected count, and the effective spacing along the guide

#### Scenario: The request fits one span

- **WHEN** a caller requests a nominal spacing at least as large as the length of a usable guide
- **THEN** the initial fit SHALL use one span with a clamped cubic basis

### Requirement: The output follows the planar curve and stage contract

Any returned curve SHALL be a clamped globally C² cubic on `[0, 1]` with extrapolation disabled. Both fitters SHALL apply the endpoint correction, optional geometric fairing, and explicit recovery policies defined by `planar-distance-spline-fitting`. Initial solver work SHALL be bounded to one logical planar fit attempt.

#### Scenario: Endpoint correction and fairing are requested

- **WHEN** a caller enables endpoint correction and optional fairing and a usable initial spline is fitted
- **THEN** correction SHALL target the original endpoints and fairing SHALL act on the usable curve retained after the correction stage
- **AND** the report SHALL identify each stage outcome and the measurements of the returned curve

#### Scenario: A complete planar fit cannot be produced

- **WHEN** the initial solver is skipped or fails to produce a usable curve
- **THEN** the fit SHALL be unavailable with an explanatory reason unless the caller requests endpoint recovery
- **AND** a successful endpoint recovery SHALL return a line or constant marked as a fallback

### Requirement: Reports separate fitted error from the method controls

Each result SHALL identify its fitting method, requested method control, initial solver outcome, and measured ordered source error and weighted guide residual for each available stage. Distance-budget fields SHALL be inapplicable for both methods. Effective knot spacing and span counts SHALL describe the initial fitting basis when it is constructed.

#### Scenario: Postprocessing changes an initial fit

- **WHEN** endpoint correction or fairing changes a fitted curve
- **THEN** the report SHALL distinguish initial and final errors and SHALL measure the final values on the returned curve
- **AND** a distance-budget compliance result SHALL be absent
