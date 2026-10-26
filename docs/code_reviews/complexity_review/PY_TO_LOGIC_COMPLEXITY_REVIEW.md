# PY_TO_LOGIC complexity review

This is the Python HDL front end and the highest-priority semantic review. [Its design document](../../PY_TO_LOGIC_DESIGN.md) explains the alias and aggregate machinery that dominates the implementation.

Source: [PY_TO_LOGIC.py](../../../src/PY_TO_LOGIC.py). This is a targeted structural review of the working tree based on commit `9eafa7d8`, including concurrent multi-clock changes. Function names are the stable navigation aid; line numbers describe the measured snapshot. Suspected failure cases are not confirmed bugs unless explicitly labeled.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 10,151 | 6,905 | 271 | 30 | 65 |

Highest-scoring functions: `_elab_assign` (2994–3267, CCN 65); `PARSE_FILE` (9133–9554, CCN 58); `_assign_clocks` (7785–7976, CCN 57).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Constant evaluation and assignment classification** — `_try_eval_const` (2258 onward), `_elab_assign` (2994–3267). `None` represents both a real Python value and any failed evaluation. A direct probe returned `None` for division by zero, an unknown name and literal None. This confirms diagnostic information is discarded; it does not establish a miscompile. Assignment separately probes the RHS and callee in several branches, so a failed or None-returning helper can be executed again. Classify once using `Constant(value)`, `HardwareDependent` and `EvaluationError`, retaining source information. Do not blindly rethrow every exception: hardware-call detection currently relies on evaluation failing.
2. **Partial aggregate assignment and branch joins** — `_reduce_driven_ref_toks`, `_read_branch_coverage`, `_elab_if`, `_emit_var_ref_assign`, `_emit_var_ref_rd` and their builders. An aggregate is represented by string paths, overlapping coverage tokens, aliases over time and descendant invalidation. Branch reads can temporarily replace `self.env`. Dynamic multi-dimensional writes must agree on index order, element types, untouched fields and branch defaults. These are stronger bug predictors than the length of the syntax dispatcher.
3. **Callable identity versus emitted names** — `_canonical_func_name`, `_specialization_identity`, `_stable_val_repr`, `CANONICAL_CALLABLE_KEY`, `EmissionNames` (roughly 560–1262). Semantic keys, readable names and collision avoidance are intertwined, with overlapping machinery in pypeline. `_elaborate_live_func` requests several naming variants. Calculate one semantic descriptor/digest, then render presentation variants from it; make operator scope and dependencies explicit inputs.
4. **Source and module lifecycle** — `_elaborate_live_func` (5671 onward), source-freezing/import-loader support, `PARSE_FILE` (9133–9554). Re-imports evict modules, reset selected registries, freeze source and rebuild hierarchy. This is where missed resets and mixed-generation callables surface. A parse is currently a coordinated mutation of Python's import state plus multiple compiler modules.
5. **Global wiring and clocks** — `_discover_global_wires`, `_assign_clocks` (7785–7976), crossing and global-instance checks. Names, partial paths, writer/reader ownership, explicit clocks and inferred clocks meet here. The working tree's multi-clock changes increase the importance of leaf-level ownership tests. LOGIC's old clock inference is C-only; the current LOGIC design doc now says so correctly.
6. **Simulation embedded in elaboration** — `_SimPipelineGraph`, `PREPARE_PIPELINE_LATENCY_SIM` at the file's end. A Logic interpreter decodes operations through AUTO and evaluates some operators again. This is a useful seed for a reference IR simulator, but it is not yet a general replacement for native simulation.

## Duplication and simplification

Registered binary/comparison dispatch is repeated in `_elab_binop` and `_elab_compare`; variable-index read/write builders share dimension and condition construction; branch clock-enable mux construction is mirrored. Interface-half diagnostics and global-instance path collectors repeat too. Consolidate typed operations and traversal helpers before changing syntax semantics.

The larger reduction is **whole-aggregate SSA with explicit extract/insert operations**: preserve a value for the entire aggregate and merge that value at a branch. Lower dynamic inserts to muxes later. This can replace coverage bookkeeping instead of hiding it behind a class, but must preserve partial initialization and out-of-range behavior. Add a normalization pass for augmented assignment, unpacking and conditional expressions, retaining original source locations.

A session-owned function descriptor should hold frozen AST, annotations, closure bindings, source origins and operator scope. Latency-dependent Python still needs re-execution when it changes topology; optimize reuse of unaffected functions rather than promising to eliminate all reparses. The [scoped-registration defect](pypeline_COMPLEXITY_REVIEW.md#duplication-and-simplification) makes lifecycle cleanup urgent.

## Validation

Use branch/loop partial struct writes, nested arrays, dynamic indices, hardware-local shadowing and custom operators as differential cases. Verify exceptions preserve original helper diagnostics and helpers are not evaluated repeatedly after classification. Compare cold/warm/reparsed builds, emitted type identities, source locations and clock crossing reports. The [constant-evaluation probe](REVIEW_EXPERIMENTS.md#constant-evaluation-outcomes) is a method-level experiment, not a complete design compile.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

