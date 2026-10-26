# AUTO_MULTI_CYCLE complexity review

Multi-cycle constraints, timing-path qualification, automatic cycle-count feedback and confirmation. [AUTO_MULTI_CYCLE design](../../AUTO_MULTI_CYCLE_DESIGN.md) documents the current Vivado-only constraint contract.

Source: [AUTO_MULTI_CYCLE.py](../../../src/AUTO_MULTI_CYCLE.py). This is a targeted structural review of the working tree based on commit `9eafa7d8`, including concurrent multi-clock changes. Function names are the stable navigation aid; line numbers describe the measured snapshot. Suspected failure cases are not confirmed bugs unless explicitly labeled.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 672 | 498 | 27 | 3 | 23 |

Highest-scoring functions: `CHECK_MCP_TIMING_REPORT` (257–308, CCN 23); `AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT` (311–354, CCN 17); `REMEMBER_ISOLATED_REPORTS` (504–542, CCN 16).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Constraint/report correspondence** — `GET_MCP_CELL_PATHS`, `CHECK_MCP_TIMING_REPORT` (257–308), `AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT` (311–354). Register-name globs, endpoint pins, hierarchy and rounded setup requirements must identify the same path. Matching a CE/reset path as data, or accepting a lost endpoint, invalidates the cycle allowance.
2. **Datapath identity** — `MCP_SHAPE`. It recursively hashes the cone feeding a capture register so handshake-count changes can reuse evidence while real datapath changes cannot. Types, constants, calls and the stopping boundary at state must be complete inputs.
3. **Evidence and provisional seeds** — `REMEMBER_ISOLATED_REPORTS` (504–542), `SEED_COUNTS`, `PROPOSE_CONFIRM_DOWN`. Per-shape dictionaries carry isolated timing, provisional floors and used probes across phases. Replicated endpoints require worst-case coverage; fewer observed paths must not justify a smaller count.
4. **Parallel evidence updates** — `REMEMBER_ISOLATED_REPORTS` performs read/max/write on a shared dictionary from backend work. The intended operation is a reduction. A multi-thread lost update is a plausible race to test, not reproduced in this review.

## Duplication and simplification

The file already centralizes endpoint glob generation for constraints and matching; retain that good boundary. Consolidate report qualification into a typed endpoint-pair observation used by checking, seeding and confirmation instead of repeating regex/period logic.

Return evidence from jobs and reduce it in the owning thread, or synchronize the reduction. Move caches into the build session and separate persistent characterized datapaths from per-confirmation trial state. Share latency-constraint validation/key formation with the API and LOGIC metadata, without pretending MCP counts are physical pipeline registers.

## Validation

Check every setup exception has its paired hold rule and the intended preserved data endpoints. Use same-count reparse, changed datapath, replicated endpoints, missing optional reports, caps and failed confirm-down rollback. Stress evidence arrival in different orders. No Vivado coverage proof or new end-to-end MCP failure was produced by this review.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

