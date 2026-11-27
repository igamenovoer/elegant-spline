# Elegant Spline development guide

This checkout owns the Python package, build metadata, Pixi environment, and functional verification.

- Put spline construction, fitting, and validation code under `src/elegant_spline/`. Keep test helpers and fixtures with the suites that use them. [Test layout](tests/README.md)
- Keep runnable experiments in `scripts/`, usage and API references in `docs/`, and functional settings in `configs/`.
- Use `models/` and `datasets/` for acquisition instructions and manifests. Record required source submodules under `extern/tracked/`.
- Document runtime settings in `env.example` when a feature introduces them. Keep local values in the ignored `.env`.
- Update `pixi.lock` with `pixi lock` when changing dependency declarations in `pyproject.toml`.
- Use the globally installed OpenSpec skills for spec-driven work. Run OpenSpec from this checkout's root and keep specifications and change records under `openspec/`.

Run the setup and verification commands from this checkout's root. [Getting started](docs/README.md)
