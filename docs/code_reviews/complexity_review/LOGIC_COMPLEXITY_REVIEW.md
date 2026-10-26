# LOGIC complexity review

The shared representation used by the Python front end, synthesis, scheduling and VHDL emission. [LOGIC design](../../LOGIC_DESIGN.md) explicitly distinguishes C-only methods from shared passes; raw complexity rankings alone would over-prioritize the legacy merge functions.

Source: [LOGIC.py](../../../src/LOGIC.py). This is a targeted structural review of the working tree based on commit `9eafa7d8`, including concurrent multi-clock changes. Function names are the stable navigation aid; line numbers describe the measured snapshot. Suspected failure cases are not confirmed bugs unless explicitly labeled.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 3,959 | 2,746 | 124 | 8 | 82 |

Highest-scoring functions: `MERGE_COMB_LOGIC` (742–1122, CCN 82); `C_BUILT_IN_FUNC_IS_RAW_HDL` (1842–2062, CCN 69); `TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE` (2945–3283, CCN 52).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Graph mutation and metadata consistency** — `Logic.__init__`, `DEEPCOPY`, `REMOVE_SUBMODULE`, `COPY_SUBMODULE_INFO`, `CONNECT_WIRES_LOGIC`. Wires, types, forward/reverse edges, instance ports, source origins and tag metadata live in parallel containers. A mutation can leave a graph that looks locally valid but loses a clock, latency constraint or source attribution later. Copying each new field manually is a recurring maintenance hazard.
2. **Trim, wire collapse and common instances** — `TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE` (2945–3283). Recursion, dead-wire removal, fixed-point rewiring, typed comparisons, clock enables, tag-sensitive identity and global instance renaming happen together. Only one duplicate group is collapsed per iteration, requiring repeated whole-graph scans. Common-instance legality must include observable effects and all hardware-affecting metadata, not just equal inputs.
3. **Implicit operation/type semantics** — `C_BUILT_IN_FUNC_IS_RAW_HDL` (1842–2062), `BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC` and the name/type predicates. Despite the C names, Python builds use these. Operator kind, constants, types and hierarchy are recovered from strings. A spelling or suffix change can alter dispatch and timing attribution. Unsupported built-ins must respect the Pypeline no-C-fallback guard.
4. **Caches tied to mutable graphs** — trim completion and clock-enable queries are keyed by function name. Rebuilding the body under that name, as AUTO_FSM does, invalidates the answer even when the name is stable. Module-wide clearing works only when every entry point remembers it.
5. **Legacy code in the same representation** — `MERGE_COMB_LOGIC` (CCN 82), `MERGE_SEQ_LOGIC`, `INFER_CLOCK_DOMAINS`. These are C-front-end paths, not primary Pypeline hotspots. Do not spend the first refactor simplifying them just because they score highly.

## Duplication and simplification

Repeated field-copy/update blocks and near-identical VHDL-expression/function-port checks are real consolidation opportunities. The three hierarchy predicates in LOGIC/SYN, AUTO_PIPELINE and AUTO_FSM can share traversal with distinct queries and revision-scoped memoization.

Give a wire/value a stable identity, type and producer; make uses derived or updated through one graph API. Group instance metadata into one record so copying/removing an instance is complete by construction. Add a verifier for reciprocal edges, existing ports, type-compatible connections, unique drivers and consistent hierarchy indexes. Keep a compatibility adapter for old consumers while moving one shared pass at a time.

Typed SSA is attractive for the combinational portion. State, global effects and clocks need explicit operations or effect metadata before generic CSE/DCE is legal. MLIR cannot infer these contracts from current names. Move C-only fields/methods behind an adapter only when shared callers no longer depend on them.

## Validation

No new miscompile was reproduced here. Focus on metadata-preserving graph edits: copies must isolate mutable containers while intentionally preserving callable identity; duplicate tagged calls in different groups must remain distinct; effectful calls must not disappear. Verify graph invariants after elaboration and each rewrite, then compare emitted HDL and timing-path attribution.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

