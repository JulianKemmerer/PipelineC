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
   `hw_func` builds this simulator (`_sim_type_wrap`, `_build_reg_sim_func`) when a
   function is decorated, so each function the elaborator generates (soft-operator
   factories, AUTO_COMB_OPT candidates) pays for a simulation that never runs in a
   build: 690 calls, 10.6 s of the 51 s profiled first parse. Measured with cProfile on WireGuard's shared default profile (`chacha20poly1305_encrypt_decrypt_shared`, 256 bits, 80 MHz), first parse plus zero-added-clock render, working tree on `f0471102`: 100 s profiled, 68 s without the profiler.
3. **Process-global lifecycle** — API registries, latency/schedule caches, simulation state and `CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG`. The handoff counted 79 module-level mutable registry/cache assignments; that is a heuristic count, not 79 independent concepts. Reset responsibility is spread across this file, `PY_TO_LOGIC.PARSE_FILE` and `pypeline_sim.run_sim`. Persistent build choices and transient parse objects need different lifetimes. `RESET_AUTO_MULTI_CYCLE_TRACKING` (tree after `edfb902a`) resets every per-execution AUTO table, AUTO_PIPELINE names, latency seeds and AUTO construction sites and reads among them, so its name understates what callers rely on it for. The clock-goal tables (`_auto_site_bindings`, `_auto_split_keys`) deliberately outlive a parse and are owned by `PY_TO_LOGIC.PARSE_FILE`, while `_auto_run_goal` is owned by `pypeline_sim.run_sim`.
4. **Identity and stack inspection** — `_stable_key` (255–396), `capture_factory_args` (1781 onward), `_latency_read_site`. Identity recursively inspects closures and object dictionaries; factory metadata is recovered from live frames. Reassigning a factory parameter before decoration can make the captured description represent its current value instead of the supplied argument. Bytecode-based identity also makes Python interpreter changes relevant to caches. Two identical factory calls produce equal identities, so their products elaborate as one function (`PY_TO_LOGIC._elaborate_live_func` reuses the first); per-object decisions are only possible after that merge is undone. On the tree after `edfb902a`, `_stable_key`'s AUTO branch adds a split component from installed module state (`_auto_split_component`), so a tag's identity depends on the goal tables `PARSE_FILE` installed as well as on the tag, and `_auto_construction_site` adds a frame walk to every AUTO construction.
5. **Latency tag implementations** — `AUTO_PIPELINE`, `AUTO_FSM`, `AUTO_MULTI_CYCLE`. Each combines public API validation, identity, construction-time lookup, read tracking and simulation behavior. Key suffixes must agree with the corresponding LOGIC metadata classes. A seemingly local change has several consumers. The shared helpers duck-type the tags with no common base: `_require_built` reads `tag.binding_key`, which `c2909b40` gave AUTO_PIPELINE and AUTO_FSM only. Until AUTO_MULTI_CYCLE got one too, reading an undecided AUTO_MULTI_CYCLE while replaying built hardware raised `AttributeError` instead of `BuiltHardwareError` (now covered by `auto_multi_cycle_unit_test::test_built_hardware_replay_reads`).

## Duplication and simplification

