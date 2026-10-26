# pypeline_sim complexity review

Native single-clock simulation orchestration. The actual AST rewrites and arithmetic runtime live in pypeline.py; read [simulation design](../../pypeline_sim_DESIGN.md) and the [API review](pypeline_COMPLEXITY_REVIEW.md).

Source: [pypeline_sim.py](../../../src/pypeline_sim.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 627 | 390 | 13 | 1 | 40 |

Highest-scoring functions: `run_sim` (75–324, CCN 40); `_convergence_loop` (428–466, CCN 9); `_discover_wire_names._scan` (484–502, CCN 9).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Run lifecycle** — `run_sim` (75–324, CCN 40). Mode flags must be set before import; harvested schedules, latencies and RAM plans must be installed before tag construction; modules may be imported again for target-specific RAM geometry. State reset and hook behavior span several modules.
2. **Convergence and simultaneous state** — `_run_clock_cycle` (382–425), `_convergence_loop` (428–466). Deferred global writes are applied, sim-input results memoized, MAINs reevaluated, observable outputs run once and register writes committed together. A side effect during convergence or a mutable value escaping a write snapshot can make execution order affect results.
3. **Simulation instance identity** — `_call_main`, wire discovery and global-instance construction. Reused factory functions need distinct MAIN roots and call-site frames so they do not share state. Discovery recovers live Python wiring through private pypeline data.
4. **Partial latency emulation** — queueing whole pure-MAIN results versus per-call-site pipeline models. These are different models with explicit limitations. Multi-clock native simulation is refused; adding a clock loop alone would not solve cross-domain event semantics.

## Duplication and simplification

Use a `SimulationSession` that owns imported design state, clocks, pending writes, readers, input caches and finalization. Today the runner reaches into dozens of private pypeline attributes. Make import/reset/run/finalize explicit lifecycle methods and share design discovery with elaboration.

At this snapshot, RAM plan installation uses `plans or {}`, while AP/FSM/MCP caches are installed only when incoming mappings are truthy. That asymmetry is a **suspected repeated-run isolation problem**: a second same-process run with absent/empty selections may retain prior selections. Verify against intended caller ownership before changing it.

Generalize the existing Logic pipeline interpreter into a reference simulator to reduce duplicated language semantics. Keep the fast Python path if measured performance warrants it, using differential tests to maintain equivalence.

## Validation

Test two runs in one process, empty overrides after populated overrides, hook failures, convergence failure cleanup, factory-shared MAINs and queued mutable aggregates. Compare final-pass effects and simultaneous register updates against VHDL. No new end-to-end simulation failure was reproduced; the single-clock limitation is documented behavior.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

