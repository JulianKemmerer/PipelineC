# pipelinec driver complexity review

Source: [src/pipelinec](../../src/pipelinec), also reached through the `src/pypelinec` symlink. The extensionless Python driver is included because it controls the Pypeline build lifecycle. Reviewed on the working tree based on `9eafa7d8`.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Simplification](#simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 608 | 510 | 0 | 0 | 0 |

Highest-scoring functions: none; module-level control flow is not scored as a function.

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Top-level executable policy** — argument normalization and configuration around lines 377–539. The script runs at module scope, so function complexity tools undercount its control flow. CLI options mutate SYN, SWEEP, OPEN_TOOLS, AUTO and pypeline globals. Source import, part/tool resolution and simulation shortcuts require a particular order.
2. **Early native-simulation shortcut** — around lines 477–485. It runs before several later build settings are applied. This is intentional for comb simulation, but adding an option requires deciding whether it also applies to that shortcut. Validation and option semantics should not depend on taking the longer route.
3. **Build transitions** — parsing, target resolution, latency memory, no-tool fallback, fixed-only reparsing, pipelined build, timing verdict, optional bitstream and simulation (543–603). The same parser-state variable can represent several generations. A stale generation must not supply final host types, schedules or output files.
4. **Exit-time policy** — atexit reports and deep-module sys.exit calls. Library errors, timing-not-met results and successful simulator exits have different reporting/cleanup paths.

## Simplification

Introduce `main(argv)`, an immutable BuildOptions object and a BuildSession. Normalize/validate all options once, then choose an explicit build mode. Keep the driver as the owner of process exit codes; compiler and simulator operations should return results or raise typed errors.

A BuildResult should hold the final parse generation, timing plan, clock description, artifact manifest and verdict. SIM and pypeline_sim_debug can consume it instead of reconstructing options and rebuilding. Keep latency-driven re-elaboration where Python changes topology; make it a named build operation rather than an implicit change in shared globals.

This is a coordination refactor. Moving argparse declarations elsewhere alone saves no total code. The useful deletion is repeated policy and argument filtering in the driver, SIM and debug helper.

## Validation

No new CLI failure was reproduced. Exercise the mode matrix: comb/native, comb/HDL, no-synth with fixed latency, pipelined build, missing synthesis tools, timing failure and explicit part/tool disagreement. Assert final artifacts and simulator inputs come from the same generation. Existing [test documentation](../pypeline_TESTS.md) identifies the relevant suites.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).
