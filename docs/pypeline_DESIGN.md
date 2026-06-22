# pypeline.py — Design Document

This document covers `pypeline.py` — the shared runtime foundations used by both the
hardware elaborator (`PY_TO_LOGIC.py`) and the simulation layer. For elaboration-specific
internals (Logic() graph, FuncElaborator, CONST_REF_RD, etc.) see
[`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md). For simulation-specific internals
(`@hw_func`, `_build_reg_sim_func`, multi-MAIN runner, performance tuning) see
[`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md).

## Table of Contents

- [Overview](#overview)
- [C Type System](#c-type-system)
- [Type Utilities](#type-utilities)
- [Struct Support](#struct-support)
- [Annotation Types](#annotation-types)
- [`PART()` and `@MAIN` Pragmas](#part-and-main-pragmas)
- [Operator Registry](#operator-registry)
- [`SimVal` — Typed Simulation Integer](#simval--typed-simulation-integer)
- [`concat(*args)` — Bit Concatenation](#concatargs--bit-concatenation)
- [`vhdl(text)` — Raw VHDL Passthrough](#vhdltext--raw-vhdl-passthrough)
- [Reference: `pypeline.py` Public API](#reference-pypelinepy-public-api)

---

## Overview

`pypeline.py` is the shared runtime support module for the Pypeline hardware design system.
It provides three categories of functionality:

1. **Type foundations** — C-style integer types, the `@struct` decorator, annotation
   descriptors (`Reg[T]`, `Wire[T]`, etc.), and arithmetic promotion rules used identically
   by the elaborator and simulator.

2. **Pragma and registry infrastructure** — `PART()`, `@MAIN`, and the operator registry
   that both the hardware elaborator and the simulation layer consult.

3. **Simulation primitives** — `SimVal` (typed simulation integer), `concat()` dual-mode
   bit concatenation, and the `_sim_cast` / `_sim_val_make` helpers.

`PY_TO_LOGIC.py` imports the type utilities and operator registries directly:

```python
from pypeline import (
    _RegType, _FeedbackType, _WireType, _InputType, _OutputType,
    BIT_MANIP_FUNC_NAMES, _INT_CTYPE_RE, _ctype_is_int, _ctype_info,
    _int_ctype, _arith_promote, _arith_output_ctype,
)
```

Hardware design files import user-facing names (`uint32_t`, `Reg`, `@struct`, etc.).
The simulation layer uses `SimVal`, `_sim_cast`, and the operator registries at runtime.

---

## C Type System

### `_CTypeMeta` Metaclass

All Pypeline C types are real Python classes with `_CTypeMeta` as their metaclass.
This makes them acceptable as `NamedTuple` field annotations (Pylance/pyright sees a class)
while still encoding the type name as a string.

Key dunder methods on `_CTypeMeta`:

```python
str(uint32_t)          # → "uint32_t"   (via __str__ / __repr__)
uint32_t[4]            # → _make_ctype("uint32_t[4]")   (via __getitem__)
len(uint32_t)          # → 32   (bit width via __len__, or the array dimension)
uint32_t.width         # → 32   (property, raises for array types)
```

`__getitem__` calls `_make_ctype(f"{cls._ctype_name}[{dim}]")`, so `point_t[10]`
returns a proper class object with `_ctype_name = "point_t[10]"`. This is why
`uint32_t[4]` works as a type annotation in `NamedTuple` fields.

The returned array class also gets `arr._elem_ctype = cls` set — a direct reference to
the element type object, not just its name string. This lets the simulator zero-initialize
arrays of structs correctly (`_make_sim_zero`, see
[`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md)): re-deriving the element type by
parsing `_ctype_name` (stripping the trailing `[N]`) only recovers a name string, which
is enough for scalar elements (`_make_ctype("uint1_t")` is equivalent to `uint1_t`) but
not for struct elements, since a struct's field layout isn't recoverable from its name
alone. `_elem_ctype` is preferred when present; the string-derived fallback still exists
for array types constructed without going through `__getitem__`.

### Type Factories

```python
make_uint_t(width: int) → uintN_t       # e.g. make_uint_t(24) → uint24_t
make_int_t(width: int)  → intN_t        # e.g. make_int_t(33) → int33_t
```

`_make_ctype(name)` is the primitive: creates a class with `_CTypeMeta` metaclass and
`_ctype_name = name`. Both factories call it.

### `make_float_t(E, M)`

Builds a `@struct` NamedTuple type with three fields: `sign` (1 bit), `exp` (E bits),
`man` (M bits). Matches IEEE 754 layout for standard sizes. Adds a `.as_const(value)`
staticmethod that converts a Python `float` to the field dict at elaboration time using
`struct.pack` for FP32/FP64, or a rebased FP64 approximation for other widths.

### Predefined Types

```
uint1_t  uint2_t  uint3_t  uint4_t  uint8_t  uint16_t  uint32_t  uint64_t
int1_t   int2_t   int3_t   int4_t   int8_t   int16_t   int32_t   int64_t
```

All declared as proper `class` statements (not variable assignments) so static analysis tools
accept them. `float16_t`, `float32_t`, `float64_t` are produced by `make_float_t`.

### `_INT_CTYPE_RE`

A compiled `re.Pattern` that matches C integer type strings like `"uint32_t"` or `"int8_t"`.
Imported by `PY_TO_LOGIC.py` for type classification during elaboration.

---

## Type Utilities

These pure functions are the single source of truth for integer type arithmetic shared by
the simulator (`SimVal` operators) and the elaborator (`PY_TO_LOGIC._elab_binop`).
All are cached with `@lru_cache(maxsize=None)` for performance.

### `_ctype_is_int(c_type: str) → bool`

Returns True if `c_type` is a C integer type (`uint*_t` or `int*_t`). Uses `_INT_CTYPE_RE`.

### `_ctype_info(c_type: str) → (is_signed: bool, width: int)`

Parses a C type string into its (signed, width) components.

### `_int_ctype(signed: bool, width: int) → str`

Constructs a C type string from (signed, width). Inverse of `_ctype_info`.

### `_infer_literal_ctype(val: int) → str`

Computes the minimum-width C type for a Python integer literal:

```python
_infer_literal_ctype(0)    # "uint1_t"
_infer_literal_ctype(5)    # "uint3_t"
_infer_literal_ctype(255)  # "uint8_t"
_infer_literal_ctype(-1)   # "int1_t"
_infer_literal_ctype(-2)   # "int2_t"
```

Non-negative: `val.bit_length()` bits unsigned (minimum 1). Negative: `(-val - 1).bit_length() + 1`
bits signed.

### `_arith_promote(l_type: str, r_type: str) → (eff_l: str, eff_r: str)`

Computes the effective (promoted) types for a binary arithmetic operation following C-style
mixed-signedness rules. If one operand is signed and the other unsigned, and the unsigned
type is at least as wide, the signed type is extended by one bit so the result is signed.
Returns the two effective types after promotion.

### `_arith_output_ctype(op: str, eff_l: str, eff_r: str, result_signed: bool) → ctype`

Computes the output type for arithmetic operations:

| `op` | Output width |
|---|---|
| `"add"` | `max(lw, rw) + 1` |
| `"sub"` | `max(lw, rw) + 1` |
| `"mul"` | `lw + rw` |
| others | `max(lw, rw)` |

Returns a `_CTypeMeta` class object. Cached so that the same `(op, types)` key always
returns the **same class object** — enabling `is`-comparison fast-paths in `_sim_val_make`.

### `_is_scalar_pypeline_int(ctype) → bool`

True if `ctype` is a scalar (non-array, non-struct) Pypeline integer type.

### `_ctype_str(t) → str`

Returns the canonical C type name string for a type object (handles both `_CTypeMeta`
instances and `@struct` NamedTuple types via `_pypeline_ctype_name`).

---

## Struct Support

### `NamedTuple`

Re-export of `typing.NamedTuple` for user convenience:

```python
from pypeline import NamedTuple, struct, uint32_t

@struct
class point_t(NamedTuple):
    x: uint32_t
    y: uint32_t
```

### `@struct` Decorator

The `@struct` decorator does three things at decoration time:

**1. Stamps `_pypeline_ctype_name`** — a canonical C type name derived entirely from
the class name and field types, with no dependence on the Python variable name:

```
<class_name>_<field1>_<type1_mangled>_<field2>_<type2_mangled>_...
```

Array brackets are mangled: `[` → `_`, `]` removed. Examples:

```python
# class point_t with fields x: uint32_t, y: uint32_t
# _pypeline_ctype_name = "point_t_x_uint32_t_y_uint32_t"

# class float_t with fields sign: uint1_t, exp: uint8_t, man: uint23_t
# _pypeline_ctype_name = "float_t_sign_uint1_t_exp_uint8_t_man_uint23_t"
```

Two factory calls with identical class name and field types produce the same canonical name
and share a single VHDL type declaration — correct deduplication without module prefixing.

**2. Adds `__class_getitem__`** via `_struct_class_getitem` so that `point_t[10]`
produces `_make_ctype("point_t_x_uint32_t_y_uint32_t[10]")` — a valid array C type usable
in further annotations. The canonical name is used as the base. As with `_CTypeMeta.__getitem__`
above, the returned array class also gets `_elem_ctype = point_t` set, so the simulator can
zero-initialize `point_t[10]` arrays as a list of zero-valued `point_t` instances rather than
a list of bare `0`s.

**3. Overrides `__new__`** with `_typed_new` to wrap scalar integer fields — and scalar
*array* fields, element-wise — in typed simulation values when constructing struct
instances. This enables `left.exp` in `float_add` to carry the correct `_ctype` (`uint8_t`
for float32) so `concat(x_hidden, left.man)` can infer field widths without being told. Two
code paths:

- **Normal sim mode** (`SIM_RAW_INTS=False`): wraps scalar fields with `_int_new(SimVal, ...)` +
  `_obj_setattr(obj, "_ctype", ftype)` (bypasses `SimVal.__new__` Python overhead). A field
  whose type is an array of a scalar pypeline int (e.g. `keep: uint1_t[n]`) and whose value
  is a plain Python `list` (e.g. a list-literal argument) has each element cast individually
  via `_sim_cast(e, elem_ctype)`, using the element ctype resolved by `_array_elem_ctype`
  (see [`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md#regt-simulation--stateful-registers-across-clock-cycles)).
- **Raw sim mode** (`SIM_RAW_INTS=True`): wraps scalar fields with `_RawField(int(v))` —
  `int` subclass keeping C-level arithmetic, with `__getitem__` for bit-slicing. Scalar array
  fields get the same per-element `_RawField` wrap.

Nested-struct fields are passed through unchanged in both modes — a struct-typed value
arriving here is either already a typed instance (built through its own `_typed_new`) or a
raw object the elaborator/sim layer doesn't need to touch at this level. Without the
array-of-scalar handling above, a raw list literal passed straight into a struct constructor
(e.g. `narrow_bus_t(data=[0]*n, keep=[0]*n)`) would silently keep untyped `int` elements —
this previously broke `~`/other bit-width-sensitive ops on values read back out of such a
field (see [`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md#regt-simulation--stateful-registers-across-clock-cycles)
for the full mechanism and the matching `_make_sim_zero`/Rule 4 fixes).

**Hardware transparency:** `SimVal` subclasses `int`, and `_RawField` subclasses `int`, so
struct instances returned by `as_const` or any constant helper are seen as plain integers by
`_elab_compound_init_from_pyval` in the elaborator.

---

## Annotation Types

Each annotation type is a descriptor class returned by `__class_getitem__` with the following
pattern (using `Reg` as example):

```python
class _RegType:
    def __class_getitem__(cls, inner_type):
        return cls(inner_type)  # creates a typed descriptor
```

The five annotation types and what they mean conceptually:

### `Reg[T]` / `_RegType`

Declares a **hardware register** (D flip-flop). Persists across clock cycles.
- Default reset value: zero
- Optional initializer: `cnt: Reg[uint32_t] = 10` sets power-on reset value
- Valid only inside hardware function bodies
- Implies clock-enable behaviour: writes inside `if` only latch when condition is true
- `@hw_func` (or `@MAIN`) required for simulation infrastructure to engage
- Optional second subscript argument tags the register as one endpoint of a
  `MULTI_CYCLE[...]` timing constraint: `Reg[T, tag]` where `tag` is
  `MULTI_CYCLE[ncycles].start` or `.end` — see
  [`MULTI_CYCLE[ncycles]` — Multi-Cycle Path Tag](#multi_cyclencycles--multi-cycle-path-tag)
- When `T` is a struct/array, nested field/element writes (`reg.field = expr`,
  `reg.nested.arr = [...]`) are supported in both backends: simulation via
  `_sim_lens_set` (Rule 3b/4 in [`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md#_typedannassignrewriter--truncation-at-every-typed-assignment)),
  hardware elaboration via `_elab_compound_init` (see
  [`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md#compound-initializer-syntax))

### `Feedback[T]` / `_FeedbackType`

Declares a **combinatorial feedback wire** — a signal whose driver appears later in
Python source order than its first use. No flip-flop is inferred; no initial value.
- Valid only inside hardware function bodies
- `@hw_func` required for simulation convergence loop to engage
- Cannot have an initializer at declaration site (elaboration error)

### `Wire[T]` / `_WireType`

Declares a **shared combinatorial wire** at module level, visible across `@MAIN` functions.
- Valid only at module (global) scope — error if used inside a function body
- Exactly one writer function; any number of readers
- A function cannot both read and write the same wire
- No initializer allowed at declaration
- In single-function simulation (`sim_call`): limited support; multi-MAIN simulation via `pypeline_sim.py` is the intended path

### `Input[T]` / `_InputType`

Module-level annotation declaring a **top-level FPGA input port**.
- Globally read-only — no function may write it
- Name appears verbatim as VHDL entity port (no module prefix)
- Must be a legal VHDL identifier (elaboration error if not)

### `Output[T]` / `_OutputType`

Module-level annotation declaring a **top-level FPGA output port**.
- Exactly one writing function, exactly one hierarchy instance
- Name appears verbatim as VHDL entity port (no module prefix)
- Must be a legal VHDL identifier

---

## `PART()` and `@MAIN` Pragmas

### `PART(part_string)`

Called once at module level to register the FPGA target device:

```python
PART("xc7a35ticsg324-1l")
```

Sets the module-level `_part_registry` string. `PY_TO_LOGIC.PARSE_FILE` reads it after
executing the design module and writes it to `parser_state.part`. When `None`, the toolchain
defaults to a software timing estimator.

### `@MAIN` / `@MAIN(mhz)` — Three-Form Decorator

```python
@MAIN               # no clock constraint
@MAIN(100.0)        # positional MHz
@MAIN(mhz=25.0)     # keyword MHz
def my_design(...): ...
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
    wrapped = _sim_type_wrap(func)   # implies @hw_func
    _main_registry.append(wrapped)
    return wrapped
```

**`@MAIN` implies `@hw_func`:** `_register_main` calls `_sim_type_wrap` before registering,
so every `@MAIN` function automatically gets simulation type wrapping. Users do not need both
`@MAIN` and `@hw_func` on the same function.

### `autopipeline(call_result, depth=-1)` — Forced Submodule Pipelining

Python equivalent of PipelineC's `#pragma AUTOPIPELINE <depth>`. Wrap a single direct
function call to force the synthesizer to slice (insert pipeline registers) through that
call's submodule, even inside a register/feedback context that would otherwise forbid
added latency:

```python
rv = autopipeline(some_func(x))          # auto depth
rv = autopipeline(some_func(x), 2)       # explicit depth
rv = autopipeline(some_func(x), depth=2)
```

At simulation time it is a plain identity passthrough:

```python
def autopipeline(call_result, depth: int = -1):
    return call_result

autopipeline._is_autopipeline_pragma = True
```

The `_is_autopipeline_pragma` flag is the only thing the elaborator inspects (mirroring
`@sim_output`'s `_is_sim_output` flag). See
[`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md#autopipelinecall_expr-depth--forced-submodule-pipelining)
for how `PY_TO_LOGIC.FuncElaborator._elab_call` unwraps the call and tags the resulting
submodule instance. The underlying `Logic()` fields
(`next_func_call_autopipeline_depth`, `sub_inst_to_autopipeline_depth`) and the
synthesis-side forced-slicing mechanism are shared, unmodified, with the C frontend.

### `MULTI_CYCLE[ncycles]` — Multi-Cycle Path Tag

Python equivalent of PipelineC's `#pragma MULTI_CYCLE <ncycles> <start_reg> <end_reg>`.
Unlike `PART(...)` and `autopipeline(...)`, this is not a call at all — `MULTI_CYCLE` is a
subscriptable class (same idiom as `Reg`/`Feedback`/`Wire`), and the cycle count and two
register endpoints are attached directly to the `Reg[T]` declarations they constrain:

```python
MC = MULTI_CYCLE[32]
data0: Reg[my_struct_t, MC.start]
data1: Reg[my_struct_t, MC.end]
```

```python
class _MultiCycleRole:
    def __init__(self, tag, is_start):
        self.tag = tag
        self.is_start = is_start

class _MultiCycleTag:
    def __init__(self, ncycles):
        self.ncycles = ncycles
        self.start = _MultiCycleRole(self, is_start=True)
        self.end = _MultiCycleRole(self, is_start=False)

class _MultiCycleMeta(type):
    def __getitem__(cls, ncycles):
        if not isinstance(ncycles, int):
            raise TypeError(f"MULTI_CYCLE[ncycles] expects an int, got {ncycles!r}")
        return _MultiCycleTag(ncycles)

class MULTI_CYCLE(metaclass=_MultiCycleMeta):
    pass
```

`_RegType`/`_RegMeta` (see [`Reg[T]` / `_RegType`](#regt--_regtype) above) accept this as
an optional second subscript argument, storing it as `_RegType.multi_cycle_role`.
`MULTI_CYCLE`/`_MultiCycleTag`/`_MultiCycleRole` are plain Python objects with no
hardware-wire involvement, so this whole mechanism is ordinary Python at every layer
(module exec, proto-simulation, elaboration's `_try_eval_const`) — no simulation-specific
code is needed. See
[`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md#multi_cyclencycles--regt-tag--multi-cycle-path-constraint)
for how `PY_TO_LOGIC.FuncElaborator._elab_ann_assign`/`_tag_multi_cycle_reg` consume the
role and populate `Logic.mcp_tuples` — shared, unmodified, with the C frontend.

### `wires(func)` — Just-Wires Synthesis Hint

Python equivalent of PipelineC's `#pragma FUNC_WIRES <func_name>`. Tags a function
definition as pure rewiring/bit-casting logic with no real combinational delay, so the
synthesizer treats its whole hierarchy as zero-delay instead of estimating timing for it
(see `include/leds/leds_port.c` for the C original — it tags its
`#pragma MAIN leds_module` function this way):

```python
from pypeline import wires

@wires
def my_struct_to_bytes(x: my_struct_t) -> uint8_t[4]:
    ...
```

Unlike `autopipeline(...)` (wraps a call expression) or `MULTI_CYCLE[...]` (tags a `Reg[T]`
declaration), `FUNC_WIRES` tags a *function definition* — the same shape as `@MAIN` and
`@sim_output`. Implementation mirrors `_register_main`'s "implies `@hw_func`" pattern
(see [`@MAIN` / `@MAIN(mhz)` — Three-Form Decorator](#main--mainmhz--three-form-decorator)
above):

```python
def wires(func):
    wrapped = _sim_type_wrap(func)
    wrapped._is_func_wires_pragma = True
    return wrapped
```

**`@wires` implies `@hw_func`:** like `@MAIN`, it calls `_sim_type_wrap` before stamping
the flag, so a "just wires" helper can be passed straight to `sim_call()` — no separate
`@hw_func` needed. Because `_sim_type_wrap` already sets `__wrapped__` via
`functools.wraps`, `inspect.unwrap()` in `PY_TO_LOGIC._elaborate_live_func` recovers the
original source exactly as it already does for `@hw_func`/`@MAIN` — `wires` adds no
extra wrapping layer of its own. It stacks with `@MAIN` in either order (mirroring the two
independent C pragmas on `leds_module`); whichever decorator runs last is the one bound to
the module-level name, and the `_is_func_wires_pragma` flag survives either order because
`_sim_type_wrap`'s `functools.wraps` merges `__dict__` from the wrapped object.

The `_is_func_wires_pragma` flag is the only thing the elaborator inspects (mirroring
`@sim_output`'s `_is_sim_output` flag and `autopipeline`'s `_is_autopipeline_pragma`
flag). See
[`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md#wires--just-wires-synthesis-hint) for how
`PY_TO_LOGIC.PARSE_FILE` / `FuncElaborator._elaborate_live_func` consume it and populate
`parser_state.func_marked_wires`. The underlying `ParserState.func_marked_wires` set and
`SYN.LOGIC_IS_ZERO_DELAY` consumer are shared, unmodified, with the C frontend.

### Registries

| Name | Type | Content | Consumer |
|---|---|---|---|
| `_main_registry` | `list` | All `@MAIN`-wrapped functions, in decoration order | `pypeline_sim.py` — to discover MAINs for multi-MAIN sim |
| `_main_mhz_registry` | `dict[str, float]` | `func.__name__` → MHz | `PY_TO_LOGIC.PARSE_FILE` — populates `parser_state.main_mhz` |
| `_part_registry` | `str \| None` | FPGA part string | `PY_TO_LOGIC.PARSE_FILE` — populates `parser_state.part` |

---

## Operator Registry

Custom hardware operators can be registered for specific type pairs. The registry is consulted
by both the hardware elaborator (to pick the right submodule) and the simulator (`SimVal`
operator dispatch). Three registration functions are exported:

```python
register_operator(op, lhs_t, rhs_t, impl, scope=None)
register_left_operator(op, lhs_t, impl, scope=None)
register_unary_operator(op, operand_t, impl, scope=None)
```

### Op String Values

| `op_str` | Python operator |
|---|---|
| `"PLUS"` | `+` |
| `"MINUS"` | `-` (binary) |
| `"SL"` | `<<` |
| `"SR"` | `>>` |
| `"NEGATE"` | `-` (unary) |

### Global Registries

```python
_operator_registry:       dict[(op, lhs_type, rhs_type), impl]  # exact match
_left_operator_registry:  dict[(op, lhs_type), impl]             # left-type match
_unary_operator_registry: dict[(op, operand_type), impl]         # unary
```

The elaborator tries exact match first, then left match. `impl` is either a string
(module-level callable name) or a callable.

### Scoped Registrations

`scope=<callable>` limits a registration to the duration of one function's elaboration/call.
Scoped entries are stored separately:

```python
_scoped_operator_registry:      dict[id(func), {key: impl}]
_scoped_left_operator_registry: dict[id(func), {key: impl}]
_scoped_unary_operator_registry: dict[id(func), {key: impl}]
```

**`_push_scoped_registrations(func)`** merges scoped entries for `func` into the global
registries and returns a save-list of `(registry, key, old_value)` triples for restoration.

**`_pop_scoped_registrations(saved)`** restores the previous global registry state using
that save-list.

**Performance:** `_scoped_funcs: set` tracks `id(func)` for any function that has ever had
a scoped registration. `_push_scoped_registrations` returns the module-level singleton
`_EMPTY_SAVED = []` immediately when `id(func) not in _scoped_funcs`, avoiding the dict
iteration entirely for the vast majority of functions.

**`_registered_binary_op_names`** and **`_registered_unary_op_names`** are module-level
sets that track which op names have at least one *global* (non-scoped) registration.
`SimVal.__rshift__`, `__lshift__`, `__neg__`, `__invert__` check these sets and skip
dispatch entirely when no registration exists — critical for performance in the common case
(see `pypeline_sim_DESIGN.md` performance section).

`register_operator` and `register_left_operator` add to `_registered_binary_op_names` when
`scope is None`. `register_unary_operator` adds to `_registered_unary_op_names` when `scope
is None`.

---

## `SimVal` — Typed Simulation Integer

`SimVal` is a thin `int` subclass that adds hardware-type awareness for simulation. The
hardware elaborator (`PY_TO_LOGIC.py`) **never** uses `SimVal` — it treats all `SimVal`
values as plain `int` because `SimVal` subclasses `int`.

### Core Design

```python
class SimVal(int):
    __slots__ = ("_ctype",)   # one extra attribute: the C type string
```

`_ctype` is `None` for untyped simulation values and a `_CTypeMeta` class for typed ones.
Using `__slots__` avoids a per-instance dict but is only possible here (not for full `int`
decoupling — see performance section in `pypeline_sim_DESIGN.md`).

### `__getitem__` — Hardware Bit Slicing

```python
v[i]      # extract bit i     → int (0 or 1)
v[hi:lo]  # extract bits hi down to lo inclusive → int
```

Python's `int` has no `__getitem__`; `SimVal` adds it to match hardware bit-slice syntax.
High index first, matching Verilog/VHDL convention.

### Operator Dispatch

`SimVal.__neg__`, `__rshift__`, `__lshift__` check the operator registries for custom
implementations before falling back to Python arithmetic.

Fast-path: check `_registered_binary_op_names` / `_registered_unary_op_names` sets first.
If the op name is not in the set, skip registry lookup entirely and compute the result
directly (with `_ctype` preserved for shifts).

### Hardware-Accurate Arithmetic (`SIM_STRICT_ARITH=True`)

When `SIM_STRICT_ARITH = True` (default), `__add__`, `__sub__`, and `__mul__` apply
hardware type-promotion before returning, provided **both** operands carry a known `_ctype`:

```python
SimVal(20000, int16_t) + SimVal(20000, int16_t)
# → _arith_promote("int16_t", "int16_t") — no change (same sign)
# → _arith_output_ctype("add", "int16_t", "int16_t", signed=True) → int17_t
# → mask to int17_t → SimVal(40000, int17_t)
```

Masking is now inlined directly in each operator (avoiding the `_sim_cast` function call
overhead in the hot path).

When either operand lacks `_ctype` (plain int literal, shift result, etc.), the result
falls back to a bare `SimVal` with no `_ctype`. Typed operands are re-injected by
`@hw_func` input casts and `_TypedAnnAssignRewriter` at assignment points.

Bitwise ops (`&`, `|`, `^`, `~`) always return bare `SimVal` with no `_ctype`.

### Allocation Helpers

**`_sim_val_make(v, ctype)`** — bypasses `SimVal.__new__` (a Python function, adding
~0.1 µs per allocation) by calling the C-level constructors directly:

```python
_int_new = int.__new__
_obj_setattr = object.__setattr__

def _sim_val_make(v, ctype):
    if 0 <= v <= _SIM_CONST_MAX:
        cached = _SIM_CONST_CACHE.get((v, ctype))
        if cached is not None:
            return cached
    obj = _int_new(SimVal, v)
    _obj_setattr(obj, "_ctype", ctype)
    return obj
```

**`_SIM_CONST_CACHE`** — flyweight cache for `SimVal` instances of values 0–15 per ctype
(`_SIM_CONST_MAX = 15`). Populated lazily on first use of each ctype by `_sim_type_init`.
VGA control signals (`hs`, `vs`, enable flags) and CORDIC step counters produce heavy reuse
of 0 and 1 for `uint1_t`, making this cache effective.

### `_RawField(int)` — Raw Mode Struct Fields

Used when `SIM_RAW_INTS=True`. `int` subclass that only adds `__getitem__` for bit slicing.
All arithmetic inherits from `int` at C level — no Python dispatch overhead. Arithmetic
results are plain `int`, breaking any SimVal chain, which is intentional in raw mode.

### Type Invariant

**`type(x) is SimVal`** is used throughout the hot paths rather than `isinstance(x, SimVal)`.
Subclassing `SimVal` is therefore prohibited as a design constraint — the `is`-comparison
would fail for subclasses, causing incorrect simulation results.

---

## `concat(*args)` — Bit Concatenation

`concat` packs multiple unsigned integers end-to-end, first argument in the
most-significant position. It is dual-mode: it works in both hardware elaboration and
simulation without requiring separate implementations.

```python
out: uint64_t = concat(hi_word, lo_word)   # uint32_t ++ uint32_t → uint64_t
packed: uint24_t = concat(r, g, b)         # three uint8_t values → uint24_t
```

**In hardware elaboration:** `concat` is in `BIT_MANIP_FUNC_NAMES`. The `concat` branch in
`_elab_bit_manip_call` synthesizes a synthetic `ast.Tuple` from the positional arguments
and delegates to `_elab_tuple_concat`, which emits a chain of `TUPLE_CONCAT_<types>`
submodule instances. Any `out_t=` keyword argument is silently ignored.

**In simulation:** width of each argument is inferred:
- `SimVal` with `_ctype` → `len(_ctype)` bits
- Plain Python `int` → `max(1, val.bit_length())` bits (matches hardware literal inference)

The result is a `SimVal` with `_ctype = make_uint_t(total_bits)`.

### `BIT_MANIP_FUNC_NAMES`

A `frozenset` of function names that the elaborator intercepts as built-in bit manipulation
rather than resolving as user-defined callables:

```python
BIT_MANIP_FUNC_NAMES = frozenset({
    "concat", "bit_dup", "rotl", "rotr", "bswap",
    "bit_assign", "array_to_uint_be", "array_to_uint_le",
    "uint_to_array_be", "uint_to_array_le",
})
```

---

## `vhdl(text)` — Raw VHDL Passthrough

Like the bit-manipulation primitives above, `vhdl` is a real top-level function in
`pypeline.py` that the elaborator (`PY_TO_LOGIC.py`) recognizes structurally by name and
never actually calls. Unlike them, it is **not** dual-mode: there is no general way to
simulate arbitrary user-supplied VHDL text in Python, so `vhdl`'s body unconditionally
raises:

```python
def vhdl(vhdl_text):
    raise NotImplementedError(
        "vhdl(...) has no simulation model yet. ..."
    )
```

This means a function whose body is `vhdl(...)` elaborates to hardware normally, but
cannot be exercised through `sim_call()`/`pypeline_sim.py`/a direct call — doing so
raises `NotImplementedError` immediately, rather than silently returning a wrong value or
running real (but unrelated) Python code, as could happen if `vhdl` were missing
entirely (`NameError`) or aliased to something else. See `PY_TO_LOGIC_DESIGN.md` →
"Raw VHDL Passthrough (`vhdl(...)`)" for the elaboration side, including how the text
argument is resolved via `_try_eval_const` (so it can be any compile-time-computed
Python string, not just a literal) and how it's stored on the shared
`Logic.vhdl_module_text` field (also used by the C frontend's `__vhdl__("...")`).

---

## Reference: `pypeline.py` Public API

| Name | Purpose |
|---|---|
| `uint1_t` … `uint64_t` | C unsigned integer types as real Python classes (`_CTypeMeta` metaclass) |
| `int1_t` … `int64_t` | C signed integer types |
| `float16_t`, `float32_t`, `float64_t` | Float struct types (sign/exp/man fields) |
| `make_uint_t(n)` | Dynamically creates `uintN_t` for arbitrary bit width `n` |
| `make_int_t(n)` | Dynamically creates `intN_t` for arbitrary bit width `n` |
| `make_float_t(E, M)` | Creates an IEEE 754-like struct type; `.as_const(v)` converts Python float |
| `NamedTuple` | Re-export of `typing.NamedTuple` |
| `@struct` | Adds `__class_getitem__`, stamps canonical `_pypeline_ctype_name`, wraps scalar fields in sim |
| `@MAIN` | Registers a function as a hardware entry point; implies `@hw_func`; appends to `_main_registry` |
| `@sim_output` | Marks a function as simulation output-only; no-op during convergence passes; executes in final pass per cycle |
| `autopipeline(call_result, depth=-1)` | Wraps a single direct call; identity in sim; forces pipelining through that submodule during elaboration (equivalent to `#pragma AUTOPIPELINE`) |
| `MULTI_CYCLE` / `_MultiCycleTag` / `_MultiCycleRole` | `MULTI_CYCLE[ncycles]` tag; `.start`/`.end` attach to `Reg[T, tag]` declarations to relax setup timing between them (equivalent to `#pragma MULTI_CYCLE`) |
| `wires` | Marks a function as pure rewiring/bit-casting with no real delay; implies `@hw_func`; stacks with `@MAIN` in either order (equivalent to `#pragma FUNC_WIRES`) |
| `Reg` / `_RegType` | Register descriptor; `Reg[T]` declares a stateful register; optional init value (`Reg[T] = val`); optional `Reg[T, tag]` multi-cycle role |
| `Feedback` / `_FeedbackType` | Feedback wire descriptor; `Feedback[T]` declares a combinatorial feedback wire (no flip-flop) |
| `Wire` / `_WireType` | Global wire descriptor; `Wire[T]` at module level declares a shared combinatorial wire (one writer) |
| `Input` / `_InputType` | Top-level input port; `Input[T]` at module level; any function may read, none may write |
| `Output` / `_OutputType` | Top-level output port; `Output[T]` at module level; exactly one function/instance may write |
| `register_operator(op, lhs, rhs, impl, scope=None)` | Binds a binary operator on an exact `(lhs, rhs)` type pair |
| `register_left_operator(op, lhs, impl, scope=None)` | Binds a binary operator matching only on left operand type |
| `register_unary_operator(op, operand, impl, scope=None)` | Binds a unary operator for a specific operand type |
| `_push_scoped_registrations(func)` | Merges scoped operator entries for `func` into globals; returns save-list |
| `_pop_scoped_registrations(saved)` | Restores global registries from save-list |
| `bit_dup`, `rotl`, `rotr`, `bswap`, `bit_assign` | Bit manipulation primitives (hardware + sim) |
| `array_to_uint_be/le`, `uint_to_array_be/le` | Array ↔ integer packing primitives |
| `concat(*args)` | Bit concatenation — works in hardware (→ `TUPLE_CONCAT`) and simulation (→ typed `SimVal`) |
| `BIT_MANIP_FUNC_NAMES` | Frozenset of function names intercepted as built-in bit manipulation by the elaborator |
| `vhdl(text)` | Raw VHDL passthrough — recognized structurally by name in `PY_TO_LOGIC._elab_stmt`, never called during elaboration; the real function only runs when called outside elaboration (directly, via `sim_call()`, or via `pypeline_sim.py`) and always raises `NotImplementedError` — no simulation model yet |
| `_make_ctype(name)` | Dynamically creates C type class objects (used by `make_uint_t`, array subscript, etc.) |
| `SimVal` | Simulation typed integer: bit-slice `__getitem__`, operator dispatch, hardware-accurate arithmetic |
| `_RawField` | Raw-mode int subclass for struct fields: C-level arithmetic + `__getitem__` for bit slicing |
| `_sim_cast(val, ctype)` | Cast a Python int/SimVal to a pypeline ctype: mask to bit width, two's-complement sign |
| `_sim_val_make(v, ctype)` | Fast `SimVal` allocation bypassing Python `__new__`; checks flyweight cache first |
| `_SIM_CONST_CACHE` | Flyweight cache: `(int_value, ctype)` → `SimVal` for values 0–15 per ctype |
| `hw_func` | Decorator for inner hardware functions; adds sim-mode type casting and register state management |
| `sim_call(func, *args)` | Call a pypeline function in simulation mode with scoped operators active |
| `sim_reset()` | Clear all simulated register state and global wire state; restores declared init values |
| `sim_wire_reset()` | Clear only `_sim_wire_state`; leaves register state intact |
| `_sim_inst_stack` | Module-level list: current simulation instance path; pushed/popped by `@hw_func`/`@MAIN` wrappers |
| `_sim_reg_state` | Module-level dict: `inst_path → {reg_name: value}`; persistent register values across `sim_call` |
| `_sim_wire_state` | Module-level dict: `wire_name → int`; current global wire values (keyed by name, not instance) |
| `_sim_wire_readers` | Module-level dict: `wire_name → set[MAIN fn]`; dependency graph for convergence queue |
| `_sim_converging` | Module-level bool; `True` during delta-cycle convergence; checked by `@sim_output` wrappers |
| `_sim_current_main` | Module-level variable; MAIN function currently executing; enables wire reader recording |
| `_sim_reg_begin_buffer()` | Switch register writes to buffered mode (used by `pypeline_sim.py` per cycle) |
| `_sim_reg_flush_buffer()` | Commit buffered register writes atomically — the simulated clock edge |
| `_main_registry` | Module-level list of all `@MAIN`-decorated (wrapped) functions in decoration order |
| `_main_mhz_registry` | Module-level dict: `func.__name__` → MHz (read by `PY_TO_LOGIC.PARSE_FILE`) |
| `_part_registry` | Module-level str or None: FPGA part string (read by `PY_TO_LOGIC.PARSE_FILE`) |
| `SIM_STRICT_ARITH` | Bool flag (default `True`): apply hardware type-promotion and masking on arithmetic |
| `SIM_RAW_INTS` | Bool flag (default `False`): bypass all `SimVal` wrapping for maximum speed |
| `SIM_TRACE_LOCATIONS` | Bool flag (default `False`): capture column positions for multi-instance register designs |
| `_arith_promote` | Compute promoted types for mixed signed/unsigned arithmetic (shared with elaborator) |
| `_arith_output_ctype` | Compute output type for arithmetic operations (shared with elaborator) |
| `_ctype_is_int` | Test whether a C type string is an integer type (shared with elaborator) |
| `_ctype_info` | Parse C type string into (is_signed, width) (shared with elaborator) |
| `_ctype_str` | Get canonical C type name string for a type object (shared with elaborator) |

All types are declared as proper Python `class` statements with `_CTypeMeta` as metaclass
(not variable assignments), so Pylance/pyright accepts them as valid type expressions.
Adding `# pyright: reportInvalidTypeForm=none` to design files suppresses warnings for
dynamically-produced types like factory structs.
