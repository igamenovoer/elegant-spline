# Getting started with Elegant Spline

## Install

With Pixi installed, run this command from the Elegant Spline repository root.

```bash
pixi install --locked
```

Pixi provisions Python 3.13 from `pixi.lock` and installs `elegant_spline` in editable mode. Python imports the package from `src/elegant_spline/`, so local source edits take effect on the next run. [Project manifest](../pyproject.toml)

## Verify

Run the package checks in the locked environment.

```bash
pixi run --locked test
```

The current suite checks that Python can import `elegant_spline` and read the installed distribution metadata. [Package tests](../tests/integration/test_package.py) · [Test layout](../tests/README.md)
