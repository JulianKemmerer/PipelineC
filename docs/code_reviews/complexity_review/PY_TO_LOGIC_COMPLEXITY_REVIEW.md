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
5. **Global wiring and clocks** — `_discover_global_wires`, `_assign_clocks` (7785–7976), crossing and global-instance checks. Names, partial paths, writer/reader ownership, explicit clocks and inferred clocks meet here. The working tree's multi-clock changes increase the importance of leaf-level ownership tests. LOGIC's old clock inference is C-only; the current LOGIC design doc now says so correctly. Elaboration has no MAIN or clock context (found on the tree after commit `259575a7`): `PARSE_FILE` Step 7 elaborates every top-level def once, as a template shared by every MAIN, before the instance walk and `_assign_clocks`. Anything that must differ per clock goal (an AUTO_FSM schedule per goal, say) needs ownership carried from an earlier parse and a distinct function per goal for every shared caller. On the tree after `edfb902a`, `PARSE_FILE` is a loop around `_PARSE_FILE_ONCE` that settles AUTO goal tables from the previous parse: separate objects per clock domain get their own bindings, and identical factory products holding them are split by goal set (up to two extra parses). One object used at several goals still has one implementation, for the reason above.
6. **Simulation embedded in elaboration** — `_SimPipelineGraph`, `PREPARE_PIPELINE_LATENCY_SIM` at the file's end. A Logic interpreter decodes operations through AUTO and evaluates some operators again. This is a useful seed for a reference IR simulator, but it is not yet a general replacement for native simulation.

## Duplication and simplification

Registered binary/comparison dispatch is repeated in `_elab_binop` and `_elab_compare`; variable-index read/write builders share dimension and condition construction; branch clock-enable mux construction is mirrored. Interface-half diagnostics and global-instance path collectors repeat too. Consolidate typed operations and traversal helpers before changing syntax semantics.

The larger reduction is **whole-aggregate SSA with explicit extract/insert operations**: preserve a value for the entire aggregate and merge that value at a branch. Lower dynamic inserts to muxes later. This can replace coverage bookkeeping instead of hiding it behind a class, but must preserve partial initialization and out-of-range behavior. Add a normalization pass for augmented assignment, unpacking and conditional expressions, retaining original source locations.

A session-owned function descriptor should hold frozen AST, annotations, closure bindings, source origins and operator scope. Latency-dependent Python still needs re-execution when it changes topology; optimize reuse of unaffected functions rather than promising to eliminate all reparses. The [scoped-registration defect](pypeline_COMPLEXITY_REVIEW.md#duplication-and-simplification) makes lifecycle cleanup urgent.

Two name-resolution gaps found while adding resets (tree after that feature):

- `_discover_global_wires` reads only the top-level `AnnAssign` nodes of a module body, so a global declared inside a module-level `if`/`try` (a fallback for host-side imports, say) is invisible to elaboration while native sim, which reads `__annotations__`, still sees it. WireGuard's `wireguard_env.py` needed stand-ins in its `except ImportError` branch to keep its reset pin top-level. Discovery could walk module-level `if`/`try` blocks the way conditional-import discovery does.
- `_try_eval_const` evaluates a name against module globals, so a global wire whose module global holds what it is bound to (a `_Reset`, a clock pin's `_Clock`) folded to that Python object: `if rst:` built always-true logic. `_refs_bound_wire` now declines those. A `Fifo[T]`'s initializer object is in the same position and escapes only because its attribute reads raise (suspected latent hazard).
- Only `reset` among the compiler's implicit entity port names is renamed by `_sanitize_vhdl_name` (`_IMPLICIT_PORT_NAMES`); a user local or argument named `clk` or `CLOCK_ENABLE` still collides with the entity's port of that name (suspected; not reproduced).

Struct registration has no single owner (tree after the reset work). `_register_struct_recursive` is called from `_discover_structs_from_module` (module globals), `_resolved_annotation_to_ctype` and `_inner_ctype_to_str` (annotations, and `Reg[T]`/`Wire[T]` inner types), `_elaborate_live_func` (closure variables), `_elab_cast_call` (cast targets) and the unannotated-constructor branch of `_elab_assign`, which lacked it: `c = mag.complex_t(...)`, a factory's struct reached only as an attribute, crashed with a `KeyError` in `_ref_toks_to_ctype` until that branch registered it (regression case in `inst/compound_init_test.py`). Any other path that declares a local from a type object, without an annotation, can have the same gap; registering wherever a type becomes a C type name (one hook in `_resolved_annotation_to_ctype`'s callers) would close the class.

Global wire writers and readers are derived four times (tree after commit `f862ed6f`, found while adding the design diagram). `_assign_clocks`, `_check_global_insts` and `_check_clock_crossings` each collect, per global wire, the functions that drive which leaf paths (`global_wire_driven_paths`) and read which (`global_wire_read_paths`, with readback wires mapped back), and match them with `_path_overlaps`. `VHDL.WRITE_MULTIMAIN_TOP` ("Directly connected global wires") finds writers again from `used_in_funcs`, `write_only_global_wires` and state regs. `DIAGRAM._links` is a fifth, private copy of the same rule. One writer/reader table per wire, built once after elaboration and read by all five, would keep them from drifting. `parser_state.file_to_module_prefix` was set by `PARSE_FILE` without a declaration and read with `getattr`; it is now declared in `LOGIC.ParserState` with `pypeline_file_imports`.

Type descriptions are parse state with no declaration, and an interface half's role does not survive into it (tree after commit `a4440697`, found while adding interface roles to the design diagram). `PARSE_FILE` assigns `pypeline_name_descriptions`, `pypeline_type_canonical`, `pypeline_user_names`, `pypeline_type_identities` and the other `pypeline_*` tables at its start rather than `LOGIC.ParserState` declaring them, so `DIAGRAM._Types` reads them with `getattr`. A type's interface role lives on the Python class (`_pypeline_interface_role`); the parse keeps only the description kind (`interface_fwd` / `interface_fb`) of the halves themselves. `interface_func._plain_shape_of` copies a half into a role-less `<half class>_plain` struct for the `Feedback`s it generates, so the diagram recovers a copy's role by matching its fields against the halves' and its half by C-name prefix ([DIAGRAM_DESIGN.md](../../DIAGRAM_DESIGN.md#types-and-interface-roles)). Recording, where `_register_struct_recursive` registers a type, its role and the half a plain copy stands for in a declared table would make both exact.

## Validation

Use branch/loop partial struct writes, nested arrays, dynamic indices, hardware-local shadowing and custom operators as differential cases. Verify exceptions preserve original helper diagnostics and helpers are not evaluated repeatedly after classification. Compare cold/warm/reparsed builds, emitted type identities, source locations and clock crossing reports. The [constant-evaluation probe](REVIEW_EXPERIMENTS.md#constant-evaluation-outcomes) is a method-level experiment, not a complete design compile.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

