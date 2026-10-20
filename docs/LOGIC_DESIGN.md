# LOGIC — the shared Logic IR

`src/LOGIC.py` holds the intermediate representation both front ends build and every
later stage reads. The C front end (`src/C_TO_LOGIC.py`, see
[`issues_inventory.md`](issues_inventory.md#how-the-two-front-ends-fit-together)) and the
Python front end (`src/PY_TO_LOGIC.py`, see [`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md))
each produce a `ParserState` full of `Logic` objects. Pipelining
([`AUTO_PIPELINE_DESIGN.md`](AUTO_PIPELINE_DESIGN.md)), the throughput sweep
([`SWEEP_DESIGN.md`](SWEEP_DESIGN.md)), synthesis ([`SYN_DESIGN.md`](SYN_DESIGN.md)) and
VHDL generation ([`VHDL_DESIGN.md`](VHDL_DESIGN.md)) work only on that representation.

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section, if it
> has one, rather than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## Table of Contents

- [1. What lives where](#1-what-lives-where)
- [2. The `Logic()` object](#2-the-logic-object)
  - [Latency tags](#latency-tags)
- [3. `ParserState` — the global compiler context](#3-parserstate--the-global-compiler-context)
- [4. Source locations: `ASTMeta`](#4-source-locations-astmeta)
- [5. Names and C type strings](#5-names-and-c-type-strings)
- [6. Shared passes and helpers](#6-shared-passes-and-helpers)

- [History](#history)

---

## 1. What lives where

| module | role |
|---|---|
| `src/LOGIC.py` | `Logic`, `ParserState`, `ASTMeta`, the info classes, internal naming constants, C type string helpers, wire-graph helpers, the built-in operator `Logic` builder, and the whole-design passes both front ends run |
| `src/C_TO_LOGIC.py` | the C front end only: preprocessing, pycparser `c_ast` → `Logic`, `#pragma` handling, the C code generated for built-in operators and headers (bit manipulation, bit math, memories, clock crossings, FSMs), and the C parse cache |
| `src/PY_TO_LOGIC.py` | the Python front end, plus the native-sim model for user fixed-latency pipelines |
| `src/AUTO_PIPELINE.py` | `WRITE_0_ADDED_CLKS_INIT_FILES`, the first output either front end's `ParserState` reaches |
| `src/SYN.py` | `FUNC_IS_PRIMITIVE` and the float/integer instance reports |
| `src/utilities.py` | `GET_SHELL_CMD_OUTPUT`, `EXE_ABS_DIR`, `FIND_REGEX_MATCHES`, `DISPLAY_SOURCE` |

**Import rules.** `LOGIC.py` sits at the bottom of the compiler's import graph. At module
level it imports only the standard library and `utilities`. `AUTO.py` and `PY_TO_LOGIC.py`
read its constants (`BIN_OP_*_NAME`, `UNARY_OP_*_NAME`) while they themselves are being
imported, so `LOGIC` has to finish loading before anything that imports it. Only one
function imports another compiler module: `BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC` imports
`C_TO_LOGIC` locally for its C-code fallback (§6). Code shared by both front ends belongs in
`LOGIC.py`, including predicates over C type strings and `Logic` that later stages share
(§5, §6), and must not reach the C front end except through that one built-in fallback.
Modules other than the C front end call `LOGIC.X`; only code that really needs C syntax
trees calls `C_TO_LOGIC.X` (for example `VHDL.py`'s use of `C_TO_LOGIC.ID_IS_ENUM_CONST`
and its literal parser, and `RAW_VHDL.py`'s use of the C reference-token helpers).
Importing `C_TO_LOGIC` does not need `cpp`: the C front end checks for it
(`C_TO_LOGIC.REQUIRE_CPP`) when it first preprocesses, so Pypeline builds that load
`C_TO_LOGIC` for those helpers run without a C preprocessor.

## 2. The `Logic()` object

Every hardware function is represented as a `Logic()` object — a directed graph of wires
and submodule instances. A `Logic` is either a function definition
(`ParserState.FuncLogicLookupTable`) or, after instance lookup, the same object reached
through an instance name (`ParserState.LogicInstLookupTable`).

```python
logic.func_name                      # string name
logic.inputs                         # ordered list of input port names
logic.outputs                        # ordered list of output port names
logic.variable_names                 # set of user-introduced hardware variable base names
logic.wires                          # set of all wire names (becomes VHDL signals)
logic.wire_to_c_type                 # wire_name -> C type string
logic.wire_driven_by                 # wire_name -> driver_wire_name
logic.wire_drives                    # driver_wire_name -> {wire_name, …}
logic.submodule_instances            # inst_name -> func_name
logic.submodule_instance_to_input_port_names  # inst_name -> [port_name, …]
logic.submodule_instance_to_ast_meta # inst_name -> ASTMeta of the call site
logic.ast_meta                       # ASTMeta of the definition
# Reference-token metadata (used by ref-read/assign submodules):
logic.ref_submodule_instance_to_ref_toks
logic.ref_submodule_instance_to_input_port_driven_ref_toks
logic.wire_aliases_over_time         # base_var -> [alias_wire, …]  (oldest first)
logic.alias_to_driven_ref_toks       # alias_wire -> ref_toks tuple
logic.alias_to_orig_var_name         # alias_wire -> base_var name
```

Other fields carry state registers and global wires (`state_regs`,
`read_only_global_wires`, `write_only_global_wires` and the Pypeline-only
`global_wire_driven_paths` / `readback_global_wires`), feedback wires, multi-cycle paths
(`mcp_tuples`, `auto_multi_cycle_tuples`), AUTO_PIPELINE and AUTO_FSM tags
(`sub_inst_to_auto_pipeline_latency`, `sub_inst_to_auto_pipeline_key`,
`sub_inst_to_auto_fsm_key`), how a built-in is emitted (`is_c_built_in`, `is_vhdl_func`,
`is_vhdl_expr`, `vhdl_module_text`), and the measured `delay`. Each field's comment in
`Logic.__init__` says which front end fills it. `DEEPCOPY`, `MERGE_COMB_LOGIC` and
`MERGE_SEQ_LOGIC` must be updated with every new field.

`Logic.c_ast_node` returns `ast_meta.raw`, the original syntax node: a pycparser node for C
logic, a Python `ast` node for Pypeline logic. Only C-specific code may navigate it.

The graph-editing methods (`REMOVE_WIRES_AND_SUBMODULES_RECURSIVE`, `REMOVE_SUBMODULE`,
`COPY_SUBMODULE_INFO`, `WIRE_ALLOW_NO_DRIVEN_BY`, `WIRE_ALLOW_NO_DRIVES`,
`WIRE_DO_NOT_COLLAPSE`) and the latency questions (`CAN_HAVE_ADDED_LATENCY`,
`CAN_USE_AUTOPIPELINING`, `HAS_AUTO_PIPELINE_IN_HIER`) work the same for both front ends.

### Latency tags

`AutoPipelineLatency` (an AUTO_PIPELINE call site's `latency` / `start_latency` /
`max_latency` constraint) and `AutoMultiCycleConstraint` (an AUTO_MULTI_CYCLE tag) are
built from Pypeline tags with `.from_tag(...)` and stored on `Logic`. Their `key_suffix`
rules must match `pypeline.py`'s; see
[AUTO_PIPELINE_DESIGN.md](AUTO_PIPELINE_DESIGN.md) and
[AUTO_MULTI_CYCLE_DESIGN.md](AUTO_MULTI_CYCLE_DESIGN.md).

## 3. `ParserState` — the global compiler context

AUTO_FSM declares its constant-specialization table, independent measurement
callables and operand-mux callables here. `DEEPCOPY` preserves their mappings and
live callable identities. Characterization resolves the current consumer list,
so shapes registered after an earlier query are included.


```python
parser_state.FuncLogicLookupTable       # func_name -> Logic()  (function definitions)
parser_state.LogicInstLookupTable       # inst_key  -> Logic()  (instantiated call sites)
parser_state.FuncToInstances            # func_name -> {inst_keys}
parser_state.struct_to_field_type_dict  # struct_name -> {field: c_type_str}
parser_state.enum_info_dict             # enum_ctype_name -> LOGIC.EnumInfo (member map + int_c_type)
parser_state.global_vars                # name -> LOGIC.VariableInfo
parser_state.func_name_to_calls         # func_name -> {called func names}
parser_state.func_names_to_called_from  # func_name -> {calling func names}
parser_state.part                       # FPGA part string or None
parser_state.main_mhz                   # main_name -> float MHz or None
parser_state.func_fixed_latency         # func_name -> fixed latency (@pipeline_latency / FUNC_LATENCY)
parser_state.clk_cross_var_info         # var name -> LOGIC.ClkCrossVarInfo
```

`FuncLogicLookupTable` holds one `Logic()` per unique function definition.
`LogicInstLookupTable` holds one entry per call-site instance.

`path_delay_funcs`, `path_delay_measure_funcs` and `path_delay_frontier_funcs`
are declared as `None` until unrooted `SYN.ADD_PATH_DELAY_TO_LOOKUP` fills the
full parse's ordered dependencies, eligible hierarchy and measurement frontiers.
Measurement/refinement requires that explicit initialization. Rooted fixed-latency
characterization uses local collections without replacing the full-parse scope.
`ParserState.DEEPCOPY` copies these collections independently.

`ParserState.__init__` ends with a block of fields only the C front end fills and reads
(`c_file_ast`, `global_consts`, `func_to_local_state_regs`, `func_to_local_variables`,
`PrimFuncLogicLookupTable`, `func_mult_style`, `io_pairs`, and the generated-header
bookkeeping). They stay on the one class so shared code never meets a missing attribute.
The Python front end adds its own `pypeline_*` attributes in
`PY_TO_LOGIC._new_parser_state`.

The other classes stored in a `ParserState` are `VariableInfo` (a global or state register),
`EnumInfo`, `ClkCrossVarInfo` and `ArbHandshakeInfo`. Only the C front end fills the last
two, but VHDL and SYN read them for every design.

## 4. Source locations: `ASTMeta`

`ASTMeta` is the front-end-agnostic source location stored on `Logic.ast_meta` and per call
site in `submodule_instance_to_ast_meta`: `src_file`, `line`, `col`, `end_col` (Python only),
`hash_suffix` (C only: a few hex digits of a hash, from `C_TO_LOGIC.C_AST_NODE_TO_META`) and
`raw`, the original node. `coord_str()` is the wire-name-safe location tag used in instance
names (`blink_c_l20_c6_4a91` for C), and `location_text()` the human-readable `file:line:col`.
Equality and hashing go through `coord_str()`; that hash is salted per process, so passes
that put `ASTMeta`s in a set sort them before using the order (see
[VHDL_DESIGN.md](VHDL_DESIGN.md)).

## 5. Names and C type strings

Wire, instance and entity names follow conventions every stage parses back:

| constant | value | meaning |
|---|---|---|
| `SUBMODULE_MARKER` | `"____"` | separates an instance name from its port (`inst____port`) and nested instance names |
| `RETURN_WIRE_NAME` | `"return_output"` | the output port of every function |
| `CLOCK_ENABLE_NAME` | `"CLOCK_ENABLE"` | the clock-enable input port |
| `CONST_PREFIX` | `"CONST_"` | constant wires; `GET_VAL_STR_FROM_CONST_WIRE` reads the value back out of the name |
| `ENUM_CONST_MARKER` | `"$"` | marks an enum constant inside a constant wire name |
| `COMPOUND_NULL` | `"COMPOUND_NULL"` | the all-zeros value of any type |
| `BIN_OP_*`, `UNARY_OP_*`, `MUX_LOGIC_NAME`, `CAST_FUNC_NAME_PREFIX`, `CONST_REF_RD_*`, `VAR_REF_*` | | built-in operator function names, completed with their types by `BUILD_FUNC_NAME` |
| `PRINTF_FUNC_NAME`, `SIM_ASSERT_FUNC_NAME`, `SIM_FINISH_FUNC_NAME` | | simulation-control built-ins (`IS_SIM_CTRL_FUNC_NAME`) |

`LEAF_NAME`, `GET_CONTAINER_INST` and `RECURSIVE_FIND_MAIN_FUNC_FROM_INST` take instance
names apart. The sweep attributes timing paths by finding function names inside these
strings, so a naming change can change sweep decisions (see
[CONTRIBUTING.md](../CONTRIBUTING.md#implementation-and-code-hygiene)).

Types are plain C type strings (`"uint32_t"`, `"uint32_t[4]"`, `"point_t"`, `"float"`) in
`Logic.wire_to_c_type`. The `C_TYPE_IS_*` / `C_TYPES_ARE_*` predicates (including
`C_TYPE_IS_UINT_N`, `C_TYPE_IS_INT_N` and `C_TYPES_ARE_INTEGERS`), the `WIRES_ARE_ENUM` /
`WIRES_ARE_UINT_N` / `WIRES_ARE_INT_N` wire checks, `GET_WIDTH_FROM_C_TYPE_STR` /
`GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR`, `C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS`, the float
helpers and `C_TYPE_SIZE` read them for both front ends. So do the origin checks `IS_BIT_MANIP` / `IS_BIT_MANIP_NAME`, `IS_MEM`,
`IS_BIT_MATH`, `IS_AUTO_GENERATED`, `FUNC_NAME_INCLUDES_TYPES`, `GET_MEM_NAME` and
`C_TYPE_IS_ARRAY_STRUCT`, which classify a `Logic` by name or by the generated header it
came from.

## 6. Shared passes and helpers

- **Wire graph.** `CONNECT_WIRES_LOGIC(logic, driving_wire, driven_wire_names)` adds the
  wires and records `wire_drives` / `wire_driven_by`, with no type checks. The C front end's
  `C_TO_LOGIC.APPLY_CONNECT_WIRES_LOGIC` checks types and inserts casts first, then calls
  it. `FIND_DANGLING_LOGIC`, `FIND_CONST_DRIVING_WIRE`,
  `GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE` and the `WIRE_IS_*` predicates read the graph.
- **Trim and collapse.** `TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE` (gated by
  `TRIM_COLLAPSE_LOGIC`) removes wires that drive nothing and merges duplicate submodule
  instances that have identical drivers, for each function bottom up. It reconnects
  collapsed instances with `CONNECT_WIRES_LOGIC`; their port types were checked when they
  were first connected, so no cast is needed. Both `PARSE_FILE`s run it after instance
  lookup. The Python front end also runs it on AUTO_FSM's measurement roots, which no
  MAIN instantiates yet; a function without instances has no global instance names to
  rename.
- **Clock domains.** `INFER_CLOCK_DOMAINS` and `RECURSIVE_FIND_MAIN_FUNCS` assign globals
  and MAINs to clock groups. The C front end calls it from its clock-crossing pass; the
  Python front end calls it with empty crossing maps after building its call graph.
- **Clock enables.** `LOGIC_NEEDS_CLOCK_ENABLE(logic, parser_state)` decides whether a
  function gets a `CLOCK_ENABLE` port.
- **Global wires.** `GLOBAL_VAR_IS_SHARED` (a top-level IO or clock wire, or a global
  used by more than one function), `LOGIC_NEEDS_GLOBAL_TO_MODULE` and `LOGIC_NEEDS_MODULE_TO_GLOBAL` decide whether a
  function gets the `global_to_module` / `module_to_global` records.
- **Raw HDL.** `LOGIC_IS_RAW_HDL` says whether a `Logic` is emitted as hand-written VHDL
  (bit manipulation, memories, raw-HDL built-ins) instead of from its wire graph. For a
  built-in operator it asks `C_BUILT_IN_FUNC_IS_RAW_HDL`, which `FORCE_RAW_INT_CMP_FOR_QOR_BENCH`
  (environment variable `PYPELINE_FORCE_RAW_INT_CMP=1`, set only by the operator QoR bench)
  extends to the sliced integer comparators.
- **Source locations in messages.** `FUNC_SRC_LOC_STR(parser_state, func_name)` returns
  `" [file.py:line]"` from a function's `ast_meta`, for console and sweep messages.
- **Built-in operators.** `BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC` builds the `Logic` of a
  built-in operator instance (ports, types, whether it is a VHDL function). Built-ins with
  raw HDL (`LOGIC.C_BUILT_IN_FUNC_IS_RAW_HDL`) stop there. The rest fall back to
  `C_TO_LOGIC.BUILD_LOGIC_AS_C_CODE`, which generates C, preprocesses it with `cpp` and
  parses it. `PY_TO_LOGIC.PARSE_FILE` sets `PYPELINE_NO_SW_LIB_GUARD`, and while it is set
  that fallback raises instead; Pypeline registers soft implementations for those operators
  (see
  [Default replacements for C-generated operators](pypeline_DESIGN.md#default-replacements-for-c-generated-operators)).
- **printf.** `PRTINTF_STRING_TO_FORMATS` splits a format string into `PrintfFormat`s for
  `VHDL.py`.
- **Caches.** `LOGIC.DEL_ALL_CACHES()` clears the per-parse trim/collapse and
  clock-enable memos; the Python front end calls it before a re-parse.
  `C_TO_LOGIC.DEL_ALL_CACHES()` calls it and also clears the C front end's caches.
  Both memos are keyed by function name, and a re-parse can rebuild a function
  differently under the same name: AUTO_FSM's scheduled pass turns a MAIN that held
  only a combinational passthrough into one that holds the stateful FSM.

## History

### Owned FSM characterization state

ParserState initializes and independently copies specialization, pipeline-profile, transform, decode-proxy, source-identity and provenance tables. Fixed-latency constraints carry an optional plain-data FSM placement recipe, avoiding planner state hidden on live objects.

### Name-keyed memos are per parse

`LOGIC_NEEDS_CLOCK_ENABLE` memoizes by function name. The memo once outlived the
parse: an AUTO_FSM under a MAIN with no registers of its own was first parsed as a
combinational passthrough, so the MAIN was recorded as needing no clock enable. The
scheduled re-parse rebuilt the MAIN around the stateful FSM under the same name, read the
stale answer, and left the FSM's clock enable undriven. Vivado then removed every
register as constant. `DEL_ALL_CACHES` now clears it with the trim/collapse memo, for the
same reason.
