# pypeline complexity review

The public HDL API, elaboration metadata and native simulation runtime all live in this module. Nearly every Python design depends on it. Read with [API design](../../pypeline_DESIGN.md) and [simulation design](../../pypeline_sim_DESIGN.md).

Source: [pypeline.py](../../../src/pypeline.py). This is a targeted structural review of the working tree based on commit `9eafa7d8`, including concurrent multi-clock changes. Function names are the stable navigation aid; line numbers describe the measured snapshot. Suspected failure cases are not confirmed bugs unless explicitly labeled.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 11,043 | 6,442 | 475 | 20 | 89 |

Highest-scoring functions: `_build_reg_sim_func` (9752–10249, CCN 89); `_stable_key` (255–396, CCN 37); `_value_description` (489–621, CCN 36).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Operator registration and scope restoration** — `register_operator`, `register_left_operator`, `register_unary_operator`, `register_mux`, `_push_scoped_registrations`, `_pop_scoped_registrations` (roughly lines 4600–5200). Four operator families maintain parallel exact/generic/scoped dictionaries, caches, dispatch gates and precedence counters. Correctness requires registration, lookup, native dispatch and restoration to agree. An exception or missed cache invalidation can change which hardware implementation a later call uses.
2. **A second language implementation for simulation** — `_build_reg_sim_func` (9752–10249), `_GlobalWireRewriter`, `_TypedAnnAssignRewriter`, `_SimLoopInstanceRewriter`, `_sim_type_wrap`. Source is inspected, parsed, rewritten and compiled to implement register reads/writes, feedback, instances, typed assignment and global wires. The elaborator implements these again. A new syntax feature can simulate correctly while elaborating incorrectly, or vice versa. Decoration does substantial simulation preparation even when the caller only wants HDL.
3. **Process-global lifecycle** — API registries, latency/schedule caches, simulation state and `CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG`. The handoff counted 79 module-level mutable registry/cache assignments; that is a heuristic count, not 79 independent concepts. Reset responsibility is spread across this file, `PY_TO_LOGIC.PARSE_FILE` and `pypeline_sim.run_sim`. Persistent build choices and transient parse objects need different lifetimes.
4. **Identity and stack inspection** — `_stable_key` (255–396), `capture_factory_args` (1781 onward), `_latency_read_site`. Identity recursively inspects closures and object dictionaries; factory metadata is recovered from live frames. Reassigning a factory parameter before decoration can make the captured description represent its current value instead of the supplied argument. Bytecode-based identity also makes Python interpreter changes relevant to caches.
5. **Latency tag implementations** — `AUTO_PIPELINE`, `AUTO_FSM`, `AUTO_MULTI_CYCLE`. Each combines public API validation, identity, construction-time lookup, read tracking and simulation behavior. Key suffixes must agree with the corresponding LOGIC metadata classes. A seemingly local change has several consumers.

## Duplication and simplification

**Confirmed defect: scoped registrations can attach to unrelated functions.** Registrations store `id(scope)` without retaining or weakly tracking the scope object. After collection, CPython reused that address for an unrelated function; pushing its scope installed the old NEGATE implementation. The [experiment](REVIEW_EXPERIMENTS.md#scoped-operator-identity-reuse) reproduced this in the current tree. The address reuse is allocator-dependent, but the ownership error is concrete. Re-parsing and generated helper factories make short-lived callables relevant. No end-to-end miscompiled user design was demonstrated.

Use one `OperatorRegistry` with operator-kind data, explicit precedence and a scope context manager. Key scope entries by callable identity with a deliberate ownership policy: weak keys if values cannot retain their keys, or strong keys owned by a build session. Preserve library defaults separately from per-design registrations; indiscriminately clearing all registries would break cached imports. Consolidate the near-identical left/unary registration functions and generic resolvers first.

Introduce a `DesignSession` owning registries and immutable build selections, plus a separate `SimulationSession`. Capture source/AST once in a function descriptor and prepare simulation lazily. A typed operator specification should supply promotion, truncation and evaluation rules to both elaboration and simulation. These are structural changes; merely splitting this file by topic would not remove duplicated semantics.

## Validation

Reproduce scope reuse and nested scope push/pop, including exceptions and generic/exact/INFERRED precedence. Parse two different designs in both orders within one process, then compare results with fresh processes. Preserve strict arithmetic, signed division/modulo, narrow shifts, per-instance state and simultaneous register commits with native-versus-VHDL tests. Benchmark decoration/import cost separately from steady-state simulation before making laziness a performance claim.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

