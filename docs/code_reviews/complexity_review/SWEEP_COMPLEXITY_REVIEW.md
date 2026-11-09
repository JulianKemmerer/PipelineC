# SWEEP complexity review

The largest concentration of decision complexity: physical placement planning, report attribution, timing refinement, trimming, locks and latency memory. [SWEEP design](../../SWEEP_DESIGN.md) documents the intended decision order and conservative treatment of missing evidence.

Source: [SWEEP.py](../../../src/SWEEP.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 9,446 | 7,281 | 183 | 37 | 339 |

Highest-scoring functions: `DO_PLANNED_THROUGHPUT_SWEEP` (6596–8337, CCN 339); `RESOLVE_INTERNAL_PIPELINE_PLACEMENTS` (2545–2801, CCN 71); `finalize` (846–1089, CCN 60).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Refinement orchestration** — `DO_PLANNED_THROUGHPUT_SWEEP` (6596–8337, 1,742 lines, CCN 339). Plans, planless MAINs, regions, MCP counts, trim probes, snapshots, repeated implementations, fallback measurements, budgets and final reports coexist. Many `best_*` and `met_snapshot_*` variables must be restored together. A partial rollback can report timing from one implementation while emitting another.
2. **Landscape and placement geometry** — `SliceLandscape.finalize` (846–1089), `RESOLVE_INTERNAL_PIPELINE_PLACEMENTS` (2545–2801), boundary-cover planning and `APPLY_PIPELINE_PLACEMENTS`. Continuous delay estimates become discrete legal bit/operation boundaries. Reconvergent paths require coherent placement; requested cut count differs from actual added latency.
3. **Path ownership and decisions** — MAIN role queries, failure classification and synthesis observations. A path can cross a MAIN without being repairable by adding latency there. The current crossing/endpoint distinction is valuable. Its repeated use in feedback, confirmation and reporting creates opportunities for inconsistent interpretations.
4. **Persistent latency evidence** — `RESOLVE_LATENCY_MEMORY`, subtree digests, hints and concrete locks. Reparse changes instance labels and sometimes types. Reusable memory needs semantic compatibility, while an exact lock needs physical compatibility. Restoring either by an insufficient key can silently overconstrain a new design.
5. **Accounting and termination** — `RECORD_SYNTHESIS_OBSERVATION` (9237–9403), implementation signatures and synthesis budgets. Planning attempts, actual tool calls and reused observations are distinct. A repeated physical implementation should not consume unnecessary tool runs or falsely imply progress.
   - Observed on the working tree on top of `deac5d21`: the plateau stop (`AT_PLATEAU`) needs a flat fmax, so a falling one does not end the sweep. The case was `sweep_floor_detect_design.py` on sky130, built with a reset pin under `reset_registers="all"` (`-D SWEEP_FLOOR_DETECT_MHZ=100`).
   - fmax went 49.78 → 44.94 → 34.54 → 23.10 MHz while cuts grew 26 → 65: each replan's registers lengthened the reset pin's fanout net, which was the critical path. `RESET_DISTRIBUTION_PATH` names those paths, but `RESET_PATH_STOPS_PLAN` keeps the feedback, as iteration 5 did better.
   - Eight more replans then reused the same implementation without a tool run, and the sweep stopped at iteration 17 (`no_realized_change`).
   - The best result, 49.78 MHz, was kept. The cost was three wasted, growing syntheses (1:16, 1:48 and 3:14) and eight planning iterations.
   - Suspected gap: no stop for "more cuts, lower fmax" over consecutive iterations, for whatever net (a reset, a clock enable, a select) grows with the register count.

## Duplication and simplification

The large opportunity is to reduce independent state variables, not split the 1,742-line function into arbitrary helpers. Define a complete `Candidate` snapshot (timing table, placements, locks, regions, MCP counts, identity), an immutable `Observation`, and an explicit action such as refine, measure, trim, restore or stop. A pure decision function returns the next action; one executor applies it.

Use one path-classification result for feedback, confirmation and history. Keep typed placement objects; the older scalar-cut vocabulary should remain only where required as an adapter. Consolidate repeated floor calculations and landscape traversal, but preserve the semantic difference between optimistic estimates and hard legality bounds.

Moving the internal placement experiment interface out of the main planner improves navigation but does not itself reduce total code. Remove obsolete policy paths only after proving that current callers and benchmark use no longer need them. MLIR does not replace the vendor feedback policy here.

## Validation

No new failing sweep was reproduced. Replay recorded observations through extracted decisions and require identical actions, not just identical final MHz. Test rollback restores the whole implementation; unrelated passing MAINs retain placement; missing paths cannot establish success; repeated signatures do not trigger duplicate synthesis. Compare QoR and tool-run counts on identical cold/warm baselines before deleting a policy branch.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

