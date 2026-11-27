# Elegant Spline

Elegant Spline is a project for constructing and fitting spline curves that satisfy geometric and numerical conditions. Given waypoints or a guide curve, the goal is to return an evaluable spline and report how well it meets each condition.

## Conditions

- **Fit to data.** Interpolate required points and approximate other observations within a tolerance.
- **Endpoint behavior.** Set endpoint positions and tangents when the application requires them.
- **Smoothness.** Control continuity at joins and reduce bending where the curve has room to turn.
- **Spatial containment.** Keep the entire curve inside a permitted region and maintain clearance from obstacles between waypoints.

## Initial problem

Fit a planar cubic B-spline to an ordered route through a polygonal domain with holes. The curve should reach the start and goal, pass near intermediate waypoints, and keep the required clearance through each turn. Endpoint and clearance requirements define which curves are admissible. Fitting error and bending help choose among those curves.

The project is at the design stage.

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
