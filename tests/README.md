# Verification

From the repository root, run the fast Python suites in the locked Pixi environment.

```bash
pixi run --locked test
```

| Directory | Scope |
| --- | --- |
| `unit/` | Isolated checks of spline operations and numerical properties. |
| `integration/` | Checks of installed package behavior and workflows spanning multiple components. |
| `instructional/` | Definitions for agent-driven verification. |
| `acceptance/` | End-to-end scenarios run with their documented prerequisites. |
| `manual/` | Verification procedures performed by an operator. |

The default task discovers `unit/` and `integration/`. Use the commands documented by each acceptance, instructional, or manual case when those cases are added.
