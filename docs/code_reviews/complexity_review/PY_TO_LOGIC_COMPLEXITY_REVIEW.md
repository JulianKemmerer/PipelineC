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

Global wire writers and readers have one table, `ParserState.global_wire_access` (`LOGIC.BUILD_GLOBAL_WIRE_ACCESS`). The rule had been derived at about a dozen sites (found on the tree after commit `f862ed6f` while adding the design diagram), each combining its own subset of the per-function access records (`write_only_global_wires`, `read_only_global_wires`, `state_regs`, `readback_global_wires`, `global_wire_driven_paths`, `global_wire_dynamic_index_writes`, `global_wire_write_locs`, `global_wire_read_paths`) with `FuncToInstances`. The table holds one `GlobalWireUse` per function and wire, built once after trimming and again after late MAINs. `_assign_clocks`, `_check_global_insts`, `_check_clock_crossings`, `_assign_resets`, the global-wire rule block of `PARSE_FILE`, the native pipeline evaluator, `VHDL.GLOBAL_WIRE_CONNECTIONS` (with the user clock wires, `MAIN_RESET_SOURCE_TEXT` and the package predicate), `DIAGRAM._links` and its wire stubs, and `SWEEP.RESET_DISTRIBUTION_PATH` read it. The copies had disagreed: the package predicate did not follow the port predicate (a readback in a design with no shared wire gave invalid VHDL, #384), the top level looped over unsorted instance sets (`top.vhd` changed with `PYTHONHASHSEED`, #380), the diagram drew no link for a variable-index write when its writer also wrote a constant field, and the sweep's reset-path classification did not count a writer's readback as a read (so a reset MAIN reading back the source MAIN's field of a split wire was classified as reset fanout). What still reads the per-function records directly is one function's own contract (its record ports, purity and timing alignment: `LOGIC_NEEDS_GLOBAL_TO_MODULE`, `AUTO.FIND_EFFECTS`, `SIM`, AUTO_FSM's purity check) and the C front end's instance-array wiring in `VHDL.WRITE_MULTIMAIN_TOP`, which reads `used_in_funcs` and loops over unsorted sets (its `top.vhd` order still depends on `PYTHONHASHSEED`, #403 in the [issues inventory](../../issues_inventory.md)). The table's domain is the wire's `used_in_funcs` rather than a scan of the Logic table, because the C front end drops FSM duplicates from `used_in_funcs`; `global_wire_access_test.py` checks that the two agree for Pypeline designs. A C parser-state cache written before the table existed is a miss. `parser_state.file_to_module_prefix` was set by `PARSE_FILE` without a declaration and read with `getattr`; it is now declared in `LOGIC.ParserState` with `pypeline_file_imports`.

A function that writes some fields of a global wire it also reads elaborates the write as a `CONST_REF_RD` assembly over the read-back value (tree after commit `70922c58`, found while drawing global wire stubs in the design diagram): the read-back drives the assembly's whole-variable input and each written field overrides its part, so `wire_drives` shows the fields the function does not write flowing from its read to its write. No hardware drives those fields from that function; only `global_wire_driven_paths` says which parts the write really drives (VHDL connects only those), and a graph consumer has to check it. `DIAGRAM` does (a write stub's `driven`, and an assembly's longer input paths overriding a shorter one's). Recording the overridden parts on the assembly, or not wiring the read-back into it, would let the graph say what the hardware does.

