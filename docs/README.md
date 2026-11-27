# Getting started with Elegant Spline

## Install

With Pixi installed, run this command from the Elegant Spline repository root.

```bash
pixi install --locked
```

Pixi installs Python 3.13, NumPy, and SciPy from `pixi.lock`, then installs `elegant_spline` in editable mode. Python imports the package from `src/elegant_spline/`, so local source edits take effect on the next run. [Project manifest](../pyproject.toml)

## Verify

Run the package checks in the locked environment.

```bash
pixi run --locked test
```

The suite checks package installation, distance fitting, fixed-knot fairing, and their combined use. [Test layout](../tests/README.md)

## Use the library

- Fit a planar cubic to ordered points. [Distance fitting](distance-fitting.md)
- Fair an existing vector spline. [Curvature smoothing](curvature-smoothing.md)
- Fit and fair the same curve in one call. [Combined example](fit-and-fair.md)
