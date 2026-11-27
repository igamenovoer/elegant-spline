# Planar Distance Spline Fitting

## Purpose

Fit a smooth planar cubic B-spline to ordered observations and report its correspondence, residuals, and numerical outcome so callers can judge its suitability.

## ADDED Requirements

### Requirement: Fit input preserves observation order

The fitter SHALL accept a nonempty sequence of finite real coordinate pairs with representable chord distances and preserve the input values. Every fit result SHALL report one normalized cumulative chord parameter per original observation. Distance settings and measurements SHALL use the units of the coordinates.

#### Scenario: An observation is repeated at different visits

- **WHEN** a path contains consecutive equal observations and later returns to the same position after moving away
- **THEN** the consecutive copies SHALL share a source parameter and the later visit SHALL have a larger source parameter
- **AND** the result SHALL retain one parameter for each input observation

#### Scenario: Invalid inputs reach the fitter

- **WHEN** coordinates are malformed, nonfinite, empty, or yield unrepresentable distances, or settings fall outside their documented ranges
- **THEN** the fitter SHALL raise an input or settings error before numerical fitting

### Requirement: Guide preparation is bounded and auditable

The fitter SHALL collapse consecutive duplicates, merge consecutive groups by whole-group diameter, and resample the resulting guide on a single chord parameter. It SHALL coarsen sampling to respect the observation cap and report membership, effective spacing, and detail loss.

#### Scenario: Short steps would grow a cluster beyond its diameter

- **WHEN** the next point is near its predecessor but would make the whole group exceed its diameter limit
- **THEN** the point SHALL start a new group and retain its position in the correspondence record

#### Scenario: Requested sampling exceeds the observation budget

- **WHEN** the requested spacing would supply more fit observations than the cap
- **THEN** the fitter SHALL use coarser sampling within the cap, retain both ends of the guide, and report the adjustment

### Requirement: Distance fitting returns a globally C2 cubic

The fitter SHALL use a caller-supplied positive weighted RMS allowance for one initial cubic fit. The residual budget SHALL be the fit observation count times the squared allowance after normalizing the squared weights to that count. Any returned fitted or recovery curve SHALL be clamped and globally `C2` on normalized progress `[0, 1]` with extrapolation disabled.

#### Scenario: The caller changes the RMS allowance

- **WHEN** the same prepared guide is fitted with two positive allowances
- **THEN** each reported budget SHALL equal its squared allowance times the observation count
- **AND** the fitter SHALL measure the resulting residuals independently of the requested budgets

#### Scenario: The fit has interior knots

- **WHEN** the fitter returns a spline with interior knots
- **THEN** its values and its first two derivatives SHALL be continuous at each knot within the documented verification tolerance

### Requirement: Endpoint correction has an observable result

When enabled, endpoint correction SHALL target the original first and last observations while preserving the basis and global `C2` continuity. The fitter SHALL retain the initial curve on correction failure and report the correction outcome and measured endpoint errors.

#### Scenario: Correction increases the residual above the allowance

- **WHEN** a valid endpoint correction makes the measured residual exceed the initial budget
- **THEN** the corrected curve SHALL remain eligible and the report SHALL record the budget miss

#### Scenario: Endpoint correction fails numerical validation

- **WHEN** correction produces an unusable candidate after a successful initial fit
- **THEN** the fitter SHALL retain the initial fit for subsequent processing and report that correction failed

### Requirement: Optional fairing follows endpoint processing

Enabled fairing SHALL run once after endpoint processing on a usable initial fit. It SHALL use the prepared observations at their fixed fit parameters with equal fidelity weights and preserve the basis, endpoint positions, and first derivatives. The fitter SHALL retain the input to fairing on failure or a no-op and report the outcome separately.

#### Scenario: Fairing changes the selected spline

- **WHEN** fairing verifies a changed candidate
- **THEN** the fit result SHALL expose the input to fairing and return the faired spline as the final curve
- **AND** the final fit residual and endpoint measurements SHALL describe the final curve

#### Scenario: A fairing work limit is reached

- **WHEN** fairing cannot complete within its settings after an otherwise usable fit
- **THEN** the final curve SHALL equal the input to fairing and the report SHALL identify the failed stage

### Requirement: Recovery is explicit

The fitter SHALL distinguish an accepted fit, a recovery curve, and an unavailable result. When an initial fit is skipped or fails, the requested recovery policy SHALL select either an unavailable result or a clamped cubic through the endpoints. Coincident endpoints SHALL yield a constant recovery curve.

#### Scenario: The solve fails and recovery is disabled

- **WHEN** no usable initial curve is available and the caller has disabled recovery
- **THEN** the result SHALL be unavailable with a reason and zero or one recorded initial attempts

#### Scenario: A closed path requests recovery

- **WHEN** a path with coincident endpoints and other distinct positions cannot be fitted and the caller requests endpoint recovery
- **THEN** the fitter SHALL return a constant curve marked as recovery
- **AND** source error SHALL be measured against all input observations

### Requirement: Reports identify the measured curve and reference

The fit report SHALL distinguish source errors from weighted guide residuals and identify the curve stage measured. It SHALL report the requested budget, measured compliance and solver outcome separately. Unavailable measurements SHALL include a reason.

#### Scenario: A later stage changes guide fidelity

- **WHEN** endpoint correction or fairing changes the initial fit
- **THEN** the report SHALL expose the initial and final weighted guide residuals separately
- **AND** the final measurements SHALL describe the curve the caller receives
