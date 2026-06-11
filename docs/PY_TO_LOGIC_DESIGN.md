# PY_TO_LOGIC — Design Document

## Table of Contents

**Architecture & Overview**
- [Overview](#overview)
- [Execution Model: Two Layers](#execution-model-two-layers)
- [End-to-End Flow Summary](#end-to-end-flow-summary)

**Core Data Structures**
- [`ParserState` — the Global Compiler Context](#parserstate--the-global-compiler-context)
- [The `Logic()` Object](#the-logic-object)
  - [C Type Strings](#c-type-strings)
  - [Bit-Accurate Constant Inference](#bit-accurate-constant-inference)
- [`FuncElaborator` — per-Function Elaboration State](#funcelaborator--per-function-elaboration-state)
  - [`env` vs `const_env` Routing](#env-vs-const_env-routing)
  - [`_try_eval_const` — the Elaboration/Hardware Boundary](#_try_eval_const--the-elaborationhardware-boundary)
  - [Annotation Evaluation](#annotation-evaluation)
  - [Return Type and Void Functions](#return-type-and-void-functions)

**Elaboration Mechanics**
- [Basic Function Calls — Submodule Instances](#basic-function-calls--submodule-instances)
- [Reference Tokens — the Core Addressing System](#reference-tokens--the-core-addressing-system)
- [Alias Tracking — Assignments Over Time](#alias-tracking--assignments-over-time)
- [Finding the Covering Wire](#finding-the-covering-wire)
  - [Temporal Sort of Covering Wires](#temporal-sort-of-covering-wires)
- [CONST\_REF\_RD — Reading Compound Types](#const_ref_rd--reading-compound-types)
- [VAR\_REF\_RD — Variable-Index Reads](#var_ref_rd--variable-index-reads)
- [VAR\_REF\_ASSIGN — Variable-Index Writes](#var_ref_assign--variable-index-writes)
- [`if` Statements — Hardware MUX Generation](#if-statements--hardware-mux-generation)
  - [Clock Enable Propagation Through `if`](#clock-enable-propagation-through-if)
  - [Reduction (`_reduce_driven_ref_toks`)](#reduction-_reduce_driven_ref_toks)
  - [Reading Branch Wires](#reading-branch-wires)
- [For and While Loop Unrolling](#for-and-while-loop-unrolling)
  - [For Loops](#for-loops)
  - [While Loops](#while-loops)
  - [Why Naming Stays Unique Across Iterations](#why-naming-stays-unique-across-iterations)
- [Closure Factory Pattern](#closure-factory-pattern)
  - [Specialised Functions](#specialised-functions)
  - [Specialised Types](#specialised-types)
  - [Conditional Type-Driven Code](#conditional-type-driven-code)

**Special Signal Declarations**
- [Registers (`Reg[T]`)](#registers-regt)
  - [Clock Enable and Function Calls](#clock-enable-and-function-calls)
- [Feedback Wires (`Feedback[T]`)](#feedback-wires-feedbackt)
- [Global Wires (`Wire[T]`)](#global-wires-wiret)
- [Global I/O (`Input[T]` / `Output[T]`)](#global-io-inputt--outputt)

**Multi-File Support**
- [Multi-File Import Support](#multi-file-import-support)
  - [Name Mangling Rule](#name-mangling-rule)
  - [`PARSE_FILE` Import Pre-Pass (`_process_imports`)](#parse_file-import-pre-pass-_process_imports)
  - [Wire Access in Hardware Function Bodies](#wire-access-in-hardware-function-bodies)
  - [Function Name Mangling](#function-name-mangling)
  - [Cross-File Function Calls](#cross-file-function-calls)

**Pypeline Pragmas**
- [Pypeline Pragmas (`PART` / `MAIN_MHZ`)](#pypeline-pragmas-part--main_mhz)
  - [`PART(...)` — FPGA Target Device](#part--fpga-target-device)
  - [`@MAIN(mhz)` — Clock Frequency Constraint](#mainmhz--clock-frequency-constraint)
  - [Clock Domain Inference (`INFER_CLOCK_DOMAINS`)](#clock-domain-inference-infer_clock_domains)

**Syntax Extensions**
- [Compound Initializer Syntax](#compound-initializer-syntax)
- [Ternary (IfExp) Assignment](#ternary-ifexp-assignment)
- [Boolean Operators (`and` / `or`)](#boolean-operators-and--or)
- [Bit Manipulation Syntax](#bit-manipulation-syntax)
- [Built-in Bit Manipulation Functions](#built-in-bit-manipulation-functions)
- [Custom Operator Registration](#custom-operator-registration)

**Simulation**
- [Proto-Simulation — Running Pypeline Code as Python](#proto-simulation--running-pypeline-code-as-python)
  - [`SimVal` — Typed Simulation Integer](#simval--typed-simulation-integer)
  - [`@hw_func` / `_sim_type_wrap` — Per-Function Type Propagation](#hw_func--_sim_type_wrap--per-function-type-propagation)
  - [`@MAIN` Implies `@hw_func`](#main-implies-hw_func)
  - [`Reg[T]` Simulation — Stateful Registers Across Clock Cycles](#regt-simulation--stateful-registers-across-clock-cycles)
  - [`Feedback[T]` Simulation — Combinatorial Convergence](#feedbackt-simulation--combinatorial-convergence)
  - [`Wire[T]` / `Input[T]` / `Output[T]` Global Wire Simulation](#wiret--inputt--outputt-global-wire-simulation--multi-main-convergence)
  - [Limitations of the Current Proto-Sim](#limitations-of-the-current-proto-sim)

**Reference**
- [pypeline.py — Runtime Support](#pypeline-py--runtime-support)
- [Predicting C/VHDL Output Names](#predicting-cvhdl-output-names)
  - [VHDL Identifier Safety — Name Sanitization](#vhdl-identifier-safety--name-sanitization)

---

## Overview

`PY_TO_LOGIC.py` is the Python frontend for the PipelineC hardware compiler. It translates
Python design files into PipelineC's internal `Logic()` graph representation, which the
backend then lowers to VHDL.

The central idea is to **use Python itself as the elaboration language**. A design file is
executed as a live Python module before any AST analysis begins. This means Python's full
runtime — arithmetic, conditionals, list comprehensions, class instantiation, closures — is
available at elaboration time. Only the hardware-typed function bodies need AST elaboration;
everything else is plain Python that runs normally.

---

## Execution Model: Two Layers

```
Design file (.py)
      │
      ▼  Layer 1 – Python runtime (importlib.exec_module)
      │  Runs factories, constants, @struct/@MAIN decorators, module-level code
      │
      ▼  Layer 2 – AST elaboration (FuncElaborator)
         Translates hardware-typed function bodies into Logic() graphs
```

**Layer 1** (`PARSE_FILE`):
- Executes the design file as a Python module
- Discovers `@MAIN` entry points via `pypeline._main_registry`
- Discovers struct types via `_discover_structs_from_module`
- Captures all module-level names (constants `N`, `M`, helper functions, closures) into
  `module_globals` for use during elaboration

**Layer 2** (`FuncElaborator.elaborate`):
- Parses the source again with `ast.parse`
- Collects top-level `def` statements that have type annotations (`_is_hardware_func`)
- Two-pass: first registers stubs in `FuncLogicLookupTable` (so recursive calls resolve),
  then elaborates each function body

---

## `ParserState` — the Global Compiler Context

```python
parser_state.FuncLogicLookupTable       # func_name -> Logic()  (function definitions)
parser_state.LogicInstLookupTable       # inst_key  -> Logic()  (instantiated call sites)
parser_state.FuncToInstances            # func_name -> {inst_keys}
parser_state.struct_to_field_type_dict  # struct_name -> {field: c_type_str}
parser_state.part                       # FPGA part string or None (set by PART(...) pragma)
parser_state.main_mhz                   # main_name -> float MHz or None (set by @MAIN(mhz=...) + inference)
```

`FuncLogicLookupTable` holds one `Logic()` per unique function definition.
`LogicInstLookupTable` holds one entry per call-site instance (populated by `_build_inst_lookup`
after all functions are elaborated).

---

## The `Logic()` Object

Every hardware function is represented as a `Logic()` object — a directed graph of wires
and submodule instances.

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
# Reference-token metadata (used by ref-read/assign submodules):
logic.ref_submodule_instance_to_ref_toks
logic.ref_submodule_instance_to_input_port_driven_ref_toks
logic.wire_aliases_over_time         # base_var -> [alias_wire, …]  (oldest first)
logic.alias_to_driven_ref_toks       # alias_wire -> ref_toks tuple
logic.alias_to_orig_var_name         # alias_wire -> base_var name
```

### C Type Strings

All types are plain strings matching PipelineC's C-level naming:

| Python annotation | C type string |
|---|---|
| `uint32_t` | `"uint32_t"` |
| `uint32_t[4]` | `"uint32_t[4]"` |
| `uint32_t[4][2]` | `"uint32_t[4][2]"` |
| `point_t` | `"point_t"` |
| `point_t[3]` | `"point_t[3]"` |

Helper functions navigate these strings:

```python
_is_array("uint32_t[4]")         # True
_array_elem_type("uint32_t[4]")  # "uint32_t"   (strips outermost dimension)
_array_first_dim("uint32_t[4]")  # 4
_is_struct("point_t", ps)        # True if point_t in struct_to_field_type_dict
_is_scalar("uint32_t", ps)       # True (not array, not struct)
```

### Bit-Accurate Constant Inference

When a plain Python integer literal appears in hardware context (e.g. `my_points[1].x = 1`),
`_infer_const_ctype` automatically squeezes it into the minimum-width PipelineC integer type:

```python
_infer_const_ctype(0)    # "uint1_t"   (bool / 0–1)
_infer_const_ctype(1)    # "uint1_t"
_infer_const_ctype(5)    # "uint3_t"   (3 bits covers 0–7)
_infer_const_ctype(255)  # "uint8_t"
_infer_const_ctype(-1)   # "int1_t"
_infer_const_ctype(-2)   # "int2_t"
```

The rule: non-negative values use `val.bit_length()` bits unsigned; negative values use
`(-val - 1).bit_length() + 1` bits signed. A constant wire `CONST_1_myfile_py_l5_c12`
of type `"uint1_t"` is added to the Logic() graph and connected to the appropriate port.
This ensures the VHDL backend always sees correctly-sized constants with no implicit
sign-extension or truncation surprises.

---

## `FuncElaborator` — per-Function Elaboration State

```python
self.func_def       # ast.FunctionDef being elaborated
self.parser_state   # shared ParserState
self.src_file       # source file path (used for unique naming)
self.module_globals # live Python namespace from exec_module
self.logic          # the Logic() being built
self.env            # env_key_str -> (wire_name, c_type_str)
self.const_env      # name -> Python value (loop counters, elaboration constants)
```

`env` maps **string keys** (e.g. `"points[0].dim[1]"`) to the current wire for that path.
`const_env` holds plain Python values used only at elaboration time — loop variables, index
counters, etc. — that never become hardware wires.

### `env` vs `const_env` Routing

Every assignment in a hardware function body goes through `_elab_assign`, which applies
this decision tree:

```
target is a simple Name AND not already in env?
    │
    ├─ _try_eval_const(RHS) succeeds (pure Python value)
    │       └─ const_env[name] = value        ← elaboration-time only
    │
    └─ _try_eval_const(RHS) fails (references a hardware wire)
            └─ emit hardware: create wire, connect, update env
```

This is why `b = 0` and `i = i + 1` inside a loop body update `const_env` rather than
creating hardware wires: `0` and `i + 1` (where `i` is already in `const_env`) both
evaluate successfully as plain Python. The moment the RHS touches a wire — reading a
hardware-typed input or a previously elaborated expression — the `eval()` inside
`_try_eval_const` raises a `NameError`, the const path fails, and hardware synthesis
proceeds instead.

### `_try_eval_const` — the Elaboration/Hardware Boundary

```python
def _try_eval_const(self, node):
    expr = ast.Expression(body=node)
    ast.fix_missing_locations(expr)
    return eval(compile(expr, "<const_eval>", "eval"), self._make_eval_ns())
```

It compiles the AST node into a Python code object and runs it through Python's native
`eval()` against `{**module_globals, **const_env}`. This namespace contains only plain
Python values — integers, strings, ranges, type objects, helper functions — never hardware
wire names. If the expression references anything that only exists as a string in `self.env`
(e.g. a hardware input), `eval()` raises `NameError` and `_try_eval_const` returns `None`.

This clean boundary means: if Python can compute it, it stays Python; if it requires knowing
a hardware signal value at runtime, it becomes hardware.

**`_elab_binop` constant short-circuit:** `_elab_binop` calls `_try_eval_const` on the
entire BinOp expression before elaborating any operand. If the result is an `int` or `bool`
(e.g. `n_bits - 1 - i` where `n_bits` is a closure variable and `i` is a for-loop counter
— both in `_make_eval_ns()`), `_elab_python_value` is called directly and a CONST wire is
emitted. This prevents spurious `BIN_OP_minus` submodule instances from appearing in the
Logic() graph for expressions that are entirely compile-time constants, even when the LHS
variable being assigned to is already a hardware wire in `self.env`.

### Annotation Evaluation

Function signature annotations are evaluated against `{**module_globals, **const_env}`:

```python
def concat(bits_lo: uint1_t[LO_SIZE], bits_hi: uint1_t[HI_SIZE]) -> uint1_t[OUT_SIZE]:
```

`LO_SIZE`, `HI_SIZE`, `OUT_SIZE` are resolved from `module_globals` or closure variables
at elaboration time, producing concrete C type strings like `"uint1_t[3]"`.

### Return Type and Void Functions

A function with no `->` return annotation is **void**. `_setup_outputs` checks the return
annotation via `_annotation_to_ctype`; if the result is `None` (void), **no** `return_output`
wire is added to `logic.outputs` or `logic.wires`. A void function's `Logic()` has an empty
`outputs` list.

`_elab_return` enforces three rules:

1. **Void function with any `return` statement** — `ElaborationError`. Void functions must
   have no `return` statement at all.
2. **Non-void function with bare `return` (no value)** — `ElaborationError`.
3. **Multiple `return` statements** — `ElaborationError`. Hardware functions must have
   exactly one `return` statement; a second one would attempt to drive `return_output`
   twice, which is detected by checking `RETURN_WIRE_NAME in logic.wire_driven_by`.

---

## Basic Function Calls — Submodule Instances

A call `foo(a, b)` in a hardware function body creates a submodule instance:

```
inst_name    = "foo[myfile_py_l10_c4]"          ← unique per call site (file+line+col)
output_wire  = inst_name + "____return_output"
port_wire_a  = inst_name + "____a"
```

All instance wires are recorded in `logic.wire_to_c_type` and connected via
`logic.wire_driven_by`. The callee's `Logic()` is looked up in `FuncLogicLookupTable`
to determine port names and the return type.

**Binary ops, unary ops, MUX** are all represented as submodule instances with
auto-generated built-in function names:

```
BIN_OP_LOGIC_NAME_PREFIX_plus_uint32_t
UNARY_OP_LOGIC_NAME_PREFIX_not_uint1_t
MUX_uint32_t
MUX_point2d_t          ← compound-type MUX is valid
```

---

## Reference Tokens — the Core Addressing System

A *reference token tuple* (ref_toks) is the canonical way to describe a path into a
compound variable:

```python
("points", 0, "dim", 1)    # points[0].dim[1]  — all concrete
("points", i_ast, "dim")   # points[i].dim      — i is an ast.AST node (variable index)
```

Tokens are:
- `int` — concrete array index
- `str` — struct field name
- `ast.AST` node — variable (hardware) index; acts as a wildcard in coverage matching

```python
_is_var_tok(tok)               # True for ast.AST nodes
_has_variable_index(ref_toks)  # True if any token is an ast.AST
_ref_toks_to_env_key(ref_toks) # ("points",0,"dim",1) -> "points[0].dim[1]"
_ref_toks_to_ctype(ref_toks, base_type, ps)  # C type at the path end
```

`_parse_ref_toks(ast_node)` converts an AST expression to ref_toks: constant subscripts
and `const_env` values become concrete `int`/`str` tokens; anything else becomes the raw
AST sub-expression node, preserving variable indices for later wildcard matching.

---

## Alias Tracking — Assignments Over Time

Every write to a variable creates a new **alias wire** rather than mutating the existing
wire. This models the sequential nature of assignments within combinational hardware:

```python
# points[0].dim[1] = test_u32
alias = "points_0_dim_1_myfile_py_l15_c4"
logic.wire_aliases_over_time["points"].append(alias)   # oldest first
logic.alias_to_driven_ref_toks[alias] = ("points", 0, "dim", 1)
logic.alias_to_orig_var_name[alias]   = "points"
self.env["points[0].dim[1]"]          = (alias, "uint32_t")
```

`wire_aliases_over_time[base_var]` is an **ordered list, oldest alias first, newest last**,
representing the assignment history of that variable within the function. This temporal
ordering is critical: it is the single source of truth for reconstructing partial writes
when reading the variable back.

---

## Finding the Covering Wire

`_find_covering_wire(leaf_ref_toks)` returns the most recent wire that covers a concrete
leaf path. It walks `wire_aliases_over_time[base_var]` in **reverse chronological order**
(newest alias first), using `_var_ref_toks_covers` for both concrete and variable aliases.
The first covering alias wins. If no alias covers the path, `self.env[base_var]` provides
the original input/declaration wire as a fallback.

```python
def _var_ref_toks_covers(var_ref_toks, concrete_ref_toks):
    # ("points", i_ast, "dim", 1) covers ("points", 0, "dim", 1) ✓
    # ("points", i_ast, "dim", 1) covers ("points", 0, "dim", 0) ✗  (1 ≠ 0 at pos 3)
    # ("points",) covers any leaf under points                    ✓
```

This guarantees **strict temporal correctness**: a later full assignment like
`out_state = state` (ref_toks `("out_state",)`) always shadows an earlier partial write
like `out_state.sB = 0` (ref_toks `("out_state", "sB")`), because the full-assignment
alias sits later in `wire_aliases_over_time` and is therefore encountered first in the
reverse walk.

### Temporal Sort of Covering Wires

When a CONST_REF_RD needs multiple covering wires, they must be presented to the VHDL
backend in **oldest-first** order so that base assignments appear before partial overrides.
The algorithm (`_temporal_sort_covering_wires`) achieves this in three steps:

```
1. Walk wire_aliases_over_time[base_var] BACKWARDS (newest alias first)
2. For each alias whose ref_toks appears as a covering-wires key, collect it
   (both identity check `is` and equality check `==` are tried)
3. Any covering entries not matched by any alias are the input wire / base
   fallback — append them last
4. Reverse the collected list → oldest first
```

Example for `return my_points` after writes to `[1].x`, `[1].y`, `[2]`, `[3]`, `[4]`:

```
Backwards walk collects: alias_4, alias_3, alias_2, alias_1y, alias_1x
Remaining (no alias): ("my_points",)  ← original input wire
After reverse:
  ref_toks_0: my_points      (covers [0], [5..9]  — oldest, input wire)
  ref_toks_1: alias_1x       (covers [1].x)
  ref_toks_2: alias_1y       (covers [1].y)
  ref_toks_3: alias_2        (covers [2])
  ref_toks_4: alias_3        (covers [3])
  ref_toks_5: alias_4        (covers [4])
```

The backend applies these in order: `base := ref_toks_0; base(1).x := ref_toks_1; …`

---

## CONST_REF_RD — Reading Compound Types

Reading a compound value (struct, array) when it may have been partially written requires
a `CONST_REF_RD` submodule. This is the mechanism behind `return points`, field reads like
`p = my_struct.field`, and array element reads like `v = arr[2]` when `arr` was partially
updated.

**Process:**

1. Enumerate all scalar leaf ref_toks of the target type (`_get_leaf_ref_toks`)
2. For each leaf, call `_find_covering_wire` → `(wire, covering_ref_toks, type)`
3. Collect unique covering wires and sort temporally (`_temporal_sort_covering_wires`)
4. If a single covering wire already matches the exact target ref_toks: return it directly
   (no submodule needed — the wire is already the right type)
5. Otherwise emit a `CONST_REF_RD_<output_type>_<base_type>_<path>_<hash>` submodule.
   When called from branch coverage (`_read_branch_coverage`), a `branch_tag` (`"true"` or
   `"false"`) is forwarded through `_read_ref` → `_emit_const_ref_rd` and appended to the
   instance tag (`"{func_name}_{branch_tag}"`). This prevents a collision when both branches
   read the same compound variable through the same covering wires and the same AST node.

**`return my_points` example** (after `my_points[1].x=1`, `my_points[2]=p0`, etc.):

```python
CONST_REF_RD(
    ref_toks_0 = my_points_input,   # type: point_xy_t[10]  covers [0],[5..9]
    ref_toks_1 = alias_1x,          # type: uint32_t         covers [1].x
    ref_toks_2 = alias_1y,          # type: uint32_t         covers [1].y
    ref_toks_3 = alias_2,           # type: point_xy_t       covers [2]
    ref_toks_4 = alias_3,           # type: point_xy_t       covers [3]
    ref_toks_5 = alias_4,           # type: point_xy_t       covers [4]
) -> point_xy_t[10]
```

The backend recognises the `CONST_REF_RD_` prefix and generates VHDL that starts from
the base wire and applies each partial override in sequence.

**Variable alias as covering input:** if a covering wire came from a VAR_REF_ASSIGN alias
(which has variable ref_toks like `("points", i_ast, "dim", 1)`), `_var_alias_internal_path`
computes the correct CONST_REF_RD index path into that alias's output type. For example,
alias type `uint32_t[3]` covering `("points", i_ast, "dim", 1)`, used to extract concrete
leaf `("points", 0, "dim", 1)` → internal path `(0,)` → `CONST_REF_RD([0])` from
`uint32_t[3]` → `uint32_t`.

---

## VAR_REF_RD — Variable-Index Reads

Reading with a variable index (`points[i]`, `points[i].dim[j]`) requires a `VAR_REF_RD`
submodule that selects one element from among all possible positions using a binary mux tree.

**Call site** (`_emit_var_ref_rd`):
1. Enumerate all concrete scalar leaves under the variable path (`_get_var_ref_leaves`)
2. Find covering wires for each leaf and sort temporally
3. Elaborate each variable index expression to get a select wire
4. Build or reuse the `VAR_REF_RD_<output>_<base>_<path>_<hash>` Logic() in `FuncLogicLookupTable`
5. Emit a submodule instance call

**Standalone Logic() structure** (`_build_var_ref_rd_logic`):

The Logic() definition is built once and reused for all call sites with the same signature.

*Step 1 — Extract all concrete scalar leaf wires via CONST_REF_RD:*

For `points[i]` with a 3-element array of `point2d_t` (each having 2 `uint32_t` fields),
this extracts 6 scalar wires: `points[0].dim[0]`, `points[0].dim[1]`, `points[1].dim[0]`, …

If any covering input is a variable alias (from a prior VAR_REF_ASSIGN), internal CONST_REF_RD
submodules index into it using `_var_alias_internal_path`.

*Step 2 — Trimmed binary mux tree per variable dimension:*

For each variable dimension of size N, a mux tree reduces N leaf wires to 1 output.
The tree uses `_largest_pow2_leq(N)` as the split point rather than padding to the next
power of two:

```
N=3: split at 2 (largest pow2 ≤ 3)         N=100: split at 64
     left subtree:  leaves[0..1]                  left subtree:  leaves[0..63]
     right subtree: leaves[2]                      right subtree: leaves[64..99]
```

This means a 100-element array uses a mux tree of depth log₂(64)=6 on the left plus a
depth-6 tree on the right for 36 elements — **no dummy zero-padding hardware is ever
synthesized**. A naïve power-of-two approach would pad to 128 elements, wasting 28 MUX
levels on unreachable inputs.

Each split uses a single-bit extraction from the select wire:

```
bit_pos = split.bit_length() - 1
bit_func = "uint2_3_3_3"  ← extracts bits [bit_pos:bit_pos] from uint2_t select wire
MUX(bit, right_subtree, left_subtree)   ← bit=1 → index ≥ split → right
```

*Step 3 — Assemble compound output:*

If the output type is compound (e.g. `point2d_t`), the scalar outputs of the final mux tree
are assembled back into the compound type via a CONST_REF_RD assembly submodule. If the
output is scalar, it is connected directly.

---

## VAR_REF_ASSIGN — Variable-Index Writes

Writing with a variable index (`points[i].dim[1] = val`) creates a `VAR_REF_ASSIGN`
submodule and a **variable alias** with AST node ref_toks preserved.

**Output type:** `elem_c_type[var_dim_0][var_dim_1]...` where `elem_c_type` is the type
at the end of the ref_toks path. For `points[i].dim[1]` with `i` ranging over 3 elements:
output type = `uint32_t[3]` (one slot per possible value of `i`).

**Wire diagram for `points[i].dim[1] = val` (3-element array):**

```
Covering input
  ref_toks_0: points  (point2d_t[3])
      │
      ├─ CONST_REF_RD → points[0].dim[1]  (uint32_t)  old_elem[0]
      ├─ CONST_REF_RD → points[1].dim[1]  (uint32_t)  old_elem[1]
      └─ CONST_REF_RD → points[2].dim[1]  (uint32_t)  old_elem[2]

Variable index
  var_dim_0: i  (uint2_t)
      │
      ├─ EQ(i, 0) ─────────────────────── cond[0]
      ├─ EQ(i, 1) ─────────────────────── cond[1]
      └─ EQ(i, 2) ─────────────────────── cond[2]

For each slot k ∈ {0, 1, 2}:
  MUX(cond[k], val, old_elem[k]) → updated_elem[k]   (MUX_uint32_t)

CONST_REF_RD assembly:
  (updated_elem[0], updated_elem[1], updated_elem[2]) → uint32_t[3]
      │
      └─ return_output  (uint32_t[3])
```

**Operates at elem level:** the MUX always works on `elem_c_type` (the type at the end of
the ref_toks path), not on decomposed scalars. If `elem_c_type` is a struct or inner array,
the MUX is a `MUX_my_struct_t` — compound-type MUXes are valid and produce correct VHDL.

**Standalone Logic() construction** (`_build_var_ref_assign_logic`):

*Step 1 — CONST_REF_RD extracts old elem-typed values* from the covering inputs for each
concrete position. `_var_alias_internal_path` is used when a covering input is itself a
variable alias.

*Step 2 — EQ comparators + AND tree + MUX per concrete position.* For multi-dimensional
variable indices (e.g. `points[i].dim[j]`), comparators for each dimension are ANDed
together before the MUX select.

*Step 3 — CONST_REF_RD assembly* packs the updated elem wires into the output type. For
`uint32_t[3]`, this emits a single assembly CONST_REF_RD mapping positions 0, 1, 2.

**The assembly pseudo-variable:** the assembly CONST_REF_RD inside a standalone Logic()
references an internal pseudo-wire (e.g. `"var_assign_out"`) as its base type anchor. This
wire is registered in `logic.wire_to_c_type` of the standalone Logic() so the backend can
look up the output type. It is not a real hardware signal — it carries no driver and does
not appear in VHDL signal declarations.

**The alias** records variable ref_toks with AST nodes intact:

```python
logic.wire_aliases_over_time["points"].append(alias)
logic.alias_to_driven_ref_toks[alias] = ("points", i_ast, "dim", 1)  # AST node preserved
logic.wire_to_c_type[alias] = "uint32_t[3]"
```

This lets `_find_covering_wire` discover the alias later via `_var_ref_toks_covers`, and
`_var_alias_internal_path` computes the correct index into the alias's output type when a
subsequent CONST_REF_RD or VAR_REF_RD needs to extract a specific concrete element from it.

---

## `if` Statements — Hardware MUX Generation

Compile-time constant conditions → branch elimination (no hardware emitted).

Runtime hardware conditions → snapshot/restore + MUX per driven variable:

```
1. Evaluate condition:  cond_wire, _ = _elab_expr(stmt.test)
2. Emit clock-enable MUX wires (permanent, see below)
3. Snapshot env and wire_aliases_over_time → env_snap, aliases_snap
4. Push true_ce_wire onto clock_enable_wires
5. Elaborate true branch  → capture env_true, aliases_true
6. Pop clock_enable_wires
7. Restore snapshot
8. Push false_ce_wire onto clock_enable_wires
9. Elaborate false branch → capture env_false, aliases_false  (empty if no else)
10. Pop clock_enable_wires
11. Restore snapshot
12. Collect driven ref_toks from new aliases in both branches
13. Reduce:  _reduce_driven_ref_toks(driven, env_snap, parser_state)
14. For each reduced (ref_toks, mux_type):
      true_wire  = _read_branch_coverage(env_true,  aliases_true,  ...)
      false_wire = _read_branch_coverage(env_false, aliases_false, ...)
      MUX(cond, true_wire, false_wire) → mux_alias
```

Both branches elaborate **into the same `logic` object** — wires and submodule instances
accumulate permanently. Only `env` and `wire_aliases_over_time` are snapshot/restored, so
the hardware graph is additive across both branches while the alias view remains consistent.

### Clock Enable Propagation Through `if`

Every `Logic()` starts with a `clock_enable_wires` list initialised to `["CLOCK_ENABLE"]`
(the function's top-level CE input). This list acts as a stack: the last element is the
**current CE wire** at any point during elaboration.

When a runtime `if` is encountered, two permanent MUX instances are emitted before any
branch is elaborated:

```
true_ce_wire  = MUX(cond, parent_ce, 0)   # CE passes through only when cond=1
false_ce_wire = MUX(cond, 0, parent_ce)   # CE passes through only when cond=0
```

`parent_ce` is `clock_enable_wires[-1]` at the point the `if` is processed, so nesting
works automatically: an `if` inside another `if` sees the outer branch's gated CE, not
the top-level one.

Each branch is elaborated with its CE wire pushed onto the stack and popped afterwards,
so `clock_enable_wires[-1]` always reflects the correct gating context. The push/pop
affects only the stack — the MUX instances and their output wires are permanent additions
to `self.logic`.

When a submodule call inside a branch needs a CE connection (see **Clock Enable and
Function Calls** below), `clock_enable_wires[-1]` is already the branch-gated wire, so
the correct gated CE is wired to the submodule's `CLOCK_ENABLE` port automatically.

### Reduction (`_reduce_driven_ref_toks`)

Eliminates redundant patterns before emitting MUXes, in two passes:

**Pass 1 — Completeness (bottom-up, iterated):** if all children of a concrete parent path
are present, replace them with the parent and emit one compound MUX:

```
("points",0), ("points",1), ("points",2) for 3-element array
    → ("points",)   with mux_type point2d_t[3]   (one MUX instead of three)
```

Iterated so that `dim[0]` + `dim[1]` → `dim` → `points[i].dim` → `points[i]` can chain.

**Pass 2 — Prefix coverage:** if ref_toks B is a strictly more general prefix of ref_toks A
(shorter, or same length with wildcards where A has concrete), remove A:

```
("points", i_ast) covers ("points", 0, "dim", 1) → remove the latter
```

### Reading Branch Wires

`_read_branch_coverage` temporarily swaps `self.env` / `wire_aliases_over_time` to the
branch snapshot, reads the required wire, then restores the originals. It handles two cases:

**Concrete ref_toks (no variable indices):** calls `_read_ref(ref_toks, mux_type, ast_node,
branch_tag=branch_tag)`. `_read_ref` forwards the tag to `_emit_const_ref_rd`, which appends
it to the instance tag so the true-branch and false-branch CONST_REF_RD instances get
distinct names even when the covering wires are identical (see **CONST_REF_RD** above).

**Variable ref_toks (contains AST nodes):** `_read_branch_coverage` calls
`_assemble_var_ref_coverage` to produce a wire of `mux_type` from the branch's env/aliases:

1. Temporarily swap `self.env` and `wire_aliases_over_time` to the branch snapshot
2. Use `_get_var_ref_elem_positions` to enumerate all concrete elem positions
3. Call `_read_ref` for each position — this naturally finds the right covering wire from
   the branch state (the VAR_REF_ASSIGN alias in the true branch, or the original input in
   the false/pre-if branch)
4. Assemble the elem wires into `mux_type` via a CONST_REF_RD assembly submodule
5. Restore `self.env` and `wire_aliases_over_time`

**The assembly pseudo-variable (`DUMMY_OUT`):** the CONST_REF_RD assembly inside the
caller's Logic() needs a type-anchor wire so the backend can look up the output type during
VHDL generation. A pseudo-wire `"cov_assemble_<mux_type_tag>"` (e.g.
`"cov_assemble_uint32_t_3"`) is registered in `self.logic.wire_to_c_type` with the
`mux_type`. It is added to `wire_to_c_type` only — not to `logic.wires` — so no spurious
VHDL signal is declared.

**The MUX output alias** inherits the driven ref_toks with AST nodes intact, so any
subsequent reads after the if statement correctly discover it via `_find_covering_wire`
wildcard matching.

---

## For and While Loop Unrolling

Both loop constructs are **fully unrolled at elaboration time**. The loop condition or
iterable must evaluate to a plain Python value via `_try_eval_const`. No hardware mux trees
are generated for loop control; loops exist purely at elaboration time.

### For Loops

```python
for i in range(LO_SIZE):   # range(3) evaluated by _try_eval_const
    bits[b] = bits_lo[i]   # unrolled 3 times with concrete i=0,1,2
    b = b + 1
```

The loop variable `i` is stored in `const_env` at each iteration. Body statements are
elaborated once per value, producing distinct hardware for each unrolled copy.

Supported iterables: `range(...)`, `tuple`, `list`. String field iteration
(`for f in point_t._fields:`) works too — `f` becomes a string in `const_env` and
subscript access `rv[f]` resolves to a struct field via `_parse_ref_toks`.

### While Loops

```python
i = 0
while i < LO_SIZE:         # condition re-evaluated each iteration via _try_eval_const
    bits[b] = bits_lo[i]
    b = b + 1
    i = i + 1              # updates const_env["i"], not a hardware wire
```

Each iteration: evaluate condition, elaborate body if true, repeat. Loop counter updates
(`i = i + 1`) route through `_elab_assign`: `i` is not in `env`, `_try_eval_const(i+1)`
succeeds → `const_env["i"]` updated. A safety limit of 65 536 iterations prevents
non-terminating loops from hanging the compiler.

### Why Naming Stays Unique Across Iterations

A concern when unrolling is that multiple iterations of the same source line might produce
colliding wire/instance names. The primary mechanism is `loop_instance_prefix`:

**`loop_instance_prefix`** (the general solution) — `_elab_for` accumulates a string prefix
like `"FOR_i_0_"` (or `"FOR_i_0_FOR_j_2_"` when nested) that is prepended to **every**
alias wire name and submodule instance name emitted inside the loop body. This prefix is
applied in three places:

- `_write_ref` — all assignment aliases (`result`, `bits[0]`, struct fields, etc.)
- `_elab_if` — MUX output aliases produced by if-statements inside the loop
- `_emit_var_ref_assign` — VAR_REF_ASSIGN output aliases

When `loop_instance_prefix` is `""` (outside any loop), the names are identical to before.

**Additional natural uniqueness** for some patterns that also helps (but is not sufficient alone):

- **Concrete-index writes:** `bits[b] = bits_lo[i]` — the alias prefix includes `b`'s
  resolved value (`"bits_0_..."`, `"bits_1_..."`), producing different alias names even
  before the loop prefix is applied
- **VAR_REF_ASSIGN func_name hash:** includes the covering_ref_toks, which differ across
  iterations as each iteration's output alias becomes the next iteration's covering input —
  a chain of distinct hashes for the submodule definition (not the alias wire)
- **CONST_REF_RD reads:** the func_name includes the concrete access path (e.g. index 0 vs
  index 1), giving different func_names → different inst_names

---

## Closure Factory Pattern

The closure factory pattern lets Python generate specialised hardware functions and types
at elaboration time, with all sizing and structure resolved to concrete values before any
hardware graph is built.

### Specialised Functions

```python
def make_concat(LO_SIZE, HI_SIZE):
    OUT_SIZE = LO_SIZE + HI_SIZE

    def concat(bits_lo: uint1_t[LO_SIZE], bits_hi: uint1_t[HI_SIZE]) -> uint1_t[OUT_SIZE]:
        bits: uint1_t[OUT_SIZE]
        b = 0
        for i in range(LO_SIZE):
            bits[b] = bits_lo[i]
            b += 1
        ...
        return bits

    return concat

concat_3_4 = make_concat(3, 4)   # module-level alias, discovered by elaborator
```

When a call to `concat_3_4` is first encountered in a hardware function body, `_elab_call`
finds it in `module_globals`, sees it is callable but not in `FuncLogicLookupTable`, and
invokes `_elaborate_live_func`:

1. `inspect.getsource` + `textwrap.dedent` recovers the inner function's source text
2. Closure variables are extracted from `func.__code__.co_freevars` / `func.__closure__`
   — e.g. `{"LO_SIZE": 3, "HI_SIZE": 4, "OUT_SIZE": 7}`
3. Names used only in annotations (not body) are recovered from `func.__annotations__`
   and merged into the closure namespace
4. A **canonical name** is computed from the factory chain + all closure variables
   (or a hash when factory params aren't in the closure — see Canonical function name format)
5. Dedup check: if the canonical name is already in `FuncLogicLookupTable`, return the
   existing Logic() immediately — no re-elaboration
6. Otherwise, a fresh `FuncElaborator` elaborates the function; the result is stored under
   the canonical name in `FuncLogicLookupTable` with `logic.func_name = canonical`

The Python alias (`"concat_3_4"`) is **not** stored in `FuncLogicLookupTable`. The dict
only holds concrete functions that map to VHDL entities. The next time `concat_3_4` is
encountered, `_elab_call` calls `_elaborate_live_func` again; the dedup check at step 5
returns immediately.

After finding the `callee_def`, `_elab_call` passes `callee_def.func_name` (the canonical
name) — not the Python alias — to `_add_submodule_instance`, so all references in
`submodule_instances` and VHDL output use the canonical name consistently.

**Closure globals merge:** when elaborating a closure function, the namespace used for
`_try_eval_const` and annotation resolution is built as:

```
merged_globals = {**func.__globals__, **self.module_globals, **closure_ns}
```

Priority: `closure_ns` > `self.module_globals` > `func.__globals__`. The lowest-priority
`func.__globals__` captures types imported at the top of the closure's source file (e.g.
`vga_pos_t` imported in `vga/timing.py`) that are not present in the calling module's
globals. The struct-scan pass that registers closure structs in
`parser_state.struct_to_field_type_dict` also inspects `func.__globals__` for struct types.

**Nested factory functions** — factory-produced functions whose result is local to another
factory (never bound at module level) — work the same way. The closure of the outer
function contains the inner callable; when its body is elaborated, `merged_globals`
includes the closure var, `_elab_call` finds it as a callable, and `_elaborate_live_func`
computes a canonical name for it:

```python
def make_sum3(T):
    local_add = make_adder(T)   # local — never in module_globals

    def sum3(a: T, b: T, c: T) -> T:
        return local_add(local_add(a, b), c)

    return sum3

sum3_u32 = make_sum3(uint32_t)
# local_add gets canonical "make_adder_T_uint32_t" regardless of which outer
# factory created it — make_sum3(uint32_t) and make_sum3(uint8_t) produce
# distinct "make_adder_T_uint32_t" and "make_adder_T_uint8_t" respectively
```

Only top-level `def` statements are scanned by `ast.walk` on `tree.body`. Nested functions
inside factory closures (like `def concat` inside `make_concat`) are deliberately excluded
— they are elaborated on-demand through `_elaborate_live_func` when first called.

**Canonical function name format:**

```
<factory_prefix>_<param1>_<val1>_<param2>_<val2>_...
```

`factory_prefix` encodes the **definition hierarchy** (from `func.__qualname__`, not the
call site): `func.__qualname__` with the last `.<locals>.<funcname>` stripped and remaining
`.<locals>.` replaced with `_`. This means a module-level factory called from inside
another factory still uses only its own name as the prefix.

Only closure variables whose names match a **parameter of the enclosing factory function**
are included (sorted alphabetically). The factory is looked up by name in `module_globals`;
middle-chain factories (nested definitions) are looked up as callables in the closure.

**Three cases for the suffix:**

1. **Factory not found** in `module_globals` — fall back to all type/int-valued closure vars.
2. **Factory has 0 parameters** — suffix is empty; name is just `factory_prefix`.
3. **Factory has parameters, but none appear in the closure** — this happens when the factory
   computes derived locals from its parameters (e.g. `make_vga_timing` expands `spec` into
   integer constants `FRAME_WIDTH`, `H_SYNC_START`, etc.; none of those match the parameter
   name `spec`). In this case, all closure vars are **hashed** (SHA-256, first 8 hex chars)
   and the factory parameter names are used as the descriptor: `<param_names>_<hash8>`.
   Example: `make_vga_timing_spec_a1b2c3d4`. This avoids the 300+ character names that
   would result from listing all derived closure vars, which can exceed OS path limits.

Values are: C type name for `_CTypeMeta` / `@struct` types (with brackets mangled to `_`),
integer/bool values as their string representation. Non-C-type objects are skipped.

```python
# make_concat.<locals>.concat  factory params: LO_SIZE, HI_SIZE
# → "make_concat_HI_SIZE_4_LO_SIZE_3"     (OUT_SIZE excluded — derived local)

# make_adder.<locals>.add  factory params: T  (recovered from annotations)
# → "make_adder_T_uint32_t"

# make_negate.<locals>.negate  factory params: value_t, out_t
# → "make_negate_out_t_int33_t_value_t_uint32_t"

# make_float_adder.<locals>.float_add  factory params: float_t
# → "make_float_adder_float_t_float_t_sign_uint1_t_exp_uint8_t_man_uint23_t"
# (M, SHIFT_AMOUNT_BITS, exp_t, man_t, etc. are all derived locals — excluded)

# make_clz called from inside make_float_adder: clz.__qualname__ = "make_clz.<locals>.clz"
# → "make_clz_value_t_uint24_t"   (definition is at module level, call site irrelevant)

# make_double_neg.<locals>.make_inv.<locals>.inv  factory params: t (from make_inv)
# → "make_double_neg_make_inv_t_uint32_t"   (nested definition encoded in prefix)

# make_swap.<locals>.swap  factory params: T, but T not captured in swap's closure
# → hashed fallback: "make_swap_T_<hash8>"   (all closure vars hashed; "T" is the param name)

# make_vga_timing.<locals>.vga_timing  factory params: spec (VgaTimingSpec)
# spec not in closure (expanded into FRAME_WIDTH, H_SYNC_START, etc.)
# → hashed fallback: "make_vga_timing_spec_a1b2c3d4"

# def make_singleton():  (0 params)
# → "make_singleton"
```

### Specialised Types

```python
def make_point_t(dim_type, dim_size):
    @struct
    class point_t(NamedTuple):
        dim: dim_type[dim_size]
    point_t.dim_type = dim_type
    point_t.dim_size = dim_size
    return point_t

point_t = make_point_t(uint32_t, 2)
```

`_discover_structs_from_module` walks the live module namespace after `exec_module` and
registers all `NamedTuple` subclasses in `struct_to_field_type_dict`. Registration is
handled by `_register_struct_recursive`, which recursively registers nested struct field
types (e.g. `vga_pos_t` inside `vga_timing_signals_t`) so that the backend can look up
every field type at any depth. The `@struct`
decorator adds `__class_getitem__` so `point_t[10]` produces `_make_ctype("point_t[10]")`
— a valid array C type object usable in further annotations.

**Factory struct canonical naming (`_pypeline_ctype_name`):**

The `@struct` decorator immediately stamps a **canonical C type name** on the class that
is derived entirely from the class name and field types, with no dependence on the Python
variable name used at the call site. This allows structs created inside nested factories
(where there is no module-level variable name) to have stable, unique names.

**Canonical name rule:**

```
<class_name>_<field1>_<type1_mangled>_<field2>_<type2_mangled>_...
```

where mangling removes array brackets: `uint32_t[2]` → `uint32_t_2`.

Examples:

```python
@struct
class point_t(NamedTuple):
    dim: uint32_t[2]
# _pypeline_ctype_name = "point_t_dim_uint32_t_2"

@struct
class float_t(NamedTuple):
    sign: uint1_t
    exp: uint8_t
    man: uint23_t
# _pypeline_ctype_name = "float_t_sign_uint1_t_exp_uint8_t_man_uint23_t"
```

Two factory calls with the same parameters produce structs with the same canonical
name and the same `struct_to_field_type_dict` entry — correct deduplication with no
redundant generated types.

**Nested factory structs:**

A struct created inside a nested factory is never visible to `_discover_structs_from_module`
(which only walks `vars(module)`). Because `@struct` stamps `_pypeline_ctype_name`
immediately at decoration time, the struct already carries its canonical name when
`_elaborate_live_func` finds it in a closure. `_elaborate_live_func` checks each closure
variable: if a NamedTuple subclass with `_pypeline_ctype_name` is not yet in
`struct_to_field_type_dict`, it is registered there before elaboration begins.

```python
def make_swap(T):
    local_pair_t = make_pair_t(T)   # local — NOT in vars(module)

    def swap(p: local_pair_t) -> local_pair_t:
        rv: local_pair_t = {"a": p.b, "b": p.a}
        return rv

    return swap

swap_u32 = make_swap(uint32_t)
# When swap_u32 is first called:
#   _elaborate_live_func sees local_pair_t in closure
#   local_pair_t._pypeline_ctype_name already = "pair_t_a_uint32_t_b_uint32_t"
#   registers it in struct_to_field_type_dict if not already there
```

`_annotation_to_ctype` reads `getattr(result, '_pypeline_ctype_name', ...)` which is
always set by `@struct` before any annotation resolution occurs. `_struct_class_getitem`
(which backs `point_t[10]` syntax) also uses `_pypeline_ctype_name` so that array types
of factory structs carry the correct canonical base name.

### Conditional Type-Driven Code

Because closure variables are real Python objects at elaboration time, hardware functions
can branch on type properties — this is evaluated completely at elaboration time:

```python
def types_test_foo(point: point_t) -> point_t:
    rv: point_t
    if point_t.style == "array":        # _try_eval_const → True or False → branch elimination
        for i in range(point_t.dim_size):
            rv.dim[i] = point.dim[i]
    else:
        for f in point_t._fields:
            rv[f] = point[f]
    return rv
```

Only the taken branch's hardware is emitted; the other branch produces no Logic() nodes.

---

## Registers (`Reg[T]`)

A local variable annotated `Reg[T]` declares a hardware register — a value that persists
across clock cycles and is initialised to zero at reset.

```python
@MAIN
def accumulator(data_in: uint32_t) -> uint32_t:
    acc: Reg[uint32_t]   # register, init=0
    acc = acc + data_in  # read current value, compute next
    return acc
```

Elaboration treats the annotation specially:

- A register read wire `acc` (type `uint32_t`) is added as a pseudo-input so the body can
  read its current value.
- A register write wire is the wire driven by the assignment to `acc`; it becomes the D
  input of a D-flip-flop in the generated VHDL.
- The return value is the combinational output, distinct from the registered state.

`Reg` is re-exported from `pypeline` as `_RegType`; `Reg[T]` uses `__class_getitem__` to
produce a typed register descriptor that `_elab_ann_assign` recognises.

### Clock Enable and Function Calls

Any function whose `Logic()` contains registers — or calls functions that do, transitively
— requires a `CLOCK_ENABLE` input port. `C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE` determines
this recursively (with caching) by checking `logic.state_regs` and walking
`submodule_instances`.

When `_elab_call` elaborates a call site and the callee needs CE, the current CE wire
(`logic.clock_enable_wires[-1]`) is appended to `input_ports` as the `CLOCK_ENABLE` port
before passing to `_add_submodule_instance`. This produces a `inst____CLOCK_ENABLE` wire
connected to the appropriate gated CE signal.

**Example** — register inside a conditionally-called function:

```python
def accumulator(data_in: uint32_t) -> uint32_t:
    acc: Reg[uint32_t]
    acc = acc + data_in
    return acc

@MAIN
def ce_accum_test(sel: uint1_t, data_in: uint32_t) -> uint32_t:
    rv: uint32_t
    if sel:
        rv = accumulator(data_in)
    return rv
```

Elaboration of `ce_accum_test`:

1. `_elab_if` sees `if sel` → emits `true_ce = MUX(sel, CLOCK_ENABLE, 0)` and pushes it.
2. Inside the true branch, `_elab_call` for `accumulator` runs.
3. `LOGIC_NEEDS_CLOCK_ENABLE(accumulator_logic)` is True (it has `state_regs`).
4. `clock_enable_wires[-1]` is `true_ce` → `accumulator[...]____CLOCK_ENABLE` is wired to `true_ce`.
5. When `sel=0`, `true_ce=0` → `acc` does not update. When `sel=1`, `true_ce=CLOCK_ENABLE` → `acc` updates normally.

---

## Feedback Wires (`Feedback[T]`)

A local variable annotated `Feedback[T]` declares a **combinatorial feedback wire** — a
signal whose driver appears later in Python source order than its first use. This lets
feedforward function bodies describe reverse-direction signals without reordering code.

```python
@MAIN
def feedback_test(a: uint1_t, b: uint1_t) -> uint1_t:
    f: Feedback[uint1_t]   # declare feedback — NOT zero-initialised
    rv: uint1_t = f | a    # read f before it is assigned (uses base wire)
    f = ~b                 # driver of f resolved here
    return rv
```

Elaboration treats the annotation specially:

- A base wire `f` (type `uint1_t`) is added to the logic graph with **no driver** — unlike
  a normal local variable there is no `COMPOUND_NULL` zero wire. Reads of `f` before the
  assignment see this base wire directly.
- `f` is added to `logic.feedback_vars` (a `set` of names on the `Logic()` object).
- Assignments to `f` create alias wires in `wire_aliases_over_time` exactly as any other
  variable assignment.
- At the end of elaboration `_connect_final_state_wires` follows the alias chain and
  connects the final alias back to the base wire (`wire_driven_by["f"] = final_alias`).
  In generated VHDL, `f` is thus driven by `~b`; `rv <= f or a` reads the combinatorial
  value of `f`. Concurrent signal assignment in VHDL means source order is irrelevant.

Unlike `Reg[T]`:
- No flip-flop is inferred — the wire is purely combinatorial within one clock cycle.
- No zero-initialisation or power-on reset value.
- No clock-enable implications; `logic.uses_nonvolatile_state_regs` is not set.

Attempting to initialise a feedback wire at the declaration site is an error:

```python
f: Feedback[uint1_t] = x   # ElaborationError: Feedback wire 'f' cannot have an initializer
```

`Feedback` is exported from `pypeline` as `_FeedbackType`; `Feedback[T]` uses
`__class_getitem__` to produce a typed descriptor that `_elab_ann_assign` recognises,
mirroring the `Reg` / `_RegType` pattern exactly.

---

## Global Wires (`Wire[T]`)

A **module-level** variable annotated `Wire[T]` declares a named combinatorial wire that
is shared across multiple hardware functions. Unlike `Reg[T]` and `Feedback[T]`, `Wire[T]`
is valid **only at module (global) scope** — using it inside a function body is an
`ElaborationError`.

```python
main_a_in:  Wire[uint1_t]   # input into main_a
main_a_out: Wire[uint1_t]   # output from main_a

@MAIN
def main_a():
    main_a_out = ~main_a_in   # writes global; reads global

main_b_in:  Wire[uint1_t]
main_b_out: Wire[uint1_t]

@MAIN
def main_b():
    main_b_out = ~main_b_in

@MAIN
def a_b_connect():
    main_b_in  = main_a_out   # connect output of A into B
    main_a_in  = main_b_out   # connect output of B into A
```

### Discovery

`_discover_global_wires(tree, module_globals, parser_state, name_prefix=None)` scans
`tree.body` for top-level `ast.AnnAssign` nodes whose annotation evaluates to
`_WireType`. For each one a `C_TO_LOGIC.VariableInfo()` is created (with `name` and
`type_name` set) and stored in `parser_state.global_vars[reg_name]`, where
`reg_name = f"{name_prefix}_{bare_name}"` if a prefix is given, else `bare_name`.
An initializer on the declaration is an `ElaborationError`.

For the top-level design file, `name_prefix=None` (names used verbatim). For imported
sub-files, `name_prefix=actual_module_name` so all wires are registered under the
module-prefixed hardware name. See **Multi-File Import Support** for details.

### Read side — behaves like a module input

When a function **reads** a global wire (`main_a_in` on the RHS), the elaborator lazily
initialises it on first use:

- Checks that this function has not already written the same wire (error if so).
- Stores `parser_state.global_vars[name]` into `logic.read_only_global_wires[name]`
  (both point to the same `VariableInfo` object).
- Adds the base wire to `logic.wires` / `logic.wire_to_c_type` with no driver.
- Adds `env[name] = (name, c_type)`.

Subsequent reads of the base name return the base wire directly, exactly like a module
input. Partial-path reads (`wire.field`, `wire[i]`) are handled by `_elab_ref_read`,
which calls the same lazy init if the base var is not yet in `env`.

### Write side — behaves like a module output

When a function **writes** a global wire (`main_a_out = ...` on the LHS), the elaborator
lazily initialises it on first use:

- Checks that this function has not already read the same wire (error if so).
- Stores `parser_state.global_vars[name]` into `logic.write_only_global_wires[name]`.
- Adds the base wire to `logic.wires` / `logic.wire_to_c_type` with **no driver**,
  analogous to a module output port — the combinatorial driver is the final alias.
- Adds `env[name] = (name, c_type)`.

All writes create aliases in `wire_aliases_over_time` via `_write_ref`, as for any
variable. At the end of elaboration `_connect_final_state_wires` follows the alias chain
and connects the final alias back to the base wire (`wire_driven_by[name] = final_alias`).

### Const-path bypass

In `_elab_assign`, the early-return path that caches a pure-Python constant into
`const_env` is **skipped** for global wire names. This prevents `main_a_out = 0` from
being silently cached as an elaboration constant instead of driving the hardware wire.

### Constraints

- A function cannot both read and write the same global wire — `ElaborationError`.
- `Wire[T]` inside a function body — `ElaborationError`.
- `Wire[T]` with an initializer at declaration — `ElaborationError`.
- After all functions are elaborated, each global wire must appear in exactly one
  function's `write_only_global_wires`. Zero writers or multiple writers → `ElaborationError`.
- The writing function must have exactly one instance in the fully-elaborated submodule
  hierarchy (`FuncToInstances[writer]` must contain exactly one key). Multiple instances
  would mean multiple hardware drivers for the same wire → `ElaborationError`.
- Global wires can be read from any number of functions (including non-`@MAIN` functions).

### Implementation mapping

| Concept | Storage |
|---------|---------|
| Discovery | `parser_state.global_vars[name]` → `VariableInfo` |
| Read registration | `logic.read_only_global_wires[name]` (same `VariableInfo`) |
| Write registration | `logic.write_only_global_wires[name]` (same `VariableInfo`) |
| Base wire | `logic.wires`, `logic.wire_to_c_type` (no driver) |
| Alias chain | `logic.wire_aliases_over_time[name]` |
| Final connection | `_connect_final_state_wires` → `wire_driven_by[name] = final_alias` |

`Wire` is exported from `pypeline` as `_WireType`; `Wire[T]` uses `__class_getitem__`
to produce a typed descriptor, mirroring the `Reg` / `Feedback` pattern exactly.

---

## Global I/O (`Input[T]` / `Output[T]`)

`Input[T]` and `Output[T]` are **module-level** annotations that declare top-level
design I/O ports. They follow the same elaboration path as `Wire[T]` with two
extra effects:

- `Input` names are added to `parser_state.input_wires` (a set already defined on
  `C_TO_LOGIC.ParserState`)
- `Output` names are added to `parser_state.output_wires`

```python
global_in:  Input[uint1_t]
global_out: Output[uint1_t]

@MAIN
def global_io_test():
    global_out = ~global_in
```

### I/O Port Names Have No Module Prefix

`Input[T]` and `Output[T]` are **boundary ports** — globally unique by definition, like
an FPGA pin or top-level VHDL entity port. They are stored in `parser_state.global_vars`
under their **bare name only**, with no module prefix. This contrasts with `Wire[T]`,
which gets the `{module_prefix}_{bare_name}` namespace-isolating prefix.

This means `ja_0: Output[uint1_t]` declared in `board/arty/vga_pmod_ja_jb.py` appears in
the VHDL entity as port `ja_0`, matching `board.vhd` exactly with no modifications.

A uniqueness check is enforced: if a bare I/O name is already registered in
`parser_state.global_vars`, `ElaborationError` is raised. This prevents accidental
shadowing between files.

### Discovery

`_discover_global_wires` (called in `PARSE_FILE`) scans `tree.body` for top-level
`AnnAssign` nodes whose annotation evaluates to `_InputType` or `_OutputType`. For
each one a `VariableInfo` is created and stored in `parser_state.global_vars`, and
the name is added to `parser_state.input_wires` or `parser_state.output_wires`.

### Read side — `Input[T]`

Identical to `Wire[T]` reads: lazy init via `_declare_global_read_wire`, which
populates `logic.read_only_global_wires[name]` and adds the base wire with no driver.
Any function may read an `Input[T]` wire.

### Write side — `Output[T]`

Identical to `Wire[T]` writes: lazy init via `_declare_global_write_wire`, which
populates `logic.write_only_global_wires[name]` and adds the base wire with no driver.
`_connect_final_state_wires` connects the final alias back to the base wire at the
end of elaboration, exactly as for `Wire[T]`.

### Constraints

- `Input[T]` is **globally read-only**. Any attempt to write it causes an immediate
  `ElaborationError` in `_declare_global_write_wire` (before `read_only_global_wires`
  conflict check, keyed on `parser_state.input_wires`).
- `Output[T]` requires exactly one writing function with exactly one hierarchy instance
  — the same single-writer / single-instance rule as `Wire[T]`.
- Neither `Input[T]` nor `Output[T]` may appear inside a function body — `ElaborationError`.
- No initializer allowed at declaration — `ElaborationError`.

### Implementation mapping

| Concept | Storage |
|---------|---------|
| Discovery | `parser_state.global_vars[name]` → `VariableInfo` |
| Port set | `parser_state.input_wires` (Input) or `parser_state.output_wires` (Output) |
| Read registration | `logic.read_only_global_wires[name]` (same `VariableInfo`) |
| Write registration | `logic.write_only_global_wires[name]` (same `VariableInfo`) |
| Base wire | `logic.wires`, `logic.wire_to_c_type` (no driver) |
| Alias chain | `logic.wire_aliases_over_time[name]` (Output only) |
| Final connection | `_connect_final_state_wires` → `wire_driven_by[name] = final_alias` (Output) |

`Input` and `Output` are exported from `pypeline` as `_InputType` / `_OutputType`;
both use `__class_getitem__` to produce typed descriptors, mirroring `Wire` exactly.

---

## Multi-File Import Support

Multiple design files can be organized like C's `#include` by using Python's `import`
statement. The top-level file imports sub-files, and the elaborator automatically
discovers and mangles all names from the imported modules.

**Only `import file_a` (qualified attribute access) is supported.**
`from file_a import *` is intentionally excluded: inside a function body, bare-name
assignments like `main_b_in = main_a_out` look like local Python variable creation to
the runtime, which would silently break the proto-simulation layer.

### Motivating example

```python
# file_a.py
i: Wire[uint1_t]
o: Wire[uint1_t]
@MAIN
def main():
    o = ~i

# file_b.py
i: Wire[uint1_t]
o: Wire[uint1_t]
@MAIN
def main():
    o = ~i

# top.py
import file_a
import file_b
@MAIN
def a_b_connect():
    file_b.i = file_a.o   # write file_b_i, read file_a_o
    file_a.i = file_b.o   # write file_a_i, read file_b_o
```

Both sub-files can independently name their wires `i`/`o` and their `@MAIN` function
`main`. The elaborator produces `file_a_i`, `file_a_o`, `file_a_main`, `file_b_i`, etc.

### Name mangling rule

All names from an imported file are prefixed with the **actual module name** (not any
local alias), using a single underscore:

```
hardware_name = {actual_module_name}_{bare_name}   ← Wire[T] only
```

**Exception — `Input[T]` / `Output[T]`:** I/O port names are globally unique boundary
signals and are stored without any module prefix (see **Global I/O** section). This lets
board-specific I/O names appear verbatim in the VHDL entity, matching constraint files
exactly.

- `import file_a` → prefix `file_a` for Wire names; I/O names stay bare
- `import file_a as fa` → Python attribute access uses `fa`, but hardware name is still
  `file_a_i` (not `fa_i`). This ensures that two files importing the same module under
  different aliases still refer to the same hardware wire — preventing phantom
  multiple-driver errors.

The double-underscore `____` SUBMODULE_MARKER used in port wire names is left unchanged;
the single-underscore prefix is distinct and does not conflict.

### `PARSE_FILE` import pre-pass (`_process_imports`)

Before elaborating any hardware functions, `PARSE_FILE` inserts the design file's
directory into `sys.path` so that `import file_a` resolves relative to the design file.
It then calls `_process_imports(tree, module_globals, parser_state, files_to_elaborate, top_file)`,
which scans `tree.body` for `ast.Import` nodes:

For each imported module that is a local `.py` file:

1. Records `local_alias → actual_module_name` in `parser_state.module_alias_to_actual`
   (e.g. `'fa' → 'file_a'` for `import file_a as fa`).
2. Calls `_discover_structs_from_module(sub_mod, parser_state)` to register struct types.
3. Calls `_discover_global_wires(sub_tree, sub_globals, parser_state, name_prefix=actual_name)`
   which registers every `Wire[T]` / `Input[T]` / `Output[T]` in the sub-file under the
   mangled name (`file_a_i`, `file_a_o`) in `parser_state.global_vars`.
4. Appends `(sub_file, sub_tree, sub_globals, actual_name)` to `files_to_elaborate`.

Modules are processed once per file path; a second alias pointing to the same file only
adds an entry to `module_alias_to_actual` without re-parsing. The `top_file` path is
passed to seed `processed_files` so the top file can never be added as its own sub-file.

### Elaboration ordering — sub-files first

`files_to_elaborate` is built with sub-files listed **before** the top file:

```python
files_to_elaborate = []
_process_imports(...)          # appends sub-files
files_to_elaborate.append(top) # top file last
```

This guarantees that all sub-file functions are fully elaborated before the top file's
elaboration begins. If the top file calls a sub-file function
(`rv = pypeline_tests.accumulator(data_in)`), the callee is already complete in
`FuncLogicLookupTable` — no stub lookup race. The stubs registered in step 6 still
exist as forward references for recursive calls within a single file; they are never
hit cross-file as long as this ordering is maintained.

### Wire access in hardware function bodies

**Qualified attribute access** (`file_a.o` in a function body):

```
ast.Attribute(value=ast.Name(id='file_a'), attr='o')
```

In `_elab_expr`, before reaching `_elab_ref_read`, the elaborator calls
`_resolve_module_wire_name(base, attr)`:

1. Checks that `base` (`'file_a'`) is a `types.ModuleType` in `module_globals`.
2. Looks up `base` in `parser_state.module_alias_to_actual` to get the actual module
   name (handles aliases: `fa → file_a`).
3. Constructs `mangled = f"{actual}_{attr}"` and checks it is in `parser_state.global_vars`.
4. If not found, checks the **bare `attr` name** as a fallback — I/O ports are registered
   without module prefix, so `board_vga.ja_0` resolves to bare `"ja_0"`.
5. If found: proceeds exactly like a single-file global wire read/write under the
   resolved name. All lazy-init, alias-chain, and validation logic is unchanged.

In `_elab_assign`, the same check runs before `_parse_ref_toks` on the LHS target,
intercepting `file_a.i = ...` writes.

**Bare-name access inside sub-file functions** (`o = ~i` in `file_a.py`):

Functions elaborated from a sub-file carry `module_prefix='file_a'` on the
`FuncElaborator`. The helper `_resolve_global_wire(bare_name)` first checks
`parser_state.global_vars[bare_name]` directly (for top-file names); if not found and
`module_prefix` is set, it tries `f"{module_prefix}_{bare_name}"`. This means:

- `i` in `file_a.main` → `_resolve_global_wire('i')` → `'file_a_i'` (found)
- `o = ~i` is elaborated as a write to `'file_a_o'` and a read from `'file_a_i'`

`_elab_name` (step 4 global wire path), `_elab_assign` (const-bypass check and
ref_toks normalization), and `_elab_ref_read` (base-var normalization) all call
`_resolve_global_wire` so that compound and indexed accesses also resolve correctly.

### Function name mangling

All hardware functions in sub-files — both `@MAIN` entry points and plain hardware
helper functions (`def adder_extra(a: T, b: T) -> T`) — are elaborated under a
module-prefixed name:

```python
hw_name = f"{mod_prefix}_{node.name}" if mod_prefix else node.name
```

This happens at three sites in `PARSE_FILE`:

- **Stub registration** (step 6): `FuncLogicLookupTable[hw_name] = stub`
- **Elaboration** (step 7): `FuncElaborator` is constructed with `module_prefix`; its
  `__init__` computes `self.func_name = hw_name` so that `logic.func_name` and all
  submodule reference strings use the mangled name automatically.
- **`main_mhz` registration**: uses `hw_name` so the synthesiser sees `file_a_main` as
  the MAIN entry point, not `main`.

**Intra-sub-file calls**: when `file_a.main` calls `adder_extra(x, y)`, `_elab_call`
first attempts `f"{module_prefix}_{callee_name}"` in `FuncLogicLookupTable` before
falling through to `_elaborate_live_func`. This ensures the call site references the
already-elaborated `file_a_adder_extra` entity rather than triggering a duplicate
re-elaboration under the unmangled name.

### Cross-file function calls

The top file (or any file with `module_prefix=None`) can call a function from an
imported sub-module using **attribute call syntax**:

```python
rv = pypeline_tests.accumulator(data_in)   # ast.Call with ast.Attribute func
```

The AST for such a call has `expr.func` as `ast.Attribute` rather than `ast.Name`.
`_elab_call` detects this at the top of the function:

1. Verifies the base (`'pypeline_tests'`) is a `types.ModuleType` in `module_globals`.
2. Fetches the callable via `getattr(base_obj, attr_name)`.
3. Computes `callee_name = f"{actual_module}_{attr_name}"` (e.g. `'pypeline_tests_accumulator'`).
4. Looks up `callee_name` in `FuncLogicLookupTable` — because sub-files are elaborated
   first, this is always a fully-elaborated Logic(), never a stub.
5. If not found (factory closure not yet elaborated): falls through to
   `_elaborate_live_func(callee_name, live_func)`.

The remainder of the call elaboration (port wiring, submodule instance creation) is
identical to the simple-name path.

This same mechanism handles calling factory-closure results from imported modules:

```python
result = pypeline_tests.abs_int32(a)   # make_abs(int32_t, uint32_t) result
```

`abs_int32` is a closure (not a top-level `def`), so it is not pre-elaborated in step 6.
`_elaborate_live_func` handles it on first call; the canonical name from `_canonical_func_name`
(e.g. `make_abs_IN_T_int32_t_OUT_T_uint32_t`) is used for deduplication.

### Module-level constants from imported files

Constants defined in a sub-file (e.g. `SHIFT_AMOUNT = 5` in `pypeline_tests.py`) are
**not** directly accessible in hardware function bodies of the top file. The elaborator
resolves bare names against `module_globals` of the top file; a bare `SHIFT_AMOUNT` is
not there, and `pypeline_tests.SHIFT_AMOUNT` in a hardware body is an `ast.Attribute`
that `_resolve_module_wire_name` rejects (not a wire).

The correct pattern is to copy the constant at module level in the top file:

```python
import pypeline_tests
SHIFT_AMOUNT = pypeline_tests.SHIFT_AMOUNT   # now in module_globals as a plain int
```

Inside hardware function bodies, `SHIFT_AMOUNT` is then resolved via `module_globals`
as an elaboration-time constant (integer), not a hardware wire.

### Struct types — no mangling

`@struct` stamps `_pypeline_ctype_name` from the class name and field types at
decoration time. Two files defining `class point_t` with identical fields produce the
same canonical name and share a single VHDL type — correct deduplication. Files defining
`class point_t` with different field types produce different canonical names based on
field content, so there is no collision without module prefixing.

### Proto-simulation limitation

Global wires in single-file designs already fail when executed as plain Python
(`Wire[T]` creates no Python value — `NameError`). The multi-file form is consistent:
`file_a.o` would raise `AttributeError` at runtime for the same reason. Both limitations
are pre-existing and documented.

### Constraints specific to multi-file imports

- Only `import file_a` (qualified access) is supported; `from file_a import *` is not.
- `import` aliases are resolved to the actual module name for hardware naming:
  `import file_a as fa` → hardware prefix `file_a`, not `fa`.
- Only `.py` source files are processed; `.so`, built-in, and package modules are skipped.
- Each imported file is processed once even if imported under multiple aliases.
- Recursive sub-file imports (`file_a.py` itself importing `file_c.py`) are not
  automatically followed; only the top file's imports are scanned.

### Implementation mapping

| Concept | Storage / location |
|---|---|
| Alias → actual module name | `parser_state.module_alias_to_actual` (dict) |
| Sub-file wire discovery | `_discover_global_wires(..., name_prefix=actual_name)` |
| Module-attr wire lookup | `FuncElaborator._resolve_module_wire_name(base, attr)` |
| Bare-name sub-file wire lookup | `FuncElaborator._resolve_global_wire(bare_name)` |
| Sub-file function hw name | `f"{mod_prefix}_{node.name}"` in PARSE_FILE steps 6–7; `FuncElaborator.func_name` |
| Intra-sub-file call resolution | `_elab_call` prefixed-name lookup before `_elaborate_live_func` |
| Cross-file function call | `_elab_call` `ast.Attribute` branch → `getattr` + `FuncLogicLookupTable` lookup |
| Elaboration order | Sub-files first in `files_to_elaborate`; top file appended last |
| Module constants in top file | `CONST = imported_mod.CONST` at module level copies into `module_globals` |

---

## Compound Initializer Syntax

A local variable of struct or array type can be initialized from a **NamedTuple
constructor call or a list literal** at declaration time (annotated assignment) or in a
plain assignment after the variable is already declared.

```python
# Preferred form — NamedTuple constructor at declaration:
my_point: point2d_t = point2d_t(dim=[0, 1])
rv: pair_t = pair_t(a=p.b, b=p.a)

# Plain assignment (no annotation) — also supported:
pmod_a_wire = pmod8_t(p1=x, p2=y, p3=z, p4=w, p5=a, p6=b, p7=c, p8=d)

# Module-qualified global wire target — also supported:
board_vga.vga_pmod = vga_12bpp_t(r=px.r[7:4], g=px.g[7:4], b=px.b[7:4], hs=px.hs, vs=px.vs)

# Array variable — list literal:
my_arr: uint32_t[2] = [v0, v1]

# Legacy dict form (still elaborated but prefer NamedTuple above):
my_point: point2d_t = {"dim": [0, 1]}           # string-keyed dict
my_point: point2d_t = {"dim": {1: 1, 0: 0}}     # int-keyed dict (C-style)
```

**Elaboration — NamedTuple constructor form:**

`_elab_ann_assign` checks whether the RHS is an `ast.Call` whose callee evaluates
(`_try_eval_const`) to a NamedTuple class (has `_fields`). If so, `_elab_compound_init`
is called with the `ast.Call` node. The `ast.Call` branch in `_elab_compound_init` iterates
over the keyword arguments and recurses with `path_toks + (kw.arg,)` for each field:

```
point2d_t(dim=[v0, v1])  on  my_point: point2d_t
  ├─ kw "dim" → path_toks = ("dim",)
  ├─ list index 0, v0 → _write_ref(("my_point","dim",0), v0_wire, ...)
  └─ list index 1, v1 → _write_ref(("my_point","dim",1), v1_wire, ...)
```

`_try_eval_const` resolves the callee name against `{**module_globals, **const_env}`,
so struct types defined in factory closures (like `float_t` inside `make_float_adder`)
are found correctly.

**Elaboration — list / dict literal forms:**

`_elab_ann_assign` also detects `ast.Dict` or `ast.List` RHS directly and routes to
`_elab_compound_init`. `ast.Dict` keys must be compile-time string or int constants.
`ast.List` elements map to indices 0, 1, 2, … in order.

**`_elab_return` compound forms:**

The same logic applies to `return` statements: `_elab_return` checks for
`ast.Dict`/`ast.List` and NamedTuple constructor calls before the general `_elab_expr`
path, routing them to `_elab_compound_init` with `RETURN_WIRE_NAME` as the base.

After `_elab_compound_init` writes each sub-field alias (e.g. `return_output.r`,
`return_output.g`), `_connect_compound_return` is called to assemble the full struct.
It calls `_read_ref(("return_output",), return_type, ...)`, which finds each sub-field
via the concrete `env` entries and emits a `CONST_REF_RD` assembly submodule. The output
wire of that submodule is then connected to `return_output`, giving the VHDL backend a
visible driver for the return port.

**Elaboration — module-qualified global wire target:**

`_elab_assign` also handles struct constructor calls when the LHS is a module-qualified
global wire (`board_vga.vga_pmod = vga_12bpp_t(...)`). The target is an `ast.Attribute`
node; `_resolve_module_wire_name` mangles it to the hardware wire name, the wire is
declared if needed, and `_elab_compound_init` is called with the `ast.Call` node —
identical to the `ast.Name` plain-assignment path.

**Rules (all forms):**
- Leaf values can be any hardware expression (constants, input wires, sub-expressions).
- Nesting is allowed to arbitrary depth (struct of arrays, array of structs, etc.).
- Applies to annotated assignment (`var: T = …`), plain assignment (`x = MyStruct(...)`),
  module-qualified global wire assignment (`mod.wire = MyStruct(...)`), and return
  statements.

This is **pure elaboration sugar** — the result is identical to writing the assignments
explicitly. No new hardware primitives are introduced.

### Compound Init from Python Function Call

Any **elaboration-time Python function** whose return value is a `dict`, `list`, or
`tuple` can be used as a compound initializer. `_elab_ann_assign` tries
`_try_eval_const` on the RHS before reaching `_elab_expr`; if a dict/list/tuple is
returned it is handed to `_elab_compound_init_from_pyval`:

```python
def make_point_const(x, y):        # plain Python, not a hardware function
    return point_xy_t(x=x, y=y)   # NamedTuple instance — treated as compound init

def my_func(...) -> point_xy_t:
    p: point_xy_t = make_point_const(3, 4)   # NamedTuple instance → compound init
    return p
```

`_elab_compound_init_from_pyval` inspects the returned value:
- **dict** — keys are string/int field or index names
- **`list` / plain `tuple`** — elements map to indices 0, 1, 2, …
- **NamedTuple** (has `_fields`) — field *names* are used as path tokens, matching the
  NamedTuple constructor form. This is important: treating a NamedTuple as a plain tuple
  would use integer indices and break struct field resolution.

**Leaf values must be plain Python `int` or `bool`.** Hardware wires cannot appear
inside the returned value.

### Float Type and `as_const`

`pypeline.make_float_t(E, M)` lets users initialize float struct variables from a Python
float literal at elaboration time:

```python
float32_t = make_float_t(8, 23)   # standard FP32; fields: sign/exp/man

def my_func(...) -> float32_t:
    x: float32_t = float32_t.as_const(1.5)   # returns a float32_t NamedTuple → compound init
    return x
```

`float32_t.as_const(value)` is a plain Python staticmethod that converts a Python `float`
to a `float32_t(sign=…, exp=…, man=…)` NamedTuple instance at elaboration time (using
`struct.pack` for FP32/FP64; a rebased FP64 approximation for other widths). The result is
handled by `_elab_compound_init_from_pyval` exactly as a hand-written NamedTuple instance.

Direct float-literal syntax (`x: float32_t = 1.5`) is **not** supported — the
explicit `.as_const(…)` call is required.

---

## Ternary (IfExp) Assignment

Python's ternary `x = body if test else orelse` is supported in hardware assignments.

```python
out_r: uint4_t = r if sig.active else uint4_t(0)
```

**Elaboration:** `_elab_assign` detects `ast.IfExp` on the RHS and transforms it into a
synthetic `ast.If` statement:

```
x = body if test else orelse
    → if test:
          x = body
      else:
          x = orelse
```

This reuses the full `_elab_if` MUX machinery, including clock-enable propagation and
temporal sorting of covering wires. If the condition evaluates to a compile-time constant
via `_try_eval_const`, the unused branch is eliminated entirely.

---

## Boolean Operators (`and` / `or`)

Python's `and` / `or` keywords produce `ast.BoolOp` nodes and map to bitwise AND / OR
of boolean predicates:

```python
x and y   →   (x != 0) & (y != 0)   # result type: uint1_t
x or y    →   (x != 0) | (y != 0)

# Three-operand form — left-folds:
a and b and c   →   ((a != 0) & (b != 0)) & (c != 0)
```

**Elaboration** (`_elab_bool_op`):

1. **Constant folding first** — `_try_eval_const` is called on the entire `BoolOp` node.
   If the whole expression is a compile-time constant (all operands in `const_env`), a
   CONST wire is emitted directly and no hardware is produced.

2. **AST rewrite** — each operand is wrapped in a synthetic `ast.Compare` node (`!= 0`)
   and the operands are left-folded into a chain of `ast.BinOp` nodes using `ast.BitAnd`
   or `ast.BitOr`. Source locations are preserved with `ast.copy_location` so that every
   synthetic node inherits the position of its original operand, avoiding duplicate instance
   names when the same source line contains multiple `and`/`or` operands.

3. **Delegation** — the rewritten `ast.BinOp` tree is passed back to `_elab_expr`, which
   dispatches through the normal `_elab_binop` / compare paths. No new hardware primitives
   are introduced — the result is the usual combination of `BIN_OP_NEQ` and `BIN_OP_AND`
   or `BIN_OP_OR` submodule instances.

**Why `!= 0` per operand:** hardware types are arbitrary-width integers, not Python bools.
Wrapping each operand in `!= 0` normalizes any non-zero value to `uint1_t(1)` before the
bitwise combination, matching Python's truthiness semantics.

**Example:**

```python
if (t < 2048) and not (d < 2):   # ast.BoolOp(And, [Compare, UnaryOp])
    ...
```

Elaborated as:

```
(t < 2048) != 0   →   BIN_OP_NEQ_uint1_t   →   tmp0 : uint1_t
(not (d < 2)) != 0   →   BIN_OP_NEQ_uint1_t   →   tmp1 : uint1_t
tmp0 & tmp1   →   BIN_OP_AND_uint1_t   →   cond : uint1_t
```

---

## Bit Manipulation Syntax

Several subscript forms on scalar hardware types produce bit-level operations rather than
array indexing. The elaborator detects these in `_elab_expr` / `_elab_assign` by checking
that the base type is a scalar integer (not an array or struct).

### Single-Bit Select

```python
bit: uint1_t = x[15]   # extract bit 15 of uint32_t → uint1_t
```

Elaborated as a `BIT_SELECT_<type>_<pos>` submodule instance.

### Bit-Slice Read

```python
lo_half: uint16_t = x[15:0]          # bare name — extract bits [15:0] → uint16_t
r_hi: uint4_t     = sig.pos.x[7:4]   # struct field access — also supported
```

The slice bounds are evaluated via `_try_eval_const` (must be constants at elaboration time).
Both bare names (`x[hi:lo]`) and attribute-chain expressions (`s.field[hi:lo]`) are handled
by `_try_bit_slice`: the base is elaborated first to obtain its wire and scalar type, then
the slice submodule is emitted. Elaborated as a `BIT_SLICE_<type>_<hi>_<lo>` submodule.

### Bit-Slice Assignment

```python
x[15:0] = y   # write bits [15:0] of x with value y, leaving other bits unchanged
```

Creates a new alias wire for `x` via a `BIT_SLICE_ASSIGN_<type>_<hi>_<lo>` submodule that
takes the old `x` wire and `y` and produces an updated value.

### Bit Concatenation — `concat()` and tuple literal

Bit concatenation packs multiple unsigned integers end-to-end, **first argument in the
most-significant position**. Two syntaxes are supported:

```python
# concat() function — preferred (works in hardware and sim):
out: uint64_t = concat(a, b)          # a:uint32_t ++ b:uint32_t → uint64_t
out: uint64_t = concat(a, b, c)       # a:uint16_t ++ b:uint16_t ++ c:uint32_t → uint64_t

# Tuple literal — hardware elaboration only (cannot run as Python):
out: uint64_t = (a, b)
out: uint64_t = (a, b, c)
```

Both forms elaborate identically: a chain of `TUPLE_CONCAT_<types>` submodule instances.
The output width is the sum of all element widths.

**`concat()` in hardware:** `concat` is in `BIT_MANIP_FUNC_NAMES`. The `concat` branch in
`_elab_bit_manip_call` synthesizes a synthetic `ast.Tuple` from the positional arguments
and delegates to `_elab_tuple_concat`. Any `out_t=` keyword argument (used by the
simulation path for width inference) is ignored.

**`concat()` in simulation:** see the Proto-Simulation section.

---

## Built-in Bit Manipulation Functions

`pypeline` exports several bit-manipulation helpers that elaborate to dedicated submodule
instances. All bounds / counts are evaluated at elaboration time via `_try_eval_const`.

| Function | Signature | Description |
|---|---|---|
| `bit_dup(x, n)` | `(uintW_t, int) → uintW*n_t` | Replicate `x` exactly `n` times end-to-end |
| `rotl(x, n)` | `(uintW_t, int) → uintW_t` | Rotate left by `n` bit positions |
| `rotr(x, n)` | `(uintW_t, int) → uintW_t` | Rotate right by `n` bit positions |
| `bswap(x)` | `(uintW_t,) → uintW_t` | Reverse byte order (W must be a multiple of 8) |
| `bit_assign(base, val, offset)` | `(uintW_t, uintV_t, int) → uintW_t` | Overwrite bits `[offset+V-1:offset]` of `base` with `val` |
| `array_to_uint_be(arr)` | `(uintE_t[N],) → uintE*N_t` | Pack byte array → integer, big-endian (arr[0] = MSB) |
| `array_to_uint_le(arr)` | `(uintE_t[N],) → uintE*N_t` | Pack byte array → integer, little-endian (arr[0] = LSB) |
| `uint_to_array_be(x, n)` | `(uintW_t, int) → uint(W/n)_t[n]` | Unpack integer → array of `n` elements, big-endian |
| `uint_to_array_le(x, n)` | `(uintW_t, int) → uint(W/n)_t[n]` | Unpack integer → array of `n` elements, little-endian |

Each function elaborates to a `BIT_MANIP_<func>_<types>` submodule instance in the
Logic() graph. The output type is derived from the input widths and parameters at
elaboration time.

---

## Custom Operator Registration

Any binary or unary Python operator can be overloaded for specific operand types by
registering a hardware function. The elaborator checks the registry before the built-in
path; registered implementations take full precedence.

### Three registration functions

| Function | Matches on | Use case |
|---|---|---|
| `register_operator(op, lhs, rhs, impl)` | exact `(lhs, rhs)` pair | variable shifts with a specific amount type; arithmetic on struct types |
| `register_left_operator(op, lhs, impl)` | `lhs` only (rhs derived from impl's signature) | variable shifts where the amount width is inferred |
| `register_unary_operator(op, operand, impl)` | operand type | unary negation, custom bitwise ops |

All three accept either a **string name** (module-level callable) or a **callable directly**
as `impl`. They also accept an optional `scope=<callable>` keyword argument for scoped
registrations (see below).

The `op_str` values map to Python operators:

| `op_str` | Python operator |
|---|---|
| `"SL"` | `<<` (shift left) |
| `"SR"` | `>>` (shift right) |
| `"PLUS"` | `+` (addition) |
| `"MINUS"` | `-` (subtraction) |
| `"NEGATE"` | `-` (unary negation) |

### Binary operator lookup in `_elab_binop`

For shift operators (`SL`/`SR`) the elaborator first tries a constant-amount fast path
(`CONST_SL_<n>_<type>`). If the amount is a runtime signal:

```
1. lhs_wire, l_type = _elab_expr(left)
   rhs_wire, r_type = _elab_expr(right)
2. Exact match:  _operator_registry.get((op, l_type, r_type))
3. Left match:   _left_operator_registry.get((op, l_type))
4. If found: resolve impl (string → module_globals lookup, callable → _elaborate_live_func)
            emit submodule instance
5. If not found for a shift: raise NotImplementedError
```

For **all other binary operators** the same exact/left-match lookup runs after the operands
are elaborated. This enables `+` on struct types (e.g. `float32_t + float32_t`) to dispatch
to a registered implementation before falling through to the arithmetic built-in path:

```python
float_add_32 = make_float_adder(float32_t)
register_operator("PLUS", float32_t, float32_t, float_add_32)   # callable, not string

@MAIN
def add_floats(a: float32_t, b: float32_t) -> float32_t:
    return a + b   # dispatches to float_add_32
```

### Unary operator lookup in `_elab_unary`

```
1. op_name = UNARY_OP_MAP[type(expr.op)]   e.g. "NEGATE"
2. operand_wire, typ = _elab_expr(expr.operand)
3. impl = _unary_operator_registry.get((op_name, typ))
4. If found: resolve impl, emit submodule instance; ret_type from callee return wire
5. If not found: fall through to built-in UNARY_OP
      - `NOT` / `~`: output type = operand type
      - `NEGATE` on integers: output type = `int(width+1)_t` (signed, one bit wider)
      - `NEGATE` on floats: output type = operand type
      - Function name always encodes the **input** type (e.g. `UNARY_OP_NEGATE_uint8_t`)
```

### Scoped operator registrations

Registrations made with `scope=<callable>` are **active only while that callable is being
elaborated**. This lets a factory function install temporary operator overloads for the
intermediate types it uses internally, without polluting the global registry:

```python
def make_float_adder(float_t):
    man_t = float_t.typeof('man')
    M_LEN = len(man_t)
    man_hidden_t = make_uint(M_LEN + 1)
    signed_man_t = make_int(M_LEN + 2)
    negate_man_h = make_negate(man_hidden_t, signed_man_t)
    sr_signed    = make_shifter_SR(signed_man_t)

    def float_add(left: float_t, right: float_t) -> float_t:
        x_signed = -x_man_h          # uses scoped NEGATE for man_hidden_t
        y_aligned = y_signed >> diff  # uses scoped SR for signed_man_t
        ...

    register_unary_operator("NEGATE", man_hidden_t, negate_man_h, scope=float_add)
    register_left_operator("SR", signed_man_t, sr_signed, scope=float_add)
    return float_add
```

**Mechanism** (`pypeline.py` + `_elaborate_live_func`):

- Global registries: `_operator_registry`, `_left_operator_registry`, `_unary_operator_registry` — keyed `(op, type_str)` → impl.
- Scoped registries: `_scoped_operator_registry` etc. — keyed `id(scope_func)` → `{key: impl}`.
- `_push_scoped_registrations(func)`: merges the scoped entries for `func` into the global registries, returning a list of `(registry, key, old_value)` triples.
- `_pop_scoped_registrations(saved)`: restores the previous values from that list.
- Called in `_elaborate_live_func` around `elab.elaborate()` in a `try/finally` block so scoped entries are always cleaned up.
- Because the push happens **before** elaboration begins and stays in effect for the entire elaboration, nested callee closures (e.g. `abs_sum` called inside `float_add`) automatically inherit the scoped overloads.

**Resolving `impl`** — `_resolve_registered_impl(impl_name, expr)`:

- If `impl_name` is a **string**: look up in `parser_state.FuncLogicLookupTable`, else in `module_globals`, else raise.
- If `impl_name` is a **callable**: call `_elaborate_live_func(impl_name.__name__, impl_name)` directly (used for scoped callables not at module level).

---

## Pypeline Pragmas (`PART` / `MAIN_MHZ`)

Pypeline provides Python equivalents for the two most common PipelineC C pragmas:

```c
// PipelineC C syntax
#pragma PART "xc7a35ticsg324-1l"
#pragma MAIN_MHZ my_main 100.0
void my_main() { ... }
```

```python
# pypeline Python syntax
PART("xc7a35ticsg324-1l")

@MAIN(100.0)
def my_main(): ...
```

### `PART(...)` — FPGA Target Device

```python
PART("xc7a35ticsg324-1l")
```

Called once at module level (usually near the top of the design file). Sets the global
`_part_registry` string in `pypeline.py`.

`PY_TO_LOGIC.PARSE_FILE` reads `pypeline._part_registry` after executing the module and
writes it to `parser_state.part`. This value is forwarded to the synthesis backend
(Vivado or PYRTL); when `None` the tool chain defaults to a software timing estimator.

### `@MAIN(mhz)` — Clock Frequency Constraint

```python
@MAIN(25.0)         # positional
@MAIN(mhz=25.0)     # keyword
@MAIN               # no constraint (same as before)
def my_main(): ...
```

When an MHz value is provided, `_register_main` records it in `pypeline._main_mhz_registry`
keyed by the function's Python name. `PARSE_FILE` reads this registry and stores the value
in `parser_state.main_mhz[hw_name]` and `parser_state.main_syn_mhz[hw_name]` for every
function found in `main_names`.

`hw_name` is the module-prefixed form (`file_a_main` for imported sub-files, bare name
for the top file), so the synthesiser sees consistent naming regardless of how the MAIN
is reached.

### Clock Domain Inference (`INFER_CLOCK_DOMAINS`)

Most designs import a board support file whose functions are also `@MAIN` entry points (e.g.
`board_vga.vga_to_pmod8`). Those functions carry `main_mhz = None` because the user only
annotates their own top-level MAIN. The inference step propagates the user's MHz to all
other MAINs that share a global wire with a known-MHz MAIN.

The logic lives in `C_TO_LOGIC.INFER_CLOCK_DOMAINS(var_to_rw_main_funcs, var_to_read_func, var_to_write_func, parser_state)`:

- Iterates `parser_state.global_vars`; for each shared global, finds all MAINs that use
  it via `global_var_state_reg_info.used_in_funcs` → `RECURSIVE_FIND_MAIN_FUNCS`.
- If any one MAIN has a non-None MHz, propagates it to the others (same clock group).
- A second pass handles C-style clock-crossing variables (`_WRITE`/`_READ` pairs) via
  `var_to_rw_main_funcs`; these are empty for the Python path.
- Repeats until no further propagation occurs (fixed-point loop).

This function was **extracted from `GET_CLK_CROSSING_INFO`** (which previously embedded
the same loop but was only called on the C code path) so it can be reused by both paths.

`PARSE_FILE` calls it with empty dicts after registering all MAINs:

```python
C_TO_LOGIC.INFER_CLOCK_DOMAINS({}, {}, {}, parser_state)
```

`GET_CLK_CROSSING_INFO` (C path only) calls it with the populated dicts from its regex
search of `preprocessed_c_text`.

---

## Proto-Simulation — Running Pypeline Code as Python

The simulation layer lets pypeline hardware functions execute as ordinary Python, enabling
unit tests to run before hardware synthesis. Pure combinational functions (no `Reg[T]`)
are the natural target; the design is extensible toward full simulation later.

### The Gap Between Hardware and Python

Hardware elaboration uses Python **as an elaboration language**: type annotations, closure
variables, and loop counters are all Python values at compile time, but the function bodies
themselves are compiled to Logic() graphs and never executed. Three specific constructs
prevent naive direct execution:

1. **Bit slicing `x[i]` / `x[hi:lo]`** — Python `int` has no `__getitem__`.
2. **Bit concatenation `(a, b)`** — Python sees a plain tuple, not a bit-cat operation.
3. **Arbitrary-width integer arithmetic** — pypeline integers have fixed widths (e.g.
   `uint24_t`); Python ints are arbitrary precision, so overflow / sign wrapping is silent.

### `SimVal` — Typed Simulation Integer

`SimVal` is a thin subclass of Python `int` that adds:

- **`__getitem__`** for hardware-style bit slicing:
  - `v[i]` → bit `i` (single bit, value 0 or 1)
  - `v[hi:lo]` → bits `hi` down to `lo` inclusive (hardware convention: high index first)
- **Operator dispatch** for unary and binary operators whose type-specific implementations
  are registered via `register_*_operator`:
  - `__neg__` → looks up `"NEGATE"` for `self._ctype` in `_unary_operator_registry`
  - `__rshift__` → looks up `"SR"` (exact `(lhs_type, rhs_type)` then left-only match)
  - `__lshift__` → looks up `"SL"` in the same way
  - Falls back to Python arithmetic if no registration is found
- **Return-type casting** — when dispatch fires and the callee function has a `return`
  annotation, the result is passed through `_sim_cast` to attach the correct `_ctype`
- **Arithmetic passthrough** — `+`, `-`, `*`, `&`, `|`, `^`, `~` return new `SimVals`
  (no `_ctype`, since the result type requires hardware promotion rules to determine)

`SimVal` subclasses `int`, so it is **transparent to the hardware elaborator**: when it
appears as a constant value during `_elab_compound_init_from_pyval`, it is seen as an
ordinary Python int.

### `_sim_cast(val, ctype)` — Type-Correct Masking

Converts a Python int / `SimVal` to a `SimVal` with:
- Value masked to `len(ctype)` bits (implements unsigned wrap-on-overflow)
- Two's-complement sign extension for signed types (`int…_t`)
- `_ctype` set to `ctype`

This is the simulation equivalent of a hardware type assignment and is used in two places:
1. By `hw_func` / `_sim_type_wrap` to cast function inputs and outputs.
2. By `SimVal._dispatch_unary/binary` as a fallback when a dispatched function returns
   an untyped value.

### `@struct` — Auto-Typed Fields

The `@struct` decorator overrides `__new__` on the NamedTuple class so that constructing
any struct instance automatically wraps scalar integer fields in `SimVal`:

```python
float32_t(sign=0, exp=127, man=0)
# → float32_t(sign=SimVal(0, uint1_t), exp=SimVal(127, uint8_t), man=SimVal(0, uint23_t))
```

Only scalar pypeline integer fields (those whose ctype passes `_is_scalar_pypeline_int`)
are wrapped. Array and nested-struct fields are passed through unchanged.

This means `left.exp` in `float_add` carries the correct `_ctype` (`uint8_t` for float32),
so `concat(x_hidden, left.man)` can infer field widths without being told.

**Hardware transparency:** `SimVal` subclasses `int`, so struct instances returned by
`as_const` or any constant helper are seen as plain integers by `_elab_compound_init_from_pyval`.

### `concat(*args)` — Simulation Bit Concatenation

```python
x_man_h: man_hidden_t = concat(x_hidden, x.man)
```

Width of each argument is inferred:
- `SimVal` with `_ctype` → `len(_ctype)` bits
- Plain Python `int` → `max(1, val.bit_length())` bits (mirrors hardware literal inference)

The result is a `SimVal` with `_ctype = make_uint(total_bits)`. For float32 where
`x.man` has ctype `uint23_t` and `x_hidden` is `0` or `1` (1-bit), the result has ctype
`uint24_t`, which matches `man_hidden_t`. This ctype then enables operator dispatch
(e.g. `-x_man_h` dispatches to the registered `negate_man_h`).

In hardware, `concat` is handled by `_elab_bit_manip_call` → `_elab_tuple_concat` (see Bit
Concatenation above). The `out_t=` keyword argument sometimes used in sim for clarity is
simply ignored on the hardware path.

### `@hw_func` / `_sim_type_wrap` — Per-Function Type Propagation

The `@hw_func` decorator wraps a pypeline hardware function to propagate type information
through the simulation call graph:

1. **Instance path:** pushes `(func_qualname, call_loc)` onto `_sim_inst_stack` before
   the call and pops it in a `finally` block after. `call_loc = (filename, lineno,
   col_offset, end_col_offset)` is captured from the caller's frame via `sys._getframe(1)`,
   mirroring the hardware elaborator's `_loc_str` instance-naming convention. This enables
   multi-instance register simulation (see **`Reg[T]` Simulation** below).
2. **On entry:** each positional argument is cast to its annotated parameter type via
   `_sim_cast` (scalar integer args only; array/struct args pass through).
3. **Scoped operators:** `_push_scoped_registrations(original_fn)` is called, making any
   operators registered with `scope=fn` temporarily active.
4. **On exit:** the return value is cast to the annotated return type via `_sim_cast`
   (if scalar integer).

`functools.wraps` preserves `__name__`, `__annotations__`, and merges `__dict__`, so
custom attributes like `clz.out_t` or `shifter_SL.amount_t` survive the wrapping.

**Hardware transparency:** `_elaborate_live_func` calls `inspect.unwrap(func)` before
`inspect.getsource` and closure extraction, so `@hw_func`-wrapped functions elaborate
from the original source code, not the wrapper body. The merged namespace for elaboration
also uses `func_for_source.__globals__` (the unwrapped function's globals, e.g.
`vga/timing.py`'s imports) rather than `func.__globals__` (the wrapper function's globals,
which are `pypeline.py`'s imports). This matters when `@hw_func` is applied to a closure
defined in a sub-module — without it, types imported at the top of the closure's source
file (e.g. `vga_pos_t`) would be missing from the elaboration namespace.

**`_sim_active` guard — elaborator-probing protection:**

The `@hw_func` wrapper has this guard at its start:

```python
if not _sim_active:
    return fn(*args, **kwargs)
```

`_sim_active` is `False` by default in `pypeline.py`. It is set to `True` in two places:

- `pypeline_sim.py` sets `pypeline._sim_active = True` before the first clock cycle of
  a multi-MAIN simulation run.
- `sim_call` sets `_sim_active = True` for the duration of each call (see below). This
  covers direct unit tests that call `sim_call` without going through `pypeline_sim.py`.

The hardware elaborator (`pipelinec`) is a separate process that never calls `sim_call`
and never sets this flag — it probes functions directly.

This guard is needed because `_elab_assign` calls `_try_eval_const(stmt.value)` on every
assignment RHS to test whether the RHS is a plain Python constant. `_try_eval_const`
evaluates the expression in `{**module_globals, **const_env}` — which includes live
callables like `vga_timing`. If the wrapper were always active:

- The elaborator calls `vga_timing()` via `_try_eval_const`
- The `@hw_func` wrapper runs the simulation body → returns a concrete `vga_timing_signals_t`
- `_try_eval_const` returns non-`None` → the result is stored in `const_env`
- Later, `sig` (= the constant) is used in `test_pattern(sig)` → elaboration error:
  *"Cannot emit non-int Python value as hardware"*

With the `_sim_active` guard, calling `vga_timing()` outside of simulation falls through
to the raw closure, which raises `UnboundLocalError` on its unbound `Reg[T]` variables.
`_try_eval_const` catches that exception, returns `None`, and the elaborator uses the
hardware path (`_elaborate_live_func`) correctly.

**Scoped operator key correctness:** scoped ops are registered with `scope=func` where
`func` is the name at the point of the `register_*_operator` call. If `@hw_func` has
already been applied, `func` is the wrapped version. `_elaborate_live_func` passes the
original `func` argument (the wrapped version) to `_push_scoped_registrations`, so the
correct `id` is used to look up the scoped registry.

**Usage in factory functions:**

```python
def make_negate(value_t, out_t):
    @hw_func
    def negate(a: value_t) -> out_t:
        a_signed: out_t = a
        return ~a_signed + 1
    return negate

def make_clz(value_t):
    n_bits = len(value_t)
    out_t = make_uint(n_bits.bit_length())
    @hw_func
    def clz(v: value_t) -> out_t:
        result: out_t = n_bits
        for i in range(n_bits):
            if v[i]:
                result = n_bits - 1 - i
        return result
    clz.out_t = out_t    # preserved by functools.wraps
    return clz
```

### `@MAIN` Implies `@hw_func`

Because every `@MAIN` function is a top-level hardware entry point, `@MAIN` automatically
applies `_sim_type_wrap` to the decorated function before registering it.

`@MAIN` supports three calling forms, all of which are simulation-transparent:

```python
@MAIN               # no clock constraint
@MAIN(100.0)        # positional MHz
@MAIN(mhz=100.0)    # keyword MHz
def my_main(): ...
```

The implementation dispatches on whether the first argument is callable (bare `@MAIN`) or
numeric (`@MAIN(mhz)`):

```python
def MAIN(func_or_mhz=None, *, mhz=None):
    if callable(func_or_mhz):
        return _register_main(func_or_mhz, mhz=None)
    else:
        if func_or_mhz is not None:
            mhz = float(func_or_mhz)
        def decorator(func):
            return _register_main(func, mhz=mhz)
        return decorator

def _register_main(func, mhz):
    if mhz is not None:
        _main_mhz_registry[func.__name__] = float(mhz)
    wrapped = _sim_type_wrap(func)
    _main_registry.append(wrapped)
    return wrapped
```

`_main_registry` stores the wrapped function; `{f.__name__}` for name lookup works
because `functools.wraps` copies `__name__`. The hardware elaborator scans the source
AST directly (not through the registry callable), so hardware generation is unaffected.

`_main_mhz_registry` maps `func.__name__` → MHz and is read by `PY_TO_LOGIC.PARSE_FILE`
when populating `parser_state.main_mhz`; it is unused during simulation.

### `sim_call(func, *args)` — Simulation Entry Point

```python
result = sim_call(float_add_32, fp32_sim(1.0), fp32_sim(2.0))
```

`sim_call` activates `_sim_active`, pushes scoped operator registrations keyed on
`id(func)` before calling, then restores both in a `finally` block:

```python
def sim_call(func, *args, **kwargs):
    global _sim_active
    prev_active = _sim_active
    _sim_active = True
    saved = _push_scoped_registrations(func)
    try:
        return func(*args, **kwargs)
    finally:
        _pop_scoped_registrations(saved)
        _sim_active = prev_active
```

**`_sim_active` in `sim_call`:** Setting `_sim_active = True` here ensures that direct
unit tests (which call `sim_call` without going through `pypeline_sim.py`) also get the
sim bodies for `@hw_func`-wrapped functions with `Reg[T]` variables. Without this,
calling a `@hw_func`-wrapped function like `accumulator(data_in)` — which has
`acc: Reg[uint32_t]` — would fall through to the raw function, raising
`UnboundLocalError: local variable 'acc' referenced before assignment`. The elaborator is
never affected because it calls functions directly without `sim_call`.

**Key design choice:** `func` is used directly (not `inspect.unwrap`). When `@hw_func`
is applied to `float_add`, the scoped operators are registered under `id(wrapped_float_add)`
(since `scope=float_add` refers to the wrapped name). Using `func` as-is ensures the
correct `id` is used. The `@hw_func` wrapper's own `_push_scoped_registrations(original)`
call uses the original's `id`, which has no scoped ops — a deliberate no-op.

If `@hw_func` is not applied to the target function, `func = original`, and
`id(func) = id(original)` matches the scoped op key — also correct.

### Writing a Sim Test

```python
def test_float_add_32():
    import struct as _struct

    def fp32_sim(f):
        bits = _struct.unpack(">I", _struct.pack(">f", float(f)))[0]
        return float32_t(           # @struct __new__ wraps fields in typed SimVals
            sign=(bits >> 31) & 1,
            exp=(bits >> 23) & 0xFF,
            man=bits & 0x7FFFFF,
        )

    def sim_to_float(r):
        bits = (int(r.sign) << 31) | (int(r.exp) << 23) | int(r.man)
        return _struct.unpack(">f", _struct.pack(">I", bits))[0]

    cases = [(1.0, 2.0, 3.0), (0.0, 0.0, 0.0), (-1.0, 2.0, 1.0), (1.5, 2.5, 4.0)]
    for a, b, expected in cases:
        result = sim_call(float_add_32, fp32_sim(a), fp32_sim(b))
        assert sim_to_float(result) == expected

if __name__ == "__main__":
    test_float_add_32()
```

### Type Propagation Through the FP Adder Call Chain

```
sim_call(float_add_32, left, right)
  │ _push_scoped_registrations(float_add_32)
  │   → pushes NEGATE(uint24_t), NEGATE(int26_t), SR(int25_t, uint8_t), SL(uint24_t, uint5_t)
  │
  ├─ float_add(left, right)   [hw_func wrapper casts float_t args — no-op for struct inputs]
  │   ├─ left.man → SimVal(man_val, uint23_t)       ← from @struct auto-wrap
  │   ├─ concat(x_hidden, left.man)
  │   │     width(x_hidden=1) + width(left.man=23) = 24 bits → SimVal(…, uint24_t)
  │   ├─ -x_man_h   → dispatches to negate_man_h (NEGATE for uint24_t)
  │   │     hw_func wrapper casts result → SimVal(…, int25_t)
  │   ├─ y_signed >> diff   → dispatches to sr_signed (SR for int25_t × uint8_t)
  │   │     hw_func wrapper casts result → SimVal(…, int25_t)
  │   ├─ abs_sum(sum_man)   [hw_func wrapper casts sum_man → SimVal(…, int26_t)]
  │   │   └─ -a  → dispatches to negate_sum_man (NEGATE for int26_t, scoped active)
  │   └─ result: float_t = float_t(sign=…, exp=…, man=…)  → real float_t instance
  │
  └─ result is a float32_t NamedTuple (not a dict, thanks to NamedTuple constructor form)
```

### `Reg[T]` Simulation — Stateful Registers Across Clock Cycles

Functions that contain `Reg[T]` state registers can be simulated. Two problems must be
solved:

**Problem 1 — local annotation creates no Python variable.**
`acc: Reg[uint32_t]` inside a function body is a Python annotation-only statement; it
does not create a local variable. Python's `fn.__annotations__` does NOT include local
variable annotations (only parameter and return annotations). Any subsequent read of
`acc` raises `NameError`.

**Problem 2 — same function, multiple hardware instances.**
In hardware, each call site of `accum_func` is a distinct flip-flop instance. In the
example below, lines 71 and 73 are two separate instances with independent `acc`
registers. The simulator must route reads and writes to the correct per-instance copy.

Both problems are solved by **`_build_reg_sim_func`** (called once at `@hw_func`/`@MAIN`
decoration time) combined with the **instance path stack** maintained in `_sim_type_wrap`.

#### Instance Path Stack

`_sim_inst_stack` is a module-level list. Each `@hw_func`/`@MAIN` wrapper pushes
`(func_qualname, (filename, lineno, col_offset, end_col_offset))` before calling the
function body and pops it in `finally`. The `call_loc` tuple is read from the
**caller's** frame (`sys._getframe(1)`) so that two calls to the same function at
different source lines produce different entries, exactly as the hardware elaborator
produces distinct instance names from `_loc_str`.

`_sim_current_inst_path()` returns `tuple(_sim_inst_stack)` — an immutable snapshot
used as the dict key for register state.

#### Per-Instance Register State

```python
_sim_reg_state: dict[tuple, dict[str, object]]
# _sim_reg_state[inst_path][reg_name] = current value
# (int 0 for scalars, zero-initialised struct/array for compound types)
```

Three helpers manage it:

```python
def _make_sim_zero(ctype): ...
# Returns 0 for scalar types; recursively constructs a zero-initialised
# NamedTuple instance for @struct types (mirrors pypeline_sim._make_sim_zero).

def _sim_reg_read(inst_path, reg_name, default=0): ...
# Returns the stored value, or `default` if the register has never been written.
# _build_reg_sim_func passes a type-appropriate zero (from _make_sim_zero) so
# compound registers return a zero struct rather than integer 0.

def _sim_reg_write(inst_path, reg_name, value): ...
# Stores value as-is — struct/array instances are preserved without int() coercion.
```

`sim_reset()` clears `_sim_reg_state` entirely, equivalent to a hardware power-on reset.
Call it at the start of each independent sim test.

#### `_build_reg_sim_func` — AST Transformation at Decoration Time

When `@hw_func` is applied to a function, `_sim_type_wrap` calls `_build_reg_sim_func(fn)`.
This function:

1. Retrieves source via `inspect.getsource(inspect.unwrap(fn))` + `textwrap.dedent`.
2. Parses the source with `ast.parse` and finds the top-level `FunctionDef`.
3. **Rewrites global wire accesses** — scans `fn.__globals__['__annotations__']` for
   `Wire[T]`/`Input[T]`/`Output[T]` names and applies `_GlobalWireRewriter` to the
   function body AST. This replaces all reads of those names with `_sim_wire_read(name)`
   calls and all assignments to them with `_sim_wire_write(name, value)` calls.
4. **Discovers registers and feedback wires** by evaluating each annotation-only `AnnAssign`
   node in the (now wire-rewritten) body against `fn.__globals__` — the only way to detect
   `_RegType`/`_FeedbackType` instances without running the hardware elaborator (because
   Python never stores local variable annotations in `__annotations__`).
5. If no `_RegType`, `_FeedbackType`, or global wire names are found, returns `None`
   (no transformation needed).
6. Otherwise builds a **transformed function body**:

```python
# generated at decoration time — not user-written:
def accum_func(data_in: uint32_t) -> uint32_t:
    __ip__ = _sim_current_inst_path()
    acc    = _sim_reg_read(__ip__, "acc", __reg_zero_acc__)   # ← type-appropriate reset default
    try:
        # original body with Reg[T] AnnAssign nodes removed:
        acc = acc + data_in
        return acc
    finally:
        _sim_reg_write(__ip__, "acc", acc)  # ← writes next-cycle value for this instance
```

The `try/finally` pattern handles all return paths (including multiple `return`
statements and exceptions). Python's `finally` executes with `acc` at its **final
local value** before the frame is torn down, so the written-back value is always correct.

`__reg_zero_acc__` is injected into the generated function's `__globals__` at decoration
time as `_make_sim_zero(ann_val.inner_ctype)`. For scalar types (e.g. `uint32_t`) this is
plain `0`; for compound types (e.g. `Reg[vga_12bpp_t]`) this is a zero-initialised struct
instance. This means accessing fields like `vga_pmod_reg.r[0]` on an uninitialised register
works correctly — the register already holds a proper struct rather than integer `0`.

Values are stored as-is by `_sim_reg_write` (no `int()` coercion), so struct values
survive write-back across clock cycles.

Decorator nodes are stripped before `compile`/`exec` to prevent re-wrapping. The
compiled function's `__globals__` is a copy of `fn.__globals__` augmented with the sim
helpers and per-register zero defaults, so all user-defined types and constants remain
in scope.

The transformation is done **once at decoration time** and the result is captured in
`wrapper`'s closure as `sim_body_fn`. Subsequent calls invoke `sim_body_fn` instead of
the original `fn`.

This mechanism is transparent to the hardware elaborator: `_elaborate_live_func` calls
`inspect.unwrap(fn)` to recover the original, unmodified function object.

#### Multi-Instance Trace

```python
@hw_func
def accum_func(data_in: uint32_t) -> uint32_t:
    acc: Reg[uint32_t]
    acc = acc + data_in
    return acc

@MAIN
def regs_multi_inst(sel: uint1_t, data_in: uint32_t) -> uint32_t:
    rv: uint32_t
    if sel:
        rv = accum_func(data_in)  # line 71 → instance1
    else:
        rv = accum_func(data_in)  # line 73 → instance0
    return rv
```

```
sim_reset()

sim_call(regs_multi_inst, sel=1, data_in=1)
  regs_multi_inst wrapper → push ("regs_multi_inst", (test.py, sim_call_line, …))
    sel=1 → if branch at line 71
    accum_func wrapper → push ("accum_func", (test.py, 71, col, end_col))
      inst_path = (("regs_multi_inst", …), ("accum_func", (test.py, 71, …)))
      acc = _sim_reg_read(inst_path, "acc") → 0   (first call, reset value)
      acc = 0 + 1 = 1
      finally: _sim_reg_write(inst_path, "acc", 1)
    accum_func wrapper → pop; return 1
  → rv = 1; result = 1  ✓

sim_call(regs_multi_inst, sel=0, data_in=1)
    sel=0 → else branch at line 73
    accum_func wrapper → push ("accum_func", (test.py, 73, …))   ← different line!
      inst_path ends in (test.py, 73, …) — distinct from instance1
      acc = _sim_reg_read(inst_path, "acc") → 0   (instance0, first call)
      acc = 0 + 1 = 1
      finally: _sim_reg_write(inst_path, "acc", 1)
    → result = 1  ✓

sim_call(regs_multi_inst, sel=1, data_in=1)
    accum_func wrapper → push ("accum_func", (test.py, 71, …))
      acc = _sim_reg_read(inst_path, "acc") → 1   (instance1 saved from first call)
      acc = 1 + 1 = 2
      finally: _sim_reg_write(inst_path, "acc", 2)
    → result = 2  ✓
```

**`@hw_func` requirement:** functions with `Reg[T]` annotations must be decorated with
`@hw_func` (or be a `@MAIN` function) for register simulation to work. This is already
the intended pattern — `@hw_func` marks any hardware-typed helper function.

**`col_offset` / `end_col_offset`:** available on Python 3.11+ via
`frame.f_code.co_positions()`. On earlier Python versions the tuple falls back to
`(filename, lineno, None, None)`, which is still sufficient to distinguish call sites
since two calls to the same function on the same line would be unusual.

---

### `Feedback[T]` Simulation — Combinatorial Convergence

Functions that contain `Feedback[T]` wires can be simulated. In hardware, the feedback wire
creates a combinatorial loop that the synthesiser resolves concurrently; in Python's sequential
execution, reading `f` before `f = ~b` would raise `NameError`. The solution mirrors real
hardware behaviour: iterate the function body until the feedback value stabilises.

**Two problems** (same as `Reg[T]`):

1. **`NameError` before assignment** — `f: Feedback[uint1_t]` is an annotation-only statement
   and creates no local variable. Any read of `f` before `f = ~b` raises `NameError`.
2. **Combinatorial convergence** — in hardware, feedback wires have no meaningful initial
   state within a clock cycle; the stable combinatorial value emerges iteratively.

Both are solved by **`_build_reg_sim_func`** (which now handles both `Reg[T]` and
`Feedback[T]`) combined with `_sim_type_wrap`.

#### Transformation

`_build_reg_sim_func` detects `Feedback[T]` annotation-only statements the same way it
detects `Reg[T]` — by evaluating each `AnnAssign` annotation against `fn.__globals__`
and checking `isinstance(ann_val, _FeedbackType)`.

The transformed function wraps the original body in a convergence loop:

```python
# generated at decoration time:
def feedback_test(a: uint1_t, b: uint1_t) -> uint1_t:
    f = 0              # ← zero-initialise each feedback var
    __fb_iters = 0
    while True:
        __fb_iters += 1
        if __fb_iters > _SIM_FEEDBACK_MAX_ITER:
            raise RuntimeError("Feedback[T] sim: convergence failed in 'feedback_test'")
        __fb_snap_f = f    # ← snapshot before this pass
        # original body with Feedback[T] AnnAssign and trailing return removed:
        rv = f | a
        f = ~b
        if f == __fb_snap_f:   # ← all feedback vars must match snapshot
            break
    return rv          # ← trailing return moved outside the loop
```

The `return` statement is extracted from the end of the original body and placed after the
convergence loop. Hardware functions have exactly one `return` as their final top-level
statement, so this extraction is always safe.

#### Convergence trace for `feedback_test(a=0, b=0)`

```
Pass 1: f=0 (init)
  rv = 0 | SimVal(0, uint1_t) = 0
  f  = ~SimVal(0, uint1_t)    = SimVal(-1)    ← Python arbitrary-precision ~0
  f(-1) ≠ snap(0) → re-run

Pass 2: f=SimVal(-1)
  rv = SimVal(-1) | SimVal(0, uint1_t) = SimVal(-1)
  f  = ~SimVal(0, uint1_t)              = SimVal(-1)
  f(-1) == snap(-1) → converged; break

@MAIN boundary: _sim_cast(-1, uint1_t) → SimVal(1, uint1_t)   ← mask to 1 bit
assert result == 1  ✓
```

Note: Python's `~` on unmasked ints gives `-1` for `~0`, not `1`. Convergence still works
because the same computation produces the same value in both iterations. The `_sim_cast` at
the `@MAIN` boundary correctly masks the final result.

#### Interaction with `Reg[T]`

When a function contains both `Reg[T]` and `Feedback[T]`, the unified transformation handles
both. Registers are reset to their initial (pre-loop) values at the start of every convergence
iteration, so they act as constant combinatorial inputs throughout — matching hardware
semantics where combinatorial feedback resolves before the clock edge latches any state.

```python
# generated at decoration time (feedback + register):
def fb_reg_accumulate(load: uint1_t, data: uint8_t) -> uint8_t:
    __ip__ = _sim_current_inst_path()
    acc = _sim_reg_read(__ip__, "acc")   # ← read register once
    __reg_init_acc = acc                 # ← snapshot for per-iteration reset
    f = 0                                # ← zero-init feedback
    __fb_iters = 0
    try:
        while True:
            __fb_iters += 1
            if __fb_iters > _SIM_FEEDBACK_MAX_ITER: raise RuntimeError(...)
            acc = __reg_init_acc         # ← reset reg to initial each pass
            __fb_snap_f = f
            # original body:
            out = acc + f
            f = acc & 1
            acc = data if load else out
            if f == __fb_snap_f: break
    finally:
        _sim_reg_write(__ip__, "acc", acc)   # ← commit register after convergence
    return out
```

`_SIM_FEEDBACK_MAX_ITER = 1000` is the safety limit; valid combinatorial feedback converges
in very few iterations (typically 1–2).

**`@hw_func` requirement:** functions with `Feedback[T]` annotations must be decorated with
`@hw_func` (or be a `@MAIN` function) for the simulation infrastructure to engage.

---

### `Wire[T]` / `Input[T]` / `Output[T]` Global Wire Simulation — Multi-MAIN Convergence

Global wire simulation requires running multiple `@MAIN` functions together, not just calling
a single function with `sim_call`. A dedicated CLI tool `pypeline_sim.py` handles this.

#### The Core Problem

`Wire[T]` declarations at module level only create `__annotations__` entries — no Python
variable is created. Inside a `@MAIN` function, `main_a_out = r` would silently create a
local variable, and `r = ~main_a_in` would raise `NameError`. The sim must intercept both
reads and writes at every point they occur in the function body, including deep in the call
hierarchy.

#### `_GlobalWireRewriter` — AST Transformation at Decoration Time

`_build_reg_sim_func` is extended to discover global wire names from the function's defining
module (`fn.__globals__['__annotations__']`) and apply a `_GlobalWireRewriter` NodeTransformer
to the parsed function body AST **before** the `Reg[T]`/`Feedback[T]` transformations run.

`_GlobalWireRewriter` rewrites:

| Original AST | Transformed AST |
|---|---|
| `Name(id='wire', ctx=Load)` | `_sim_wire_read('wire')` |
| `wire = expr` (Assign) | `_sim_wire_write('wire', expr)` (Expr stmt, no local binding) |
| `wire: T = expr` (AnnAssign with value) | `_sim_wire_write('wire', expr)` |
| `module_alias.wire` (Attribute, Load) | `_sim_wire_read('wire')` |
| `module_alias.wire = expr` (Attribute, Store) | `_sim_wire_write('wire', expr)` |

Module-level wire declarations (`wire: Wire[T]` with no value) are `AnnAssign` nodes
with `value=None` and are left untouched.

For cross-module wire access (`board_vga.vga_pmod = ...`), `_build_reg_sim_func` also scans
all module objects in `fn.__globals__` for `Wire[T]`/`Input[T]`/`Output[T]` annotations and
builds a `module_wire_attrs` dict `{(alias_name, attr_name): bare_wire_name}`. This is passed
to `_GlobalWireRewriter` alongside the bare `global_wire_names` set.

The transformed globals dict passed to `exec` includes `_sim_wire_read` and `_sim_wire_write`
alongside the existing `_sim_reg_read`, `_sim_reg_write`, and `_SIM_FEEDBACK_MAX_ITER`.

This transformation is transparent to the hardware elaborator: `_elaborate_live_func` calls
`inspect.unwrap(fn)` to recover the original unmodified source.

**Closure variable support:** `_build_reg_sim_func` builds `_eval_ns` from `fn.__globals__`
plus any closure variables (`fn.__code__.co_freevars` / `fn.__closure__`). This enables
`@hw_func`-decorated closures like `vga_timing` (returned by `make_vga_timing`) to have their
`Reg[T]` annotations evaluated correctly (e.g. `Reg[h_uint]` where `h_uint` is a free variable).
The same `_eval_ns` is used as the base for `new_globals` so that closure-captured constants
(`FRAME_WIDTH`, `H_MAX`, etc.) are accessible in the generated sim body.

The `@hw_func` wrapper on such closures is transparent to the hardware elaborator via two
mechanisms: (1) the `_sim_active` guard prevents the sim body from running when the elaborator
probes the function via `_try_eval_const`; (2) `_elaborate_live_func` uses `func_for_source.__globals__`
(the unwrapped original's imports) not `func.__globals__` (the wrapper's imports in `pypeline.py`).
See `@hw_func / _sim_type_wrap` section for details.

#### Global Wire State

```python
_sim_wire_state: dict[str, int]
# wire name (not instance path) → current integer value
```

Wire names are singletons — they are not keyed by instance path. Reads and writes use the
bare wire name as declared at module level.

```python
def _sim_wire_read(name: str)       # returns 0 if wire not yet driven; records reader dependency
def _sim_wire_write(name: str, value) -> None:  # stores value as-is (struct types preserved)
```

`sim_reset()` clears both `_sim_reg_state` and `_sim_wire_state`.

#### `pypeline_sim.py` — Multi-MAIN Clock-Cycle Simulation

`pypeline_sim.py` is a CLI tool for running multi-MAIN designs:

```
pypeline_sim.py <design_file.py> --run <N>
```

It imports the design file (triggering all `@MAIN`/`@hw_func` decorations, populating
`_main_registry`), discovers global wires from module `__annotations__` (recursively scanning
imported sub-modules), and runs N clock cycles. Multi-file designs are supported.

**Per clock cycle:**

1. Register writes are switched to buffered mode (`_sim_reg_begin_buffer`).
2. `_sim_converging = True`; the delta-cycle convergence queue runs.
3. `_sim_converging = False`; all MAINs run once more — the **final pass** — where
   `@sim_output` functions fire and any plain `print()` or side-effect code executes with
   the correct converged wire values.
4. Buffered register writes flush to `_sim_reg_state` (`_sim_reg_flush_buffer`) — the
   simulated clock edge; all flip-flops update simultaneously.

#### Delta-Cycle Convergence (Queue-Based)

Each convergence iteration uses a queue rather than round-robin to avoid unnecessary
re-executions. This mirrors VHDL delta-cycle / Verilog event-driven simulation.

```
queue = all MAINs          ← start of each cycle
wire_readers = {}          ← persistent across cycles; built lazily

while queue not empty:
    main = dequeue()
    snapshot wire state
    set _sim_current_main = main
    sim_call(main)          ← _sim_wire_read records main as reader of each wire it reads
    _sim_current_main = None

    for each wire whose value changed:
        for each MAIN that has read that wire (from wire_readers):
            if not already queued: enqueue it
```

`_sim_wire_readers: dict[str, set]` is populated lazily as MAINs run. After the first
clock cycle, the dependency graph is fully built and only affected MAINs are re-queued in
subsequent cycles. The queue is empty when no wire changed — the global fixed point.

A safety limit of 10 000 total MAIN executions per cycle guards against combinatorial
loops; the error message lists the wires still changing.

#### Register Commit Timing Across MAINs

Registers must not commit until all MAINs have converged globally — just as hardware
flip-flops all latch simultaneously at the clock edge. Two mechanisms ensure this:

1. **Buffered writes:** `_sim_reg_write` checks `_sim_reg_write_buffer`. When buffering
   is active, writes accumulate in the buffer dict instead of updating `_sim_reg_state`.
   Each MAIN re-run during convergence overwrites its own buffer entries (correct — the
   final re-run with stable inputs produces the right next-cycle value).

2. **Simultaneous flush:** after the final pass, `_sim_reg_flush_buffer` copies all
   buffered entries to `_sim_reg_state` in one operation.

#### `@sim_output` — Controlled Side Effects

Functions decorated with `@sim_output` are called normally during the final pass but are
no-ops (returning `SimVal(0)`) during convergence iterations. This prevents `print`,
file writes, matplotlib updates, etc. from firing multiple times with intermediate wire values.

```python
@sim_output
def my_output(data):
    print(f"output: {data}")
    plt.update(data)

@MAIN
def main_a():
    r: Reg[uint1_t]
    main_a_out = r
    r = ~main_a_in
    my_output(r)    # skipped during convergence; fires once per cycle in final pass
```

Plain Python functions without `@sim_output` execute during every convergence iteration —
the correct default for pure helper functions (e.g. `c = compute_constant()`). The
`_sim_converging` flag is exposed for opt-in guards if needed.

#### `@sim_output` in Hardware Elaboration — `_elab_stmt` Skip

A `@sim_output` call appearing as a bare expression statement in a `@MAIN` body must be
invisible to the hardware elaborator (`PY_TO_LOGIC`). The elaborator normally raises
`NotImplementedError` for any `ast.Expr` statement that is not a bare string constant.
A dedicated guard in `FuncElaborator._elab_stmt` handles this:

```python
elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
    callee = self._try_eval_const(stmt.value.func)
    if getattr(callee, "_is_sim_output", False):
        pass  # @sim_output call — sim-only side effect, skip in hardware
    else:
        raise NotImplementedError(f"Unsupported statement: {ast.dump(stmt)}")
```

`_try_eval_const` evaluates the callee expression against `{**module_globals, **const_env}`.
If it resolves to a Python callable with `_is_sim_output = True` (the attribute set by the
`@sim_output` decorator), the statement is silently skipped. This lets simulation-only
calls like `capture_pixel(sig, px)` live in `@MAIN` bodies without any conditional guard:

```python
@MAIN
def vga_test_pattern():
    sig = vga_timing()
    px  = test_pattern(sig)
    board_vga.vga_pmod = px
    capture_pixel(sig, px)   # @sim_output — skipped by pipelinec, fires in pypeline_sim.py
```

**Constraints:**
- Only bare function-call expression statements are checked (`ast.Expr` with `ast.Call`).
  Assignment targets (`px = capture_pixel(...)`) are not affected.
- The callee must be resolvable via `_try_eval_const` (i.e. it must be a plain name or
  attribute accessible in `module_globals`). If it cannot be resolved, `_try_eval_const`
  returns `None`, `getattr(None, "_is_sim_output", False)` is `False`, and the
  `NotImplementedError` fires as before.
- The skip is entirely at elaboration time — no hardware node, wire, or submodule instance
  is emitted for the skipped call.

#### Example — Cross-Connected NOT Registers

```python
main_a_in:  Wire[uint1_t]
main_a_out: Wire[uint1_t]
@MAIN
def main_a():
    r: Reg[uint1_t]
    main_a_out = r
    r = ~main_a_in

main_b_in:  Wire[uint1_t]
main_b_out: Wire[uint1_t]
@MAIN
def main_b():
    r: Reg[uint1_t]
    main_b_out = r
    r = ~main_b_in

@MAIN
def a_b_connect():
    main_b_in = main_a_out
    main_a_in = main_b_out
```

Cycle 0 trace (all state 0):
```
queue: [main_a, main_b, a_b_connect]

main_a: main_a_out=0 (r_a=0); new r_a=~0=-1 → buffer
main_b: main_b_out=0 (r_b=0); new r_b=~0=-1 → buffer
a_b_connect: main_b_in=0 (unchanged), main_a_in=0 (unchanged) → no re-queues

Fixed point. Final pass: sim_print fires with r=0 for both MAINs.
Register flush: r_a=-1 (uint1_t=1), r_b=-1 (uint1_t=1).
```

Subsequent cycles toggle both registers between 0 and -1 (uint1_t 0 and 1).

---

### Limitations of the Current Proto-Sim

- **Registers (`Reg[T]`)** — supported; see `Reg[T]` Simulation section above.
  Functions with `Reg[T]` must carry `@hw_func` (or `@MAIN`) for the simulation
  infrastructure to engage.
- **Feedback wires (`Feedback[T]`)** — supported via iterative convergence loop; see
  `Feedback[T]` Simulation section above. Functions with `Feedback[T]` must carry
  `@hw_func` (or `@MAIN`) for the simulation infrastructure to engage.
- **Global wires (`Wire[T]`, `Input[T]`, `Output[T]`)** — supported via
  `pypeline_sim.py`; see `Wire[T]` Global Wire Simulation section above. Multi-file
  designs supported: `_discover_wire_names` recursively scans imported sub-modules;
  cross-module wire writes (`module_alias.wire = expr`) are rewritten at decoration
  time via the Attribute-aware `_GlobalWireRewriter`. Wire sim-keys are bare names
  (no module prefix); unique wire names across sub-modules are assumed.
- **Closures returned by factory functions** (e.g. `vga_timing = make_vga_timing(spec)`)
  — add `@hw_func` to the inner closure definition. `_build_reg_sim_func` now resolves
  `Reg[T]` annotations and body references that use closure-captured variables (via
  `fn.__code__.co_freevars` / `fn.__closure__`). The `@hw_func` wrapper is transparent
  to the elaborator via the `_sim_active` guard (see `@hw_func` section above) and the
  `func_for_source.__globals__` fix in `_elaborate_live_func`.
- **Global variables** — no other form of module-level mutable state is supported.
  Only `Wire[T]`/`Input[T]`/`Output[T]` annotations are valid as shared cross-function
  globals in the hardware elaboration model.
- **Arithmetic type propagation** — intermediate arithmetic results (`+`, `-`, etc.) on
  `SimVal` produce new `SimVal`s without `_ctype`. Type information is re-attached at
  function call boundaries via `@hw_func`. Wire values are stored as-is (`_sim_wire_write`
  preserves struct instances; scalar wires hold `SimVal` or `int`). Type masking for wire
  values occurs at `@hw_func` input/output boundaries. For example, `uint1_t` wires may
  hold `-1` (Python `~0`) rather than `1` as an intermediate value; the final result at
  `@MAIN` boundaries is correctly masked.
- **Annotated casts** — `a_signed: out_t = a` is ignored by Python (annotations are hints).
  For widening/sign-extension this is harmless; truncating casts would require explicit
  `_sim_cast(a, out_t)` if exact bit width matters.
- **Unsigned overflow masking** — arithmetic on `SimVal` is Python arbitrary-precision;
  wrap-on-overflow only occurs when a `@hw_func` boundary re-applies `_sim_cast`. For
  typical hardware-range values this is not observable.
- **`Input[T]` wires** — initialized to zero and not externally driven during sim.
  Setting `Input[T]` values before each cycle is not yet supported by `pypeline_sim.py`.

---

## pypeline.py — Runtime Support

The companion module provides the types and decorators used in design files:

| Name | Purpose |
|---|---|
| `uint1_t` … `uint64_t` | C integer types as real Python classes (`_CTypeMeta` metaclass) |
| `int1_t` … `int64_t` | Signed integer types |
| `float16_t`, `float32_t`, `float64_t` | Float types |
| `make_uint(n)` | Dynamically creates `uintN_t` for arbitrary bit width `n` |
| `make_float_t(E, M)` | Creates an IEEE 754-like struct type with `sign/exp/man` fields; `.as_const(v)` converts a Python float to the field dict at elaboration time |
| `NamedTuple` | Re-export of `typing.NamedTuple` |
| `@struct` | Adds `__class_getitem__` + captures resolved field annotations |
| `@MAIN` | Registers a function as a hardware entry point; implies `@hw_func`; appends to `_main_registry` |
| `@sim_output` | Marks a function as simulation output-only; no-op during convergence passes, executes normally in the final post-convergence pass each cycle |
| `Reg` / `_RegType` | Register descriptor; `Reg[T]` annotation declares a stateful register |
| `Feedback` / `_FeedbackType` | Feedback wire descriptor; `Feedback[T]` annotation declares a combinatorial feedback wire (no flip-flop, no zero-init) |
| `Wire` / `_WireType` | Global wire descriptor; `Wire[T]` annotation at **module level** declares a named combinatorial wire shared across functions (one writer, any number of readers) |
| `Input` / `_InputType` | Top-level design input port; `Input[T]` at module level; any function may read, no function may write |
| `Output` / `_OutputType` | Top-level design output port; `Output[T]` at module level; exactly one function (one instance) may write it |
| `register_operator(op, lhs, rhs, impl, scope=None)` | Binds a binary Python operator on an exact `(lhs, rhs)` type pair; works for any op including `"PLUS"` on struct types |
| `register_left_operator(op, lhs, impl, scope=None)` | Binds a binary Python operator matching only on the left operand type |
| `register_unary_operator(op, operand, impl, scope=None)` | Binds a unary Python operator for a specific operand type; return type may differ from operand |
| `_ctype_str(t)` | Returns the canonical C type name string for a type object (handles both `_CTypeMeta` and `@struct` NamedTuple types) |
| `_push_scoped_registrations(func)` | Merges scoped operator entries for `func` into the global registries; returns a save-list for restoring |
| `_pop_scoped_registrations(saved)` | Restores the global registries to the state before the corresponding push |
| `bit_dup`, `rotl`, `rotr`, `bswap`, `bit_assign` | Bit manipulation primitives (see section above) |
| `array_to_uint_be/le`, `uint_to_array_be/le` | Array ↔ integer packing primitives |
| `concat(*args)` | Bit concatenation — works in both hardware (→ `_elab_tuple_concat`) and simulation (→ `SimVal` with inferred width) |
| `_make_ctype(name)` | Dynamically creates array C types at elaboration time |
| `SimVal` | Thin `int` subclass for simulation: bit-slice `__getitem__`, operator dispatch via registry, ctype-tracked (see Proto-Simulation section) |
| `_sim_cast(val, ctype)` | Cast a Python int/SimVal to a pypeline ctype: mask to bit width, two's-complement signedness |
| `hw_func` | Decorator for inner hardware function definitions; adds sim-mode input/output type casting and register state management; transparent to hardware elaboration via `inspect.unwrap` |
| `sim_call(func, *args)` | Call a pypeline function in simulation mode with scoped operators active |
| `sim_reset()` | Clear all simulated register state (`_sim_reg_state`) and global wire state (`_sim_wire_state`), equivalent to hardware power-on reset |
| `sim_wire_reset()` | Clear only `_sim_wire_state`; leaves register state intact |
| `_sim_inst_stack` | Module-level list tracking the current simulation instance path; each `@hw_func`/`@MAIN` wrapper pushes/pops `(func_qualname, call_loc)` |
| `_sim_reg_state` | Module-level dict `inst_path → {reg_name: value}`; holds persistent register values across `sim_call` invocations |
| `_sim_wire_state` | Module-level dict `wire_name → int`; holds current global wire values; keyed by name only (not instance path) |
| `_sim_wire_readers` | Module-level dict `wire_name → set of MAIN fn`; records which MAINs have read each wire; used by `pypeline_sim.py` convergence queue |
| `_sim_converging` | Module-level bool; `True` during delta-cycle convergence passes; checked by `@sim_output` wrappers |
| `_sim_current_main` | Module-level variable; set to the MAIN function currently executing during convergence; enables `_sim_wire_read` to record reader dependencies |
| `_sim_reg_begin_buffer()` | Switch register writes to buffered mode; used by `pypeline_sim.py` at the start of each clock cycle |
| `_sim_reg_flush_buffer()` | Commit all buffered register writes to `_sim_reg_state` atomically; the simulated clock edge |
| `_main_registry` | Module-level list of all `@MAIN`-decorated (wrapped) functions in decoration order |

All types are declared as proper Python `class` statements with `_CTypeMeta` as metaclass
(not variable assignments), so Pylance/pyright accepts them as valid type expressions.
`__str__` and `__repr__` on the metaclass return the C type name string; `__getitem__`
produces array types (`uint32_t[4]`). Adding `# pyright: reportInvalidTypeForm=none` to
design files suppresses warnings for dynamically-produced types like factory structs.

---

## Predicting C/VHDL Output Names

Every identifier that appears in generated VHDL — struct type names, component entity
names, signal names, port names, submodule instance names — follows deterministic rules
that can be predicted directly from Python source. This section documents those rules.

### Source Location String

Many names embed the source location of the AST node that generated them:

```
<file_base>_l<line>_c<col>[_e<end_col>]
```

`file_base` is the source filename with `.` replaced by `_` (e.g. `pypeline_test_py`).
`line` and `col` are 1-based line and 0-based column numbers. `end_col` is added when
the node carries an `end_col_offset`.

Example: a call at line 42, column 8 in `my_design.py`:
```
my_design_py_l42_c8
```

### Struct Type Names

Every `@struct`-decorated class gets a canonical name stamped at decoration time:

```
<class_name>_<field1>_<type1_mangled>_<field2>_<type2_mangled>_...
```

Array brackets are mangled: `[` → `_`, `]` removed.

```python
@struct
class point_t(NamedTuple):
    x: uint32_t
    y: uint32_t
# C/VHDL type: point_t_x_uint32_t_y_uint32_t

@struct
class buf_t(NamedTuple):
    data: uint8_t[64]
# C/VHDL type: buf_t_data_uint8_t_64
```

This name is independent of what Python variable the factory result is assigned to.
Two factory calls with identical field definitions produce the same canonical name and
share one VHDL type declaration.

Array types of a struct use the canonical name as the base:
```
point_t_x_uint32_t_y_uint32_t[10]   (C type string)
point_t_x_uint32_t_y_uint32_t_10    (when mangled for use inside another name)
```

### Hardware Function Names

Top-level `def` functions in the design file keep their Python name verbatim:
```python
def adder(l: uint32_t, r: uint32_t) -> uint32_t:  ...
# FuncLogicLookupTable key and VHDL entity: "adder"
```

Factory-produced functions (closures) get a **canonical name** derived from the factory
chain and all closure variable values. The Python alias (`concat_3_4`) is never the
VHDL entity name:

```python
concat_3_4 = make_concat(3, 4)
# VHDL entity: "make_concat_HI_SIZE_4_LO_SIZE_3_OUT_SIZE_7"

clz_uint32 = make_clz(uint32_t)
# VHDL entity: "make_clz_OUT_TYPE_uint6_t_VALUE_TYPE_uint32_t_n_bits_32"

negate_uint32 = make_negate(uint32_t, int33_t)
# VHDL entity: "make_negate_OUT_TYPE_int33_t_VALUE_TYPE_uint32_t"
```

The canonical name is independent of which Python variable the result is assigned to.
Two aliases with identical factory + args produce the same canonical name and share a
single VHDL entity. `FuncLogicLookupTable` stores only canonical names for factory
closures; Python aliases are resolved on-demand via `_elaborate_live_func` which returns
the existing Logic() when the canonical name is already present.

### Submodule Instance Names

Every call site in a hardware function body becomes a submodule instance:

```
<func_name>[<loc_str>]
```

Example: calling `adder(a, b)` at `my_design_py_l10_c4`:
```
adder[my_design_py_l10_c4]
```

Inside a for-loop body, iterations are distinguished by `loop_instance_prefix`, which
accumulates the loop variable name and its current value. This prefix is applied to
**both submodule instance names and alias wire names**, ensuring every wire and instance
produced inside an unrolled loop body is unique:

```
FOR_<safe_var>_<val>_<func_name>[<loc_str>]    ← submodule instance
FOR_<safe_var>_<val>_<var_name>_<loc_str>      ← alias wire (_write_ref)
FOR_<safe_var>_<val>_<key>_if_mux_<loc_str>   ← MUX alias wire (_elab_if)
```

`<safe_var>` is the loop variable name after VHDL sanitization (see
[VHDL Identifier Safety](#vhdl-identifier-safety--name-sanitization)). The loop
variable is also stored in `const_env` under its raw Python name so that elaboration-time
`eval()` still resolves it correctly.

`while` loop prefixes use only an integer iteration counter (`WHILE_<n>_`) and are always
VHDL-safe.

Nested loops prefix left-to-right with the outermost loop first:
```python
for i in range(2):
    for j in range(3):
        foo(x)   # → FOR_i_0_FOR_j_0_foo[...], FOR_i_0_FOR_j_1_foo[...], ...
        result = val  # alias → FOR_i_0_FOR_j_0_result_..., FOR_i_0_FOR_j_1_result_..., ...
```

### Port Wire Names

Input and output wires of a submodule instance use the `____` (four underscores) separator:

```
<inst_name>____<port_name>
```

The return value port is always named `return_output`:
```
adder[my_design_py_l10_c4]____return_output
adder[my_design_py_l10_c4]____l
adder[my_design_py_l10_c4]____r
```

### Alias Wire Names

Every assignment to a hardware variable creates an alias wire:

```
<var_name>_<loc_str>
```

Example: `points[1].x = val` at `my_design_py_l20_c4`:
```
points_my_design_py_l20_c4
```

### Built-in Primitive Function Names

These are generated automatically by the elaborator and appear as submodule func_names
in `FuncLogicLookupTable` and as VHDL component entity names:

| Kind | Pattern | Example |
|---|---|---|
| Binary op | `BIN_OP_<op>_<lhs_type>_<rhs_type>` | `BIN_OP_plus_uint32_t_uint32_t` |
| Unary op | `UNARY_OP_<op>_<type>` | `UNARY_OP_not_uint1_t` |
| MUX | `MUX_<type>` | `MUX_uint32_t`, `MUX_point_t_x_uint32_t_y_uint32_t` |
| Const wire | `CONST_<val>_<file>_l<l>_c<c>` | `CONST_1_my_design_py_l5_c12` |
| CONST_REF_RD | `CONST_REF_RD_<out_type>_<base_type>_<path_toks>_<hash>` | |
| VAR_REF_RD | `VAR_REF_RD_<out_type>_<base_type>_<path_toks>_<hash>` | |
| VAR_REF_ASSIGN | `VAR_REF_ASSIGN_<out_type>_<base_type>_<path_toks>_<hash>` | |
| Bit manipulation | `BIT_MANIP_<func>_<types>` | `BIT_MANIP_bit_dup_uint4_t_4` |
| Bit select | `BIT_SELECT_<type>_<pos>` | `BIT_SELECT_uint32_t_15` |
| Bit slice | `BIT_SLICE_<type>_<hi>_<lo>` | `BIT_SLICE_uint32_t_15_0` |
| Bit slice assign | `BIT_SLICE_ASSIGN_<type>_<hi>_<lo>` | |

In `CONST_REF_RD`, `VAR_REF_RD`, and `VAR_REF_ASSIGN` names:
- Array brackets in type strings are replaced with `_`
- Path token integers appear as `_<n>`, variable index positions as `_VAR`
- A short MD5 hash suffix ensures uniqueness across different covering-input sets

### VHDL Identifier Safety — Name Sanitization

VHDL basic identifiers are more restrictive than Python identifiers:

- No leading underscores (`_foo` is illegal)
- No trailing underscores (`foo_` is illegal)
- No consecutive underscores (`foo__bar` is illegal)
- Case-insensitive (`foo` and `FOO` are the same identifier)
- Reserved words cannot be used as identifiers (`signal`, `process`, `begin`, etc.)

`_sanitize_vhdl_name(name)` transforms a Python name into a legal VHDL identifier:

1. Strip leading underscores; prepend `v_` if any were removed (e.g. `_foo` → `v_foo`, `__init__` → `v_init`).
2. Strip trailing underscores (e.g. `foo_` → `foo`, `class_` → `class`).
3. Replace runs of 2+ consecutive underscores with a single `_` (e.g. `foo__bar` → `foo_bar`).
4. If the result is a VHDL-93/2008 reserved word (case-insensitive), append `_v` (e.g. `signal` → `signal_v`).
5. If empty after all stripping (e.g. `_`), return `v`.

**Where sanitization is applied:**

- **Function parameters** (`_setup_inputs`): `arg.arg` is passed through `_hw_name`.
- **Annotated local variables** (`_elab_ann_assign`): `stmt.target.id` is passed through `_hw_name`.
- **Implicit local declarations** (`_elab_assign`): `base_var` from `_parse_ref_toks` is registered via `_hw_name`.
- **All path reads/writes** (`_parse_ref_toks`): the base `ast.Name.id` is passed through `_hw_name`.
- **Bare name reads** (`_elab_name`): sanitized before `env` lookup.
- **Bit-slice reads/assigns** (`_try_elab_bit_slice`, `_try_elab_bit_slice_assign`): base name sanitized before `env` lookup.
- **For-loop prefix** (`_elab_for`): loop variable sanitized for the `loop_instance_prefix` string (but kept raw in `const_env` so elaboration-time `eval()` still resolves it).
- **Global `Wire[T]`** (`_discover_global_wires`): auto-mangled with a stderr warning (internal wires have no constraint-file dependency).
- **Global `Input[T]` / `Output[T]`** (`_discover_global_wires`): **`ElaborationError`** — these names appear in VHDL entity ports that must match XDC/SDC constraint files exactly; silent renaming would break synthesis.

**Case-insensitivity collision detection:**

`FuncElaborator._hw_name` maintains a per-function `_vhdl_names_lower` dict (lowercase safe name → safe name). If two distinct Python names sanitize to identifiers that differ only in case, an `ElaborationError` is raised.

**`const_env` is exempt:**

Loop counters and elaboration-time constants stored in `const_env` use raw Python names. They feed `_try_eval_const`'s `eval()` namespace, where the Python source spelling must match. These names never become VHDL signals.

---

### Summary Table

| Artifact | Rule |
|---|---|
| Struct C type | `<class_name>_<f1>_<t1_mangled>_...` (canonical, set by `@struct`) |
| Array of struct | `<struct_canonical>[N]` in C type strings |
| Top-level function | Python `def` name verbatim |
| Imported sub-file function | `<actual_module_name>_<func_name>` (e.g. `file_a_main`) |
| Factory function (params in closure) | `<factory_prefix>_<param>_<val>_...` (canonical, from qualname + closure vars) |
| Factory function (params NOT in closure) | `<factory_prefix>_<param_names>_<hash8>` (closure vars hashed; e.g. `make_vga_timing_spec_a1b2c3d4`) |
| Top-file global Wire | sanitized Python name (auto-mangled if illegal; see VHDL Identifier Safety) |
| Imported sub-file Wire | `<actual_module_name>_<safe_bare_name>` |
| Input[T] / Output[T] (any file) | **bare Python name** — no module prefix; must be a legal VHDL identifier (error if not) |
| Local variable / function parameter | sanitized Python name (`_hw_name`) |
| Submodule instance | `<func_name>[<loc_str>]` (+ `FOR_<safe_v>_<n>_` prefix per loop level) |
| Port wire | `<inst>____<port>` (four underscores) |
| Return port | `<inst>____return_output` |
| Alias wire | `<safe_var_name>_<loc_str>` |
| Location string | `<file_base>_l<line>_c<col>[_e<end_col>]` |

---

## End-to-End Flow Summary

```
top.py  (single-file or multi-file entry point)
  │
  ├─ sys.path.insert(design_dir)        Allow 'import file_a' to resolve relative to top.py
  │
  ├─ exec_module()                      Python runtime: 'import file_a' executes sub-files,
  │                                     registers all @MAIN (top + sub-files), runs factories,
  │                                     records PART(...) → _part_registry,
  │                                     records @MAIN(mhz) → _main_mhz_registry
  │
  ├─ _discover_structs_from_module()    Register struct field types from top file namespace
  │
  ├─ ast.parse(top.py)
  │
  ├─ _discover_global_wires(top.py)     Bare names — no prefix
  │
  ├─ _process_imports(top_file=top.py)  For each 'import file_a' / 'import file_a as fa':
  │   ├─ record 'fa' → 'file_a' in parser_state.module_alias_to_actual
  │   ├─ _discover_structs_from_module(file_a)
  │   ├─ _discover_global_wires(file_a.py, name_prefix='file_a')
  │   │     → registers 'file_a_i', 'file_a_o', … in parser_state.global_vars
  │   └─ queue (file_a.py, sub_tree, vars(file_a), 'file_a') for elaboration
  ├─ files_to_elaborate.append(top.py)  ← top file queued LAST
  │
  ├─ Collect all_func_defs from every queued file (sub-files first, top file last)
  │
  ├─ Register stubs: FuncLogicLookupTable[hw_name] = stub
  │   (hw_name = 'file_a_main' for sub-file, bare name for top-file)
  │
  ├─ FuncElaborator ×N  (all files; sub-file elaborators carry module_prefix='file_a')
  │   ├─ _setup_inputs()
  │   ├─ _setup_outputs()
  │   └─ _elab_stmt() recursive:
  │       ├─ _elab_assign               const_env or hardware wire routing; BIT_SLICE_ASSIGN for x[hi:lo]=y
  │       │   ├─ IfExp RHS              x = body if test else orelse  →  synthetic ast.If  →  _elab_if MUX
  │       │   ├─ struct constructor RHS x = MyStruct(...)  →  _elab_compound_init (no annotation needed)
  │       │   ├─ module-attr LHS        file_a.i = expr  →  _resolve_module_wire_name → 'file_a_i' (or bare name for I/O)
  │       │   └─ bare-name LHS (sub)    i = expr  →  _resolve_global_wire('i') → 'file_a_i'
  │       ├─ _elab_ann_assign           declare local variable wire; Reg[T] → register input/output; dict/list RHS → _elab_compound_init
  │       ├─ _elab_aug_assign           const_env update or hardware BinOp
  │       ├─ _elab_for                  unroll over constant iterable
  │       ├─ _elab_while                unroll while _try_eval_const(condition)
  │       ├─ _elab_if                   eliminate (const) or snapshot+MUX (hardware)
  │       └─ _elab_return               error if void; error if bare return in non-void; error if already driven; connect result wire
  │           ├─ compound form          _elab_compound_init writes sub-field aliases; _connect_compound_return assembles via CONST_REF_RD → drives return_output
  │           └─ _elab_expr:
  │               ├─ _elab_constant     _infer_const_ctype → CONST wire
  │               ├─ _elab_binop        BIN_OP built-in or registered binary operator submodule
  │               ├─ _elab_unary        registered unary overload (ret type from func) or UNARY_OP built-in
  │               ├─ module-attr RHS    file_a.o  →  _resolve_module_wire_name → 'file_a_o'
  │               ├─ _elab_ref_read     CONST_REF_RD or VAR_REF_RD
  │               │   └─ bare-name (sub)  _resolve_global_wire → prefixed name
  │               ├─ _elab_name (step 4) _resolve_global_wire → direct or prefixed global wire
  │               ├─ _elab_bit_select   BIT_SELECT submodule (scalar x[N])
  │               ├─ _elab_bit_slice    BIT_SLICE submodule (scalar x[hi:lo] or s.field[hi:lo])
  │               ├─ _elab_tuple_concat TUPLE_CONCAT submodule ((a, b, c))
  │               └─ _elab_call         ast.Name: try prefixed name (sub-file), FuncLogicLookupTable, _elaborate_live_func
  │                                   ast.Attribute: module-qualified call (mod.func(args)) →
  │                                     getattr lookup + FuncLogicLookupTable (sub-files pre-elaborated)
  │                   └─ bit_dup/rotl/rotr/bswap/bit_assign/array_uint/concat → BIT_MANIP submodules
  │
  ├─ _build_inst_lookup()               Recursively populate LogicInstLookupTable
  │
  ├─ Apply pypeline pragmas:
  │   ├─ parser_state.part ← pypeline._part_registry   (from PART(...))
  │   └─ parser_state.main_mhz[hw_name] ← _main_mhz_registry.get(func_name)  (from @MAIN(mhz))
  │
  ├─ INFER_CLOCK_DOMAINS({}, {}, {}, parser_state)
  │   Propagates known MHz to board-support MAINs sharing global wires (fixed-point loop)
  │
  └─ ParserState → VHDL backend
```