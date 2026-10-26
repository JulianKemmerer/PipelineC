# pypeline_sim_debug complexity review

A diagnostic CLI comparing native and cocotb/VHDL debug output. It supports testing the Python front end rather than compiling hardware itself; its correctness determines whether differential failures are trustworthy.

Source: [pypeline_sim_debug.py](../../src/pypeline_sim_debug.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 302 | 224 | 5 | 1 | 32 |

Highest-scoring functions: `main` (106–298, CCN 32); `_print_context` (86–103, CCN 6); `_cycles_of_debug_lines` (64–76, CCN 5).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Warm build and two simulation copies** — `main` (106–298, CCN 32). It rewrites CLI arguments, runs an optional build, copies the warm output and starts concurrent simulations. Each simulation still traverses build logic; matching warm directories does not intrinsically prove identical final physical plans.
2. **Log protocol** — `_cycles_of_debug_lines` and context/diff handling. Correctness depends on ordered clock markers and debug-print tags. Stderr merging, output before the first cycle and early termination can change the comparison without changing hardware.
3. **Failure and workspace handling** — subprocess return codes, existing output directories and cleanup. Build failure is carried into the later verdict, but the script still prepares/runs both branches. That preserves diagnostics at extra cost and complicates what a mismatch means.

## Duplication and simplification

Use a structured `BuildResult` manifest with implementation identity and simulation inputs so both simulators consume the same compiled plan. Split orchestration, tagged-event parsing and comparison into three small operations. Share CLI option normalization with the main driver rather than reconstructing build/sim flags by filtering strings.

The tool is useful and should be retained. Reduce its reliance on re-running compilation once build/session artifacts become reusable; do not treat two successful subprocesses as sufficient evidence of equivalence.

## Validation

No new defect was reproduced. Use log fixtures for matching runs, first-cycle differences, missing/extra cycles, early sim_finish, native failure and build failure. Require both implementation signatures and cycle-aligned events to match before presenting an equivalence verdict.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