Type descriptions are parse state with no declaration, and an interface half's role does not survive into it (tree after commit `a4440697`, found while adding interface roles to the design diagram). `PARSE_FILE` assigns `pypeline_name_descriptions`, `pypeline_type_canonical`, `pypeline_user_names`, `pypeline_type_identities` and the other `pypeline_*` tables at its start rather than `LOGIC.ParserState` declaring them, so `DIAGRAM._Types` reads them with `getattr`. A type's interface role lives on the Python class (`_pypeline_interface_role`); the parse keeps only the description kind (`interface_fwd` / `interface_fb`) of the halves themselves. `interface_func._plain_shape_of` copies a half into a role-less `<half class>_plain` struct for the `Feedback`s it generates, so the diagram recovers a copy's role by matching its fields against the halves' and its half by C-name prefix ([DIAGRAM_DESIGN.md](../../DIAGRAM_DESIGN.md#types-and-interface-roles)). Recording, where `_register_struct_recursive` registers a type, its role and the half a plain copy stands for in a declared table would make both exact. `pypeline_operator_impl_ops` (registered operator implementation → the operators dispatched to it, every dispatch site since the tree after `70922c58`; it was `pypeline_compare_impl_ops`, comparisons only) is another such table: AUTO reads it for comparisons and `DIAGRAM` to draw a call as the operator the source wrote, both with `getattr`. It is per callee, not per call site, so a direct call to the same specialization looks like an operator. The names a design's modules give its types (`aead_axis_if_t = make_stream_interface(...)`) are not recorded at all (tree after commit `dd3b3204`): `DIAGRAM._module_type_names` walks the other design files' modules in `sys.modules` and, for the top file, which `PARSE_FILE` runs with `module_from_spec` outside `sys.modules`, the globals `_new_parser_state` keeps in `top_level_module_globals`, again set without a declaration.

The module-discovery walk reaches host-only libraries as well as hardware types
(tree based on `9b2cb7cb`, issue [#394](https://github.com/JulianKemmerer/PipelineC/issues/394)).
`_register_struct_recursive` cannot treat the existence of `__annotations__` as
evidence of typed fields: Python 3.10+ supplies an empty dictionary on untyped
`collections.namedtuple` classes, including `statistics.LinearRegression` imported
by `stream_perf`. The registration gate requires nonempty annotations;
`untyped_namedtuple_test.py` reproduces the old GHDL package rejection and checks
that typed and nested structs survive. Discovery still walks host modules; this
guard does not consolidate the registration paths described above.

The `@MAIN` registry had seven direct readers and no shared filter (tree after commit
`84685d25`, found while making `@MAIN` over `@sim_output`/`@sim_input` a simulation-only
MAIN). `PARSE_FILE` Step 3 (`main_func_ids`, `main_raw_ids`), `_elaborate_registered_mains`,
`_assign_clocks`, `_design_clocks`, `_assign_resets` and `ELABORATE_LIVE_ROOTS` each read
`pypeline._main_registry` themselves. Native sim runs every registered MAIN while
elaboration must see only the hardware ones. `pypeline.HARDWARE_MAINS()` is the filter and
each of those readers calls it; `pypeline_sim.run_sim` keeps the raw registry on purpose.
A reader added later still has to choose between the two by hand, and the tests catch only
part of a wrong choice. `sim_input_output_elab_test` fails when no reader filters:
`_elaborate_registered_mains` then elaborates a Python-only body. No test checks the
other readers one at a time, and none fails for the reverse mistake in a place that must
see every MAIN.

The `sim_print`/`sim_assert` message is an internal C-printf string with no single owner
(working tree based on `ec3eee13`, found while making native and VHDL prints agree).
`_build_sim_fmt_string` encodes it: it escapes literal `%` as `%%`, picks `%X`, `%c`, `%s`,
`%d` or `%u` per interpolation, and rejects forms whose Python rendering differs from the
hardware's. `LOGIC.PRTINTF_STRING_TO_FORMATS` decodes it into the argument list, and
`VHDL.PRINTF_FORMAT_TO_VHDL_STRING` into the VHDL text. Native simulation never reads it: it
prints the f-string Python evaluated, through `pypeline.hex`, `CharArray.__str__` and
`int.__str__`. A new escape, specifier or accepted form must change all four places
together, and only the native-versus-VHDL diffs (`sim_print_hex_signed_test`,
`sim_print_decimal_test`) check them against each other. The accepted forms are listed in
[pypeline_sim_DESIGN.md](../../pypeline_sim_DESIGN.md#sim_print--printf-style-console--hardware-output).

## Validation

Use branch/loop partial struct writes, nested arrays, dynamic indices, hardware-local shadowing and custom operators as differential cases. Verify exceptions preserve original helper diagnostics and helpers are not evaluated repeatedly after classification. Compare cold/warm/reparsed builds, emitted type identities, source locations and clock crossing reports. The [constant-evaluation probe](REVIEW_EXPERIMENTS.md#constant-evaluation-outcomes) is a method-level experiment, not a complete design compile.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

