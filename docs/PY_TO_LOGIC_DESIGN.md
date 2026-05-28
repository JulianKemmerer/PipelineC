# PY_TO_LOGIC — Design Document

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
parser_state.main_mhz                   # main_name -> clock MHz (None until synthesis)
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

### Annotation Evaluation

Function signature annotations are evaluated against `{**module_globals, **const_env}`:

```python
def concat(bits_lo: uint1_t[LO_SIZE], bits_hi: uint1_t[HI_SIZE]) -> uint1_t[OUT_SIZE]:
```

`LO_SIZE`, `HI_SIZE`, `OUT_SIZE` are resolved from `module_globals` or closure variables
at elaboration time, producing concrete C type strings like `"uint1_t[3]"`.

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

`_find_covering_wire(leaf_ref_toks)` returns the most specific wire that covers a concrete
leaf path. It checks two sources, preferring the **longest (most specific) prefix match**:

1. **Concrete env** — walks from full path down to base name, first hit wins
2. **Variable aliases** — walks `wire_aliases_over_time` in reverse (most recent first),
   using `_var_ref_toks_covers` for wildcard matching (AST node positions match any concrete value)

```python
def _var_ref_toks_covers(var_ref_toks, concrete_ref_toks):
    # ("points", i_ast, "dim", 1) covers ("points", 0, "dim", 1) ✓
    # ("points", i_ast, "dim", 1) covers ("points", 0, "dim", 0) ✗  (1 ≠ 0 at pos 3)
    # ("points",) covers any leaf under points                    ✓
```

Concrete wins on equal-length ties.

### Temporal Sort of Covering Wires

When a CONST_REF_RD needs multiple covering wires, they must be presented to the VHDL
backend in **oldest-first** order so that base assignments appear before partial overrides.
The algorithm (`_temporal_sort_covering_wires`) achieves this in three steps:

```
1. Walk wire_aliases_over_time[base_var] BACKWARDS (newest alias first)
2. For each alias whose ref_toks appears as a covering-wires key, collect it
   (both identity check `is` and equality check `==` are tried, since
    env-prefix tuples are new objects but variable-alias ref_toks are the
    same Python object stored in alias_to_driven_ref_toks)
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
5. Otherwise emit a `CONST_REF_RD_<output_type>_<base_type>_<path>_<hash>` submodule

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
2. Snapshot env and wire_aliases_over_time → env_snap, aliases_snap
3. Elaborate true branch  → capture env_true, aliases_true
4. Restore snapshot
5. Elaborate false branch → capture env_false, aliases_false  (empty if no else)
6. Restore snapshot
7. Collect driven ref_toks from new aliases in both branches
8. Reduce:  _reduce_driven_ref_toks(driven, env_snap, parser_state)
9. For each reduced (ref_toks, mux_type):
     true_wire  = _read_branch_coverage(env_true,  aliases_true,  ...)
     false_wire = _read_branch_coverage(env_false, aliases_false, ...)
     MUX(cond, true_wire, false_wire) → mux_alias
```

Both branches elaborate **into the same `logic` object** — wires and submodule instances
accumulate permanently. Only `env` and `wire_aliases_over_time` are snapshot/restored, so
the hardware graph is additive across both branches while the alias view remains consistent.

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

### Reading Branch Wires for Variable Ref_Toks

When a driven ref_toks contains variable indices (AST nodes), `_read_branch_coverage` calls
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
colliding wire/instance names. They don't, because:

- **Concrete-index writes:** `bits[b] = bits_lo[i]` — the alias prefix includes `b`'s
  resolved value (`"bits_0_..."`, `"bits_1_..."`), producing different alias names
- **VAR_REF_ASSIGN:** the func_name hash includes the covering_ref_toks, which differ
  across iterations as each iteration's output alias becomes the next iteration's covering
  input — a chain of distinct hashes
- **CONST_REF_RD reads:** the func_name includes the concrete access path (e.g. index 0 vs
  index 1), giving different func_names → different inst_names

All three cases produce unique identifiers automatically from the elaboration state, with no
iteration counter needed.

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
3. These are merged into `module_globals` → annotations like `uint1_t[LO_SIZE]` now resolve
4. A fresh `FuncElaborator` elaborates the function and stores the result under the
   module-level alias name (`"concat_3_4"`) in `FuncLogicLookupTable`

Only top-level `def` statements are scanned by `ast.walk` on `tree.body`. Nested functions
inside factory closures (like `def concat` inside `make_concat`) are deliberately excluded
— they are elaborated on-demand through `_elaborate_live_func` when first called.

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
registers all `NamedTuple` subclasses in `struct_to_field_type_dict`. The `@struct`
decorator:

1. Adds `__class_getitem__` so `point_t[10]` produces `_make_ctype("point_t[10]")` — a
   valid array C type object usable in further annotations
