# Elegant Spline

Elegant Spline is a project for constructing and fitting spline curves that satisfy geometric and numerical conditions. Given waypoints or a guide curve, the goal is to return an evaluable spline and report how well it meets each condition.

## Conditions

- **Fit to data.** Interpolate required points and approximate other observations within a tolerance.
- **Endpoint behavior.** Set endpoint positions and tangents when the application requires them.
- **Smoothness.** Control continuity at joins and reduce bending where the curve has room to turn.
- **Spatial containment.** Keep the entire curve inside a permitted region and maintain clearance from obstacles between waypoints.

## Fitting and fairing

Fit ordered planar observations with a weighted RMS allowance and optional endpoint correction. [Planar distance fitting](docs/distance-fitting.md)

Fair an existing SciPy B-spline while preserving its basis and the boundary values selected by the caller. [Curvature smoothing](docs/curvature-smoothing.md) · [Combined example](docs/fit-and-fair.md)

## Spatial-containment goal

A future fitting capability will accept a polygonal domain with holes as a hard constraint. It will fit curves through prescribed endpoints and maintain required clearance throughout each turn.

## Local setup

The setup guide covers the locked Pixi install and package checks. [Getting started](docs/README.md)

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/elegant_spline/` | Python package for spline construction, fitting, and validation. |
| `tests/` | Package and feature verification. [Test suites](tests/README.md) |
| `scripts/` | Functional commands and runnable experiments. |
| `docs/` | Usage, APIs, formats, and requirements. |
| `configs/` | Functional configuration. |
| `models/` and `datasets/` | Acquisition instructions and manifests for model and dataset resources. |
| `extern/tracked/` | Pinned source dependencies. |
| `openspec/` | Elegant Spline specifications, proposed changes, and archived changes. |
| `pyproject.toml` and `pixi.lock` | Package metadata, build configuration, tasks, and locked environments. |
| `env.example` | Template for runtime environment settings. |

Contributor guidance lives in [AGENTS.md](AGENTS.md).

Licensed under the Apache License, Version 2.0. [License text](LICENSE)
