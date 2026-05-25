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
parser_state.FuncLogicLookupTable   # func_name -> Logic()  (function definitions)
parser_state.LogicInstLookupTable   # inst_key  -> Logic()  (instantiated call sites)
parser_state.FuncToInstances        # func_name -> {inst_keys}
parser_state.struct_to_field_type_dict  # struct_name -> {field: c_type_str}
parser_state.main_mhz               # main_name -> clock MHz (None until synthesis)
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
logic.wires                          # set of all wire names
logic.wire_to_c_type                 # wire_name -> C type string ("uint32_t", "point_t[3]", …)
logic.wire_driven_by                 # wire_name -> driver_wire_name
logic.wire_drives                    # driver_wire_name -> {wire_name, …}
logic.submodule_instances            # inst_name -> func_name
logic.submodule_instance_to_input_port_names  # inst_name -> [port_name, …]
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
_array_elem_type("uint32_t[4]")  # "uint32_t"
_array_first_dim("uint32_t[4]")  # 4
_is_struct("point_t", ps)        # True if point_t in struct_to_field_type_dict
_is_scalar("uint32_t", ps)       # True (not array, not struct)
```

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
inst_name = "foo[src_file_l10_c4]"    ← unique per call site (file + line + col)
output_wire = inst_name + "____return_output"
input_port_wire = inst_name + "____a"
```

All instance wires are recorded in `logic.wire_to_c_type` and connected via
`logic.wire_driven_by`. The callee's `Logic()` is looked up in `FuncLogicLookupTable`
to determine port names and the return type.

**Binary ops, unary ops, MUX** are all represented as submodule instances with
auto-generated built-in function names (`BIN_OP_LOGIC_NAME_PREFIX_plus_uint32_t`,
`MUX_uint32_t`, etc.).

---

## Reference Tokens — the Core Addressing System

A *reference token tuple* (ref_toks) is the canonical way to describe a path into a
compound variable:

```python
("points", 0, "dim", 1)   # points[0].dim[1]  — all concrete
("points", i_ast, "dim")  # points[i].dim      — i is an ast.AST node (variable index)
```

Tokens are either:
- `int` — concrete array index
- `str` — struct field name
- `ast.AST` node — variable (hardware) index, acts as a wildcard in matching

```python
_is_var_tok(tok)          # True for ast.AST nodes
_has_variable_index(ref_toks)  # True if any token is an ast.AST
_ref_toks_to_env_key(ref_toks)  # ("points",0,"dim",1) -> "points[0].dim[1]"
_ref_toks_to_ctype(ref_toks, base_type, ps)  # type at the path end
```

---

## Alias Tracking — Assignments Over Time

Every write to a variable creates a new **alias wire** rather than mutating the existing
wire. This models the sequential nature of assignments within combinational hardware:

```python
# points[0].dim[1] = test_u32
alias = "points_0_dim_1_myfile_py_l15_c4"
logic.wire_aliases_over_time["points"].append(alias)
logic.alias_to_driven_ref_toks[alias] = ("points", 0, "dim", 1)
logic.alias_to_orig_var_name[alias]   = "points"
self.env["points[0].dim[1]"]          = (alias, "uint32_t")
```

`wire_aliases_over_time[base_var]` is an **ordered list** — oldest alias first, newest
last — representing the variable's assignment history within the function.

---

## Finding the Covering Wire

`_find_covering_wire(leaf_ref_toks)` returns the most specific wire that covers a
concrete leaf path. It checks two sources, preferring the **longest (most specific)
prefix match**:

1. **Concrete env** — string-keyed, longest prefix first
2. **Variable aliases** — walks `wire_aliases_over_time` in reverse (most recent first),
   using `_var_ref_toks_covers` for wildcard matching

```python
def _var_ref_toks_covers(var_ref_toks, concrete_ref_toks):
    # AST node positions in var_ref_toks act as wildcards
    # ("points", i_ast, "dim", 1) covers ("points", 0, "dim", 1) ✓
    # ("points", i_ast, "dim", 1) covers ("points", 0, "dim", 0) ✗
```