2. Captures resolved C type strings via `sys._getframe(1)` while factory locals are still
   in scope, handling `ForwardRef` strings that `from __future__ import annotations` creates.
   These are stored in `cls._pypeline_annotations` and preferred by `_discover_structs_from_module`

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
lo_half: uint16_t = x[15:0]   # extract bits [15:0] → uint16_t
```

The slice bounds are evaluated via `_try_eval_const` (must be constants at elaboration time).
Elaborated as a `BIT_SLICE_<type>_<hi>_<lo>` submodule.

### Bit-Slice Assignment

```python
x[15:0] = y   # write bits [15:0] of x with value y, leaving other bits unchanged
```

Creates a new alias wire for `x` via a `BIT_SLICE_ASSIGN_<type>_<hi>_<lo>` submodule that
takes the old `x` wire and `y` and produces an updated value.

### Tuple Concatenation

A tuple literal whose elements are all hardware-typed values is treated as bit
concatenation, **first element in the most-significant position**:

```python
out: uint64_t = (a, b)          # a:uint32_t ++ b:uint32_t → uint64_t
out: uint64_t = (a, b, c)       # a:uint16_t ++ b:uint16_t ++ c:uint32_t → uint64_t
```

Elaborated as a chain of `TUPLE_CONCAT_<types>` submodule instances. The output width is
the sum of all element widths; the return type must match exactly.

---

## Custom Operator Registration (`register_operator`)

Hardware operators that are not built-in binops (e.g. shift, multiply with non-standard
output width) are registered explicitly:

```python
def make_shifter_SL(VALUE_TYPE, AMOUNT_TYPE):
    def shifter_SL(v: VALUE_TYPE, amount: AMOUNT_TYPE) -> VALUE_TYPE:
        return v + amount  # placeholder body; real impl is a PipelineC primitive
    return shifter_SL

shl_uint32_uint6 = make_shifter_SL(uint32_t, uint6_t)
register_operator("SL", uint32_t, uint6_t, "shl_uint32_uint6")
```

`register_operator(op_str, lhs_type, rhs_type, func_name)` binds the Python operator
`<<` (mapped from `"SL"`) on `(uint32_t, uint6_t)` operands to the named function.  When
`_elab_binop` encounters `v << amount` with those types it looks up the registered function
name and elaborates the call as if `shl_uint32_uint6(v, amount)` had been written — a
regular submodule instance in the Logic() graph.

The `op_str` → Python operator mapping:

| `op_str` | Python operator |
|---|---|
| `"SL"` | `<<` (shift left) |
| `"SR"` | `>>` (shift right) |

Operators not in the registry fall through to the standard `BIN_OP_LOGIC_NAME_PREFIX_<op>_<type>`
submodule naming.

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

## pypeline.py — Runtime Support

The companion module provides the types and decorators used in design files:

| Name | Purpose |
|---|---|
| `uint1_t` … `uint64_t` | C integer types as real Python classes (`_CTypeMeta` metaclass) |
| `int1_t` … `int64_t` | Signed integer types |
| `float16_t`, `float32_t`, `float64_t` | Float types |
| `make_uint(n)` | Dynamically creates `uintN_t` for arbitrary bit width `n` |
| `NamedTuple` | Re-export of `typing.NamedTuple` |
| `@struct` | Adds `__class_getitem__` + captures resolved field annotations |
| `@MAIN` | Registers a function as a hardware entry point |
| `Reg` / `_RegType` | Register descriptor; `Reg[T]` annotation declares a stateful register |
| `register_operator` | Binds a Python operator (`<<`, `>>`, …) for a specific type pair to a named function |
| `bit_dup`, `rotl`, `rotr`, `bswap`, `bit_assign` | Bit manipulation primitives (see section above) |
| `array_to_uint_be/le`, `uint_to_array_be/le` | Array ↔ integer packing primitives |
| `_make_ctype(name)` | Dynamically creates array C types at elaboration time |

All types are declared as proper Python `class` statements with `_CTypeMeta` as metaclass
(not variable assignments), so Pylance/pyright accepts them as valid type expressions.
`__str__` and `__repr__` on the metaclass return the C type name string; `__getitem__`
produces array types (`uint32_t[4]`). Adding `# pyright: reportInvalidTypeForm=none` to
design files suppresses warnings for dynamically-produced types like factory structs.

---

## End-to-End Flow Summary

```
design.py
  │
  ├─ exec_module()                      Python runtime: factories, @MAIN, @struct, constants
  │
  ├─ _discover_structs_from_module()    Register struct field types from live namespace
  │
  ├─ ast.parse() on tree.body only      Top-level hardware functions, skip nested defs
  │
  ├─ FuncElaborator ×N                  One per top-level hardware function
  │   ├─ _setup_inputs()                Add input wires → env
  │   ├─ _setup_outputs()               Add return wire
  │   └─ _elab_stmt() recursive:
  │       ├─ _elab_assign               const_env or hardware wire routing; BIT_SLICE_ASSIGN for x[hi:lo]=y
  │       ├─ _elab_ann_assign           declare local variable wire; Reg[T] → register input/output
  │       ├─ _elab_aug_assign           const_env update or hardware BinOp
  │       ├─ _elab_for                  unroll over constant iterable
  │       ├─ _elab_while                unroll while _try_eval_const(condition)
  │       ├─ _elab_if                   eliminate (const) or snapshot+MUX (hardware)
  │       └─ _elab_return               connect result wire
  │           └─ _elab_expr:
  │               ├─ _elab_constant     _infer_const_ctype → CONST wire
  │               ├─ _elab_binop/unary  BIN_OP / UNARY_OP or registered operator submodule
  │               ├─ _elab_ref_read     CONST_REF_RD or VAR_REF_RD
  │               ├─ _elab_bit_select   BIT_SELECT submodule (scalar x[N])
  │               ├─ _elab_bit_slice    BIT_SLICE submodule (scalar x[hi:lo])
  │               ├─ _elab_tuple_concat TUPLE_CONCAT submodule ((a, b, c))
  │               └─ _elab_call         lookup FuncLogicLookupTable or _elaborate_live_func
  │                   └─ bit_dup/rotl/rotr/bswap/bit_assign/array_uint helpers → BIT_MANIP submodules
  │
  ├─ _build_inst_lookup()               Recursively populate LogicInstLookupTable
  │
  └─ ParserState → VHDL backend
```