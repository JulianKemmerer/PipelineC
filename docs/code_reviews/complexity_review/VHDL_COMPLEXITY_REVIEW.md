# VHDL complexity review

The primary HDL renderer, used by Python builds for types, top-level connectivity, state and pipelined logic. Read [VHDL design](../../VHDL_DESIGN.md). Rendering correctness also determines synthesis-cache identity.

Source: [VHDL.py](../../../src/VHDL.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 7,500 | 6,074 | 70 | 15 | 203 |

Highest-scoring functions: `WRITE_MULTIMAIN_TOP` (417–1815, CCN 203); `GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT` (6617–7186, CCN 93); `GET_PIPELINE_ARCH_DECL_TEXT` (6195–6612, CCN 67).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Top-level assembly** — `WRITE_MULTIMAIN_TOP` (417–1815, CCN 203). Clock ports, ordinary MAIN IO, global instances, FIFOs, arbitration and clock-crossing connections are decided while concatenating text. Connection planning and text rendering are inseparable, making partial-path or clock-domain mistakes hard to isolate. The global-wire section is the exception: `GLOBAL_WIRE_CONNECTIONS` plans it as `TopAssignment` records from `ParserState.global_wire_access`, and `WRITE_MULTIMAIN_TOP` only renders them and runs the clock check. The C front end's instance-array wiring after it still reads `used_in_funcs` and loops over unsorted sets of globals and reader instances, so `top.vhd` changes with `PYTHONHASHSEED` for a design with two `INST_ARRAY` globals on one side or two readers of one (not for `examples/instance_array.c`, which has one of each): #403 (see the [issues inventory](../../issues_inventory.md)) and `known_issues:c_inst_array_order_known_issue`.
2. **Pipeline architecture and process** — `GET_PIPELINE_ARCH_DECL_TEXT` (6195–6612), `GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT` (6617–7186). Both classify register banks, state, globals, clock enables, raw HDL and inline operations. Declarations, sensitivity lists, register liveness and assignments must describe the same circuit. A missing sensitivity dependency is a simulation failure even if synthesis recovers the intended logic.
3. **Clock-crossing entities** — `WRITE_CLK_CROSS_ENTITIES` (2328–3381). Vendor versus built-in FIFO implementations and other crossing shapes use large repeated templates. Clock and reset assumptions must match the Python front end's checked crossing records; this is a high-impact part of the concurrent work.
4. **Type packages and conversions** — `WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE`, `_WRITE_GROW_ONLY_C_STRUCTS_PACKAGE`, connection conversion helpers. Recursive arrays/records/enums, dependency ordering, case-insensitive names, widths and signedness meet here. The grow-only package sidecar exists partly to stabilize files across re-elaboration; a type redefinition must reset incompatible chunks. Type ordering alone does not ensure legal constant initialization: at `99e5e018`, `C_TYPE_STR_TO_VHDL_NULL_STR` called an enum conversion whose body was not elaborated until after the package declaration. The helper emits the first member's numeric encoding through `CONST_VAL_STR_TO_VHDL`; `enum_null_test.py` rejects the old branch with GHDL `-Werror=elaboration` and checks the default values. Keep declaration-time expressions independent of package-body functions when extending aggregate initialization.
5. **Artifact identity** — `WRITE_LOGIC_ENTITY`, `GET_ENTITY_NAME`. A physical entity name must determine its text. Planner-only state must not leak into rendered content under a reused name. This invariant is already documented and should be enforced at the emitter boundary.

## Duplication and simplification

Mirrored read/write clock-crossing connection loops and similar normal/crossing entity connections can share a port-map builder. Repeated register/global predicates should come from AUTO_PIPELINE's validated layout rather than being recomputed in declarations and processes.

First produce typed `TopConnections`, `EntityInterface` and `PipelineLayout` data; then render them. A small VHDL builder for declarations, associations and statements would remove delimiter trimming and string surgery. Keep specialized raw templates where they materially express hardware. A generic templating engine alone would move the complexity into templates.

The positional port order of a generated entity (`clk, CLOCK_ENABLE, RESET, global_to_module, module_to_global, inputs, outputs`) is spelled out separately at every site that writes it: the entity's port list and its parent's port map in `WRITE_LOGIC_ENTITY`, the MAIN instances in `WRITE_MULTIMAIN_TOP`, and the isolated wrapper `WRITE_LOGIC_TOP` (tree after the reset feature, which had to add `RESET` to all four; `vhdl_submodule_port_map_test.py` checks only the parent map). One `EntityInterface` record listing the ports and their order, rendered by both the declaration and every association, would make a new port a single change.

The entity-name hash cache of `AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP` was keyed by function name alone, assuming every instance of a function renders one way at zero added clocks; per-instance reset policies broke that, and it is now keyed by (function, policy). Any further per-instance rendering input must join that key (suspected hazard; no other such input is known).

Use content-addressed type dependencies and artifact manifests to reduce grow-only package and cache coupling over time. CIRCT's documented SystemVerilog path is an optional backend experiment; it does not directly replace the existing VHDL product.

## Validation

The original review reproduced no VHDL miscompile. The enum-default regression above establishes package elaboration legality and default values, including sparse, signed, wide one-hot and nested aggregate cases; it does not establish other HDL behavior. Compile generated VHDL with GHDL for enum conversions, CE, fixed/automatic pipelines and supported FIFO crossings. Compare native/HDL cycle behavior where native simulation supports the design. Render the same entity twice from equivalent physical inputs under different planner states and require identical bytes.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