Concrete wins on equal-length ties.

**Temporal sort**: covering wires for a CONST_REF_RD are ordered **oldest first** by
walking `wire_aliases_over_time` backwards and reversing — this matches the VHDL backend's
expectation that base assignments precede overrides.

---

## CONST_REF_RD — Reading Compound Types

Reading a compound value (struct, array) when it may have been partially written requires
a `CONST_REF_RD` submodule:

```python
# return points  — after my_points[1].x = 1, my_points[2] = p0, …
CONST_REF_RD(
    ref_toks_0=my_points,    # covers [0],[5..9] — original input, oldest
    ref_toks_1=alias_1x,     # covers [1].x
    ref_toks_2=alias_1y,     # covers [1].y
    ref_toks_2=alias_2,      # covers [2]
) -> point_xy_t[10]
```

The process:
1. Enumerate all scalar leaf ref_toks of the target type
2. For each leaf, call `_find_covering_wire` → get `(wire, covering_ref_toks, type)`
3. Collect unique covering wires, sorted temporally (oldest first)
4. If a single wire already covers everything and matches the target ref_toks exactly:
   return it directly (no CONST_REF_RD needed)
5. Otherwise emit a `CONST_REF_RD` submodule instance

The backend recognises the `CONST_REF_RD_` prefix and generates the appropriate VHDL
assignment sequence (base first, then overrides).

---

## VAR_REF_RD — Variable-Index Reads

Reading with a variable index (`points[i]`, `points[i].dim[j]`) requires a `VAR_REF_RD`
submodule that implements a **binary mux tree**:

```python
# return points[i]  where i is a hardware wire
VAR_REF_RD(
    ref_toks_0=points,     # covering input (entire array)
    var_dim_0=i_wire,      # select wire (uint2_t for 3 elements)
) -> point2d_t
```

**Internal Logic() structure:**

1. **Step 1** — CONST_REF_RD extracts every concrete scalar leaf from the covering inputs:
   `points[0].dim[0]`, `points[0].dim[1]`, `points[1].dim[0]`, …
2. **Step 2** — Binary mux tree per variable dimension. A trimmed binary tree (split at
   largest power-of-two ≤ N) reduces `dim_size` leaves to 1, using bit extractions of
   `var_dim_i` as the select signals.
3. **Step 3** — If the output type is compound, assemble the scalar mux outputs back into
   the output type via a CONST_REF_RD assembly.

The covering inputs may include **variable alias wires** (from prior VAR_REF_ASSIGNs).
`_var_alias_internal_path` computes the correct CONST_REF_RD index path into an alias wire.

---

## VAR_REF_ASSIGN — Variable-Index Writes

Writing with a variable index (`points[i].dim[1] = val`) creates a `VAR_REF_ASSIGN`
submodule and a **variable alias**:

```python
# points[i].dim[1] = test_u32
VAR_REF_ASSIGN(
    elem_val=test_u32,     # value to write
    ref_toks_0=points,     # covering input (oldest covering wire)
    var_dim_0=i_wire,      # variable index (uint2_t for 3 elements)
) -> uint32_t[3]           # output type: scalar_type[var_dim_0][var_dim_1]...
```

**Output type formula:** `elem_c_type[var_dim_0][var_dim_1]...`
where `elem_c_type` is the type at the end of the ref_toks path (may be compound).

**Internal Logic() structure (operates at elem level, not scalar):**

1. **Step 1** — CONST_REF_RD extracts the old elem-typed value for each concrete position
   (`points[0].dim[1]`, `points[1].dim[1]`, `points[2].dim[1]` → 3 × `uint32_t`)
2. **Step 2** — For each concrete position `k`: emit `EQ(var_dim_0, k)` comparator(s),
   AND them together for multi-dimensional cases, then `MUX(cond, elem_val, old_elem_k)`.
   MUXes operate at elem_c_type level — compound types (structs, arrays) are valid.
3. **Step 3** — Assemble updated elems into output_type via CONST_REF_RD assembly.

**The alias** records variable ref_toks (AST nodes intact) so that subsequent
`_find_covering_wire` calls can wildcard-match it:

