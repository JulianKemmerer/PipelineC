# AUTO_PIPELINE complexity review

Pipeline representation, stage maps, HDL register lifetimes, explicit latency regions and the latency confirmation loop. Read [AUTO_PIPELINE design](../../AUTO_PIPELINE_DESIGN.md); SWEEP chooses placements while this module makes them physical.

Source: [AUTO_PIPELINE.py](../../../src/AUTO_PIPELINE.py). This is a targeted structural review of the working tree based on commit `9eafa7d8`, including concurrent multi-clock changes. Function names are the stable navigation aid; line numbers describe the measured snapshot. Suspected failure cases are not confirmed bugs unless explicitly labeled.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 5,174 | 3,768 | 131 | 19 | 119 |

Highest-scoring functions: `GET_PIPELINE_MAP` (905–1933, CCN 119); `__init__` (4895–5168, CCN 79); `GET_PIPELINE_MAP.PIPELINE_DONE` (1274–1379, CCN 38).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Stage construction** — `GET_PIPELINE_MAP` (905–1933). It propagates availability through wires, constants, clock enables, state, feedback, global wires and child instances. Nested helpers share many mutable collections; `PIPELINE_DONE` alone has substantial branching. A termination mistake can hang mapping or omit a required output; an availability mistake causes transaction misalignment.
2. **Register lifetime calculation** — `PiplineHDLParams.__init__` (4895–5168). Per-stage reads/writes become inclusive register ranges. Inline VHDL expressions/functions, volatile globals and aligned global IO need special treatment because they do not all have ordinary named wires. Off-by-one start/end rules can alter latency while leaving combinational results correct.
3. **Constrained regions** — `_ENFORCE_ONE_AUTO_PIPELINE_REGION` (4464–4580). Requested cuts are not realized cycles; retries reset a region, place cuts, remove non-deepening placements and recompute latency. Fixed constraints, caps, remembered floors and FSM-owned placements interact. Reusing a landscape after its timing table changes needs explicit validity rules.
4. **Timing identity and reuse** — `TimingParams`, zero-clock caches, `CAPTURE_CONCRETE_PIPELINE`/`RESTORE_CONCRETE_PIPELINE`. Mutable slices, exact bit boundaries, IO flags and child latency influence both placement and entity names. Cache keys must describe physical implementation and must not retain a previous parse's Logic.
5. **Pin-and-confirm orchestration** — `DO_AUTO_PIPELINE_LATENCY_PASSES` and build entry points. Discovered latencies change Python-generated design structure, forcing re-elaboration. Pipeline, MCP, RAM and FSM selections must all refer to the same generation.

## Duplication and simplification

`FUNC_SUBTREE_HAS_AUTO_PIPELINE` and AUTO_FSM's analogous predicate share structure. Stage/global/clock classifications are repeated in VHDL rendering. Share a derived `PipelineLayout` containing wire lifetimes, IO banks, aligned globals and clock enables, and render only from that validated result.

Separate dependency scheduling, register liveness and presentation. A worklist/topological availability engine with explicit latency-bearing edges could replace the large propagation routine; state and feedback are boundary inputs, not combinational cycles to schedule. Use a graph revision plus a timing-plan identity for cached layouts.

Represent fixed, minimum and maximum latency as one constraint record shared with pypeline/LOGIC rather than repeated tag-field interpretation. Keep actual placement verification: a smaller planner is not useful if it merely assumes each requested cut adds one cycle.

## Validation

No new defect was reproduced. Validate unequal reconvergent child latencies, read-only initialized registers, CE alignment, global reads/writes, fixed user pipelines and exact raw-leaf splits. Assert requested versus realized placements and inclusive lifetime bounds. Use latency-derived array sizes and nested constrained regions to check reparse convergence and complete rollback.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