**Confirmed defect: scoped registrations can attach to unrelated functions.** Registrations store `id(scope)` without retaining or weakly tracking the scope object. After collection, CPython reused that address for an unrelated function; pushing its scope installed the old NEGATE implementation. The [experiment](REVIEW_EXPERIMENTS.md#scoped-operator-identity-reuse) reproduced this in the current tree. The address reuse is allocator-dependent, but the ownership error is concrete. Re-parsing and generated helper factories make short-lived callables relevant. No end-to-end miscompiled user design was demonstrated. A test symptom (tree after commit `70922c58`): `auto_comb_delay_opt_test` failed once in a parallel `--category unit --category elab_introspect --category elab -j 4` run, its mux case's second `PARSE_FILE` reporting "scoped operator implementations retained" where the first did not, and passed in five runs alone. `AUTO_COMB_OPT`'s purity gate tests `id(callable) in pypeline._scoped_funcs`, and AUTO registers operators with `scope=fn` for generated constant wrappers (`AUTO.py`, the `primitive` branch) that a later case's parse frees, so a reused address is the likely cause (suspected; not reproduced on demand).

Use one `OperatorRegistry` with operator-kind data, explicit precedence and a scope context manager. Key scope entries by callable identity with a deliberate ownership policy: weak keys if values cannot retain their keys, or strong keys owned by a build session. Preserve library defaults separately from per-design registrations; indiscriminately clearing all registries would break cached imports. Consolidate the near-identical left/unary registration functions and generic resolvers first.

Introduce a `DesignSession` owning registries and immutable build selections, plus a separate `SimulationSession`. Capture source/AST once in a function descriptor and prepare simulation lazily. A typed operator specification should supply promotion, truncation and evaluation rules to both elaboration and simulation. These are structural changes; merely splitting this file by topic would not remove duplicated semantics.

**Wire writes are cast to the wire's type; a struct built by `_replace()` is not** (finding made on the tree after commit
`0b710cca`, while adding waveforms; revalidated on `3d0b54af` plus the change that added `_GlobalWireRewriter._cast_to_wire_type`).
`_sim_wire_write` and `_sim_wire_lens_write` used to store the value as given, so what a reader saw depended on how the
writer spelled it: a comparison stayed a Python `bool` (`~q` was `-2`,
[#392](https://github.com/JulianKemmerer/PipelineC/issues/392)), a list literal stayed plain ints that `array_to_uint_le`
packed at their own bit lengths (`[1, 2]` gave 5 where GHDL gives `0x0201`), and a testbench's `ports.aad_len = AAD_LEN`
stayed an untyped int. Field and index writes were already cast; whole-wire writes (`wire = x`, `module.wire = x`,
`wire += x`, unpacked leaves) were not. The rewriter now wraps every one in `_sim_cast_deep(value, <ctype>)`
(`_cast_to_wire_type`), `axis_wave` and WireGuard's `port_waves` no longer cast, and
`native_sim:native_invert_compare_wire_test` asserts the hardware's answers for each shape.
One gap stays open. A struct-typed write is not wrapped (`_sim_cast_deep` returns structs as given), because
`@struct`'s typed constructor `_typed_new` types the fields when the struct is built; `NamedTuple._replace` and `_make`
bypass it, so a wire, typed local or `Reg` written with `s._replace(a=300)` keeps 300 in a `uint8_t` field
(`known_issues:native_struct_replace_cast_known_issue`,
[#401](https://github.com/JulianKemmerer/PipelineC/issues/401)). A `_make` that goes through `_typed_new` would close it, but
`_sim_lens_set` builds every struct field write with `_replace`, so it would re-type every field on every field write, a
cost not yet measured. The change also exposed a coupling: the synthetic ctype names the rewriter injects into the exec
namespace were keyed by source position, and `_lower_unpack` gives every leaf of one unpacking statement the statement's
position, so in `s.wide, s.narrow = ...` every leaf was cast to the type registered last (`wide=44` for 300 on the tree
before the change). The names are a per-rewriter serial. Cost: the six WireGuard native runs (encrypt,
decrypt and shared, each with the random and the fixed-vector testbench, `--comb`, one run each on both trees, the two
trees running side by side with two other jobs on four cores) took 487, 171, 570, 159, 566 and 213 s with the cast and
487, 171, 574, 162, 564 and 213 s before it, and printed identical output. The PDW testbench (`pdw_tb`, a wire-heavy design, the two trees
side by side as above) took 4839 s with the cast and 4858 s before it.

**`@interface` is part library, part `pypeline.py`, coupled by attribute names** (tree after commit `5b816e9d`, found while renaming the interface halves). The design documents call `@interface` a pure library construct (`include/pypeline/interface.py`), but this module names its halves (`_derived_type`, `_interface_half_symbol`), checks port pairing (`_check_partial_interface_ports`, `_interface_half_of`) and encodes interface parameters (`encode_param_value`), all by reading the stamps `interface()` sets: `_pypeline_is_interface`, `_pypeline_interface`, `_pypeline_interface_role`, `_pypeline_iface_derived` and `_pypeline_iface_canonical`. `PY_TO_LOGIC`, `DIAGRAM`, `interface_func` and `stream.stream` read some of the same stamps. Nothing declares them in one place, so a change to what an interface carries means finding every reader by grep. The half names show the cost: `interface._derive` builds the half class names (and so their C type keys) and `_derived_type` here builds their VHDL descriptions, and at `5b816e9d` the two used different suffixes (`<name>_t`/`<name>_feedback_t` against `<name>_fwd_t`/`<name>_fb_t`). `_interface_half_symbol` is the one rule both use. One small record type for the stamps, defined here and filled by `interface()`, would give the readers one definition.

## Validation

Reproduce scope reuse and nested scope push/pop, including exceptions and generic/exact/INFERRED precedence. Parse two different designs in both orders within one process, then compare results with fresh processes. Preserve strict arithmetic, signed division/modulo, narrow shifts, per-instance state and simultaneous register commits with native-versus-VHDL tests. Benchmark decoration/import cost separately from steady-state simulation before making laziness a performance claim.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