```python
logic.wire_aliases_over_time["points"].append(alias)
logic.alias_to_driven_ref_toks[alias] = ("points", i_ast, "dim", 1)  # AST node preserved
logic.wire_to_c_type[alias] = "uint32_t[3]"
```

Later reads (e.g. `return points`) discover this alias via `_var_ref_toks_covers` and
use `_var_alias_internal_path` to compute the correct CONST_REF_RD index into it.

---

## `if` Statements — Hardware MUX Generation

Compile-time constant conditions → branch elimination (no hardware emitted).

Runtime hardware conditions → snapshot/restore + MUX per driven variable:

```
1. Evaluate condition wire: cond_wire, _ = _elab_expr(stmt.test)
2. Snapshot: env_snap, aliases_snap = copy of env and wire_aliases_over_time
3. Elaborate true branch  → capture env_true, aliases_true
4. Restore snapshot
5. Elaborate false branch → capture env_false, aliases_false
6. Restore snapshot
7. Collect driven ref_toks from new aliases in both branches
8. Reduce: _reduce_driven_ref_toks(driven, env_snap, parser_state)
9. For each reduced (ref_toks, mux_type):
     true_wire  = _read_branch_coverage(ref_toks, mux_type, env_true,  aliases_true, ...)
     false_wire = _read_branch_coverage(ref_toks, mux_type, env_false, aliases_false, ...)
     emit MUX(cond, true_wire, false_wire) → mux_alias
```

Both branches elaborate **into the same `logic` object** — wires and submodule instances
accumulate from both sides. Only `env` and `wire_aliases_over_time` are snapshot/restored,
keeping the hardware graph additive.

**Reduction** (`_reduce_driven_ref_toks`) eliminates redundant ref_toks patterns:

- *Completeness*: if all children of a concrete parent are driven
  (`("points",0)`, `("points",1)`, `("points",2)` for a size-3 array) → replace with
  parent `("points",)`, emit one compound MUX of type `point2d_t[3]`
- *Prefix coverage*: if ref_toks B is a more general prefix of ref_toks A (including
  wildcard positions) → remove A, keep B

**Reading branch wires** for variable ref_toks uses `_assemble_var_ref_coverage`: enumerate
concrete elem positions, read each from the branch env/aliases, assemble into `mux_type`
via CONST_REF_RD. The MUX output alias inherits the driven ref_toks (AST nodes intact)
so subsequent reads continue to work correctly.

---

## For and While Loop Unrolling

Both loop constructs are **fully unrolled at elaboration time**. The loop condition or
iterable must be evaluable as a plain Python value via `_try_eval_const`.

### For Loops

```python
for i in range(LO_SIZE):
    bits[b] = bits_lo[i]
    b = b + 1
```

`_try_eval_const(stmt.iter)` evaluates `range(LO_SIZE)` against `module_globals` +
`const_env`. The loop variable `i` is stored in `const_env` at each iteration value.
Body statements are elaborated once per iteration.

Supported iterables: `range(...)`, `tuple`, `list`. String field iteration
(`for f in point_t._fields:`) also works — `f` becomes a string in `const_env`, and
`rv[f]` resolves to a struct field access via `_parse_ref_toks`.

### While Loops

```python
i = 0
while i < LO_SIZE:
    bits[b] = bits_lo[i]
    b = b + 1
    i = i + 1
```

Each iteration: evaluate condition with `_try_eval_const`, elaborate body if true, repeat.
Loop counter updates (`i = i + 1`) go through `_elab_assign` → the name is not in `env`
(hardware), `_try_eval_const` succeeds → `const_env["i"]` is updated. A safety limit of
65 536 iterations prevents non-terminating loops from hanging the compiler.

**Why naming stays unique across iterations:** concrete-index writes include the resolved
index value in the alias name (`"bits_0_..."`, `"bits_1_..."`). VAR_REF_ASSIGN func_names
hash the covering_ref_toks, which change each iteration as previous-iteration aliases become
covering inputs. CONST_REF_RD func_names include the concrete access path.

