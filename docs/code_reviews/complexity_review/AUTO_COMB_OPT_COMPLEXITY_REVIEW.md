# AUTO_COMB_OPT complexity review

Python-facing combinational optimization orchestration, using AUTO's shared DAG and emitter. [AUTO_COMB_OPT design](../AUTO_COMB_OPT_DESIGN.md) describes objective-specific plan pinning and the original implementation fallback.

Source: [AUTO_COMB_OPT.py](../../src/AUTO_COMB_OPT.py). This is a targeted structural review of the working tree based on commit `9eafa7d8`, including concurrent multi-clock changes. Function names are the stable navigation aid; line numbers describe the measured snapshot. Suspected failure cases are not confirmed bugs unless explicitly labeled.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 424 | 365 | 9 | 3 | 66 |

Highest-scoring functions: `_implementation_seeds` (104–227, CCN 66); `prepare` (230–365, CCN 43); `BUILD_FUNC` (368–396, CCN 16).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Implementation seeds** — `_implementation_seeds` (104–227, CCN 66). Constant multiply/divide, known/demanded-bit narrowing, distributed arithmetic and selective opening combine legality checks with live helper creation. The soft-div path recognizes module/function/closure names, coupling an optimization to library implementation details.
2. **Preparation and pinning** — `prepare` (230–365). Purity, inherited operator scope, target selection, graph dependencies, caches, candidate families, code generation and rescoring share one flow. The cache deliberately pins a choice while measurement state changes; resetting it too often is as wrong as retaining it across unrelated builds.
3. **Round-trip fidelity** — `CombEmitter.generate` and `BUILD_FUNC`. A chosen graph becomes Python, then Logic, and delay ranking can rebuild a graph from that result. This catches some lowering changes but introduces another scope/type/naming boundary.

## Duplication and simplification

The shared AUTO base is already the right direction. Extract seed rules with explicit input requirements, produced graph and rejection reason; do not add more nested cases to one function. Replace recognition of `operators.soft_div` internals with operation metadata supplied by the helper.

Make plan ownership explicit in the build session: semantic key, objective, target/model identity and measurement snapshot belong to one record. The `_PLANS` cache intentionally omits changing measurements from the key to stabilize a build; preserve that intent while defining when a new build starts. Direct typed-IR lowering would remove more code than another wrapper around `prepare`.

## Validation

No wrong optimization was reproduced. Test an unsupported seed retains the original, custom scopes remain intact, signed intermediate casts block invalid narrowing, and candidate zero survives search limits. Compare emitted semantics at small widths and pinned choices across reparses; test a fresh build can make a different choice when its measurement snapshot changes.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

