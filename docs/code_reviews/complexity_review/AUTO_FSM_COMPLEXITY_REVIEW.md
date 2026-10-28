# AUTO_FSM complexity review

Resource sharing, scheduling, register allocation, feedback and generated FSMs for Python HDL. [AUTO_FSM design](../../AUTO_FSM_DESIGN.md) is necessary context: this is not the legacy C coroutine frontend.

Source: [AUTO_FSM.py](../../../src/AUTO_FSM.py). This is a targeted structural review of the working tree based on commit `9eafa7d8`, including concurrent multi-clock changes. Function names are the stable navigation aid; line numbers describe the measured snapshot. Suspected failure cases are not confirmed bugs unless explicitly labeled.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 8,080 | 5,977 | 190 | 26 | 108 |

Highest-scoring functions: `generate` (6999–7557, CCN 108); `_BUILD_SCHEDULE` (3383–3754, CCN 75); `_SWEEP_MIN_AREA_SCHEDULE` (4238–4672, CCN 53).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Schedule construction** — `_BUILD_SCHEDULE` (3383–3754). Purity, graph cleanup, decomposition, unit pipeline choices, mux/control timing snapshots, resource binding and latency constraints converge in one routine. A schedule must obey dependencies, unit occupancy, select arrival and output-register conventions simultaneously.
2. **Area search with timing constraints** — `_SWEEP_MIN_AREA_SCHEDULE` (4238–4672), `SCHEDULE_DAG`, `ESTIMATE_SCHEDULE_AREA`. Open, unshare, pipeline, merge and fuse moves are scored by rescheduling the whole graph. Shared dictionaries encode both a candidate and measurement history. A stale timing snapshot or an incompletely copied candidate can make a later score depend on exploration order.
3. **FSM emission** — emitter `generate` (6999–7557). Register allocation, input-storage reduction, rolling output packs, state encoding, operand selection, pipelined functional units and stream valid behavior are emitted together. Read-old/write-next ordering and the optional output register are cycle semantics, not formatting details.
4. **Selector equivalence and mux factoring** — `_selection_chains`, operand-equivalence/factor plans, `_emit_operand_factor_plan`. Predicate exclusivity and cast preservation justify balanced selection and shared operands. An incorrect default for an out-of-range selector or loss of an intermediate cast changes hardware even when the scheduled arithmetic is unchanged.
5. **Outer schedule/confirm loop** — `DO_SCHEDULE_PASSES` and timing attribution. A new FSM changes elaboration, its latency-derived surroundings and the pipeline sweep. Failure can come from arithmetic, control/mux fanout or an unrelated crossed MAIN. Changing the schedule based on the wrong path creates growth without progress.

## Duplication and simplification

Hierarchy predicates duplicate AUTO_PIPELINE's traversal. Schedule identity/preparation and source emission overlap with AUTO/AUTO_COMB_OPT, although the shared `_GraphCodegen` already removes some duplication. Keep that existing sharing.

Use explicit immutable records for graph, binding, schedule, storage allocation and observations. Verify a schedule before emission: dependencies available, no illegal resource overlap, storage lifetime respected, output timing explicit. Pass a finished allocation/control plan to a simpler emitter. Make each search move a data transformation with a rejection reason. The area search's step loop now does this for building and judging: each move is an (opened, unshared, pipelined, merged, fused) tuple that one path builds and rejects, which is what lets `_map_forked` build a step's moves in parallel. `test_area_search_is_the_same_at_any_jobs` (`inst/auto_fsm_unit_test.py`) checks the result does not depend on where a move is built. Generating the moves is still four separate loops.

Longer term, emit a scheduled IR directly. CIRCT scheduling infrastructure is a candidate for comparing scheduling kernels, but Pypeline's measured mux costs, pipeline placements, register sharing and iterative tool feedback still require custom policy. Replacing only the list scheduler will not remove most of this file.

## Validation

No new wrong FSM was reproduced. Use existing purity, resource, tighten, stream and QoR tests; add differential schedule interpretation versus emitted HDL for representative binary/onehot control, zero-work graphs, narrowed operands, output-register choices and stalls. Check cold/warm passes produce the same pinned circuit and that a failed trial restores the complete passing schedule.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