---

## Closure Factory Pattern

The closure factory pattern lets Python generate specialised hardware functions and types
at elaboration time, with all sizing and structure resolved to concrete values.

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

concat_3_4 = make_concat(3, 4)   # ← module-level, discovered by elaborator
```

When a call to `concat_3_4` is first encountered, `_elab_call` checks `module_globals`,
finds a callable, and invokes `_elaborate_live_func`:

1. `inspect.getsource` + `textwrap.dedent` to recover the inner function's source
2. Extract closure variables from `func.__code__.co_freevars` / `func.__closure__`
   (`LO_SIZE=3`, `HI_SIZE=4`, `OUT_SIZE=7`)
3. Merge closure vars into `module_globals` → annotations like `uint1_t[LO_SIZE]` resolve
4. Elaborate with a fresh `FuncElaborator`, store under the module-level alias name

### Specialised Types

```python
def make_point_t(dim_type, dim_size):
    @struct
    class point_t(NamedTuple):
        dim: dim_type[dim_size]
    return point_t

point_t = make_point_t(uint32_t, 2)
```

`_discover_structs_from_module` walks the live module namespace after `exec_module` and
registers all `NamedTuple` subclasses in `struct_to_field_type_dict`. The `@struct`
decorator:

1. Adds `__class_getitem__` so `point_t[10]` produces a `_CTypeMeta` array type
2. Captures resolved C type strings for each field via `sys._getframe(1)`, stored in
   `cls._pypeline_annotations` — this handles `from __future__ import annotations` and
   factory closures where field annotations would otherwise be `ForwardRef` strings

### Conditional Type-Driven Code

Because closure variables are real Python objects at elaboration time, hardware functions
can branch on type properties:

```python
def types_test_foo(point: point_t) -> point_t:
    rv: point_t
    if point_t.style == "array":        # evaluates at elaboration time → branch elimination
        for i in range(point_t.dim_size):
            rv.dim[i] = point.dim[i]
    else:
        for f in point_t._fields:
            rv[f] = point[f]
    return rv
```

`point_t.style` resolves via `_try_eval_const` → constant branch elimination → only the
matching branch's hardware is emitted.

---

## pypeline.py — Runtime Support

The companion module provides the types and decorators used in design files:

| Name | Purpose |
|---|---|
| `uint1_t` … `uint64_t` | C integer types as real Python classes (`_CTypeMeta` metaclass) |
| `int1_t` … `int64_t` | Signed integer types |
| `float16_t`, `float32_t`, `float64_t` | Float types |
| `NamedTuple` | Re-export of `typing.NamedTuple` |
| `@struct` | Adds `__class_getitem__` + captures resolved field annotations |
| `@MAIN` | Registers a function as a hardware entry point |
| `_make_ctype(name)` | Dynamically creates array C types at elaboration time |

All types are declared as proper Python `class` statements (not variable assignments) so
Pylance/pyright accepts them as valid type annotations. Adding `# pyright: reportInvalidTypeForm=none`
to design files suppresses warnings for dynamically-produced types like factory structs.

---

## End-to-End Flow Summary

```
design.py
  │
  ├─ exec_module()          Python runtime: factories, @MAIN, @struct, constants
  │
  ├─ _discover_structs_from_module()   Register struct field types
  │
  ├─ ast.parse()            AST for hardware function bodies
  │
  ├─ FuncElaborator ×N      One per top-level hardware function
  │   ├─ _setup_inputs()    Add input wires to Logic() + env
  │   ├─ _setup_outputs()   Add output wire to Logic()
  │   └─ _elab_stmt() ×M   Recursively elaborate each statement:
  │       ├─ _elab_assign / _elab_ann_assign
  │       ├─ _elab_aug_assign
  │       ├─ _elab_for / _elab_while   (unroll at elaboration time)
  │       ├─ _elab_if                  (eliminate or emit MUX)
  │       └─ _elab_return
  │
  ├─ _build_inst_lookup()   Recursively populate LogicInstLookupTable
  │
  └─ ParserState → backend (VHDL generation)
```
