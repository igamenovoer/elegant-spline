# Spline viewer

From this directory, use Bun to install the locked dependencies and start the viewer.

```sh
bun install --frozen-lockfile
bun run dev
```

Open the localhost URL printed by Bun. The app starts with a bundled fit. Use the file picker to inspect another exported JSON document. Browser file reads, navigation and inspection run locally.

## Static build

```sh
bun run build
```

Serve the contents of `dist/` with a static HTTP server. The build contains the sample, scripts, styles and fonts.

## Tests

```sh
bun run typecheck
bun run test:unit
bun run test:e2e
```

The browser suite builds and serves the production assets on loopback and runs Chromium through Playwright. If the matching Chromium binary is missing, provision it with `bunx playwright install chromium` before running the suite.

To exercise a fresh export during browser verification, generate the island example with the documented Python command and point `SPLINE_TEST_DOCUMENT` at that output file. [Export the island example](../../docs/viewer-format.md#reproduce-the-island-example)

```sh
SPLINE_TEST_DOCUMENT=/absolute/path/to/island-fit.json bun run test:e2e
```
