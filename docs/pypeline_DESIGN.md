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
- [Tests](#tests)

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

The returned array class also gets `arr._elem_ctype` and `arr._arr_len` set — a direct
reference to the element type object (not just its name string) and this array's own
outer element count. This lets the simulator zero-initialize arrays of structs correctly
(`_make_sim_zero`, see [`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md)): re-deriving
the element type by parsing `_ctype_name` only recovers a name string, which is enough
for scalar elements (`_make_ctype("uint1_t")` is equivalent to `uint1_t`) but not for
struct elements, since a struct's field layout isn't recoverable from its name alone.
`_elem_ctype`/`_arr_len` are preferred when present; the string-derived fallback (leftmost
`[N]`) still exists for array types constructed without going through `__getitem__`.

For a single dimension (`cls` is scalar/struct), `arr._elem_ctype = cls` and
`arr._arr_len = dim`, as above. When chaining further brackets on an already-array `cls`
(e.g. `int8_t[3][4]`, evaluated as `(int8_t[3])[4]`), `__getitem__` does **not** wrap
`cls` as the new element type — it pushes the new dimension onto `cls`'s own element type
(`arr._elem_ctype = cls._elem_ctype[dim]`) and keeps `arr._arr_len = cls._arr_len`. This
matters because Python evaluates `T[A][B]` left-to-right, so a naive wrap-outside
implementation would make the *last*-written bracket the array's outer dimension — the
reverse of C's `T x[A][B]` (`A`, the first-written/leftmost bracket, is outer; `B` is
inner). Pushing new dimensions onto the leaf keeps the first-applied dimension as the
permanent outer/first dimension no matter how many further brackets are chained, matching
C and `PY_TO_LOGIC.py`'s elaboration-side `_array_first_dim`/`_array_elem_type`
(`PY_TO_LOGIC_DESIGN.md`), which always treat the leftmost bracket as outer.

### Type Factories

```python
make_uint_t(width: int) → uintN_t       # e.g. make_uint_t(24) → uint24_t
make_int_t(width: int)  → intN_t        # e.g. make_int_t(33) → int33_t
```

`_make_ctype(name)` is the primitive: creates a class with `_CTypeMeta` metaclass and
`_ctype_name = name`. Both factories call it.

### Floating-point types have moved to `include/pypeline/floating_point.py`

`make_float_t(E, M)` (builds a `@struct` NamedTuple type with three fields: `sign`
(1 bit), `exp` (E bits), `man` (M bits), matching IEEE 754 layout for standard
sizes, plus a `.as_const(value)` staticmethod converting a Python `float` to the
field dict at elaboration time using `struct.pack` for FP32/FP64 or a rebased
FP64 approximation for other widths, and a `__float__` method — the inverse of
`.as_const` — for reading a value back out as a Python `float`) is no longer part
of core `pypeline.py`: it lives in the `floating_point` library alongside the
arithmetic/conversion factories built on it (`make_float_adder`,
`make_float_subtractor`, `make_float_multiplier`, `make_float_divider`,
`make_float_converter`, `make_float_to_int`, `make_int_to_float`,
`register_float_ops`), since none of that is generic beyond floats. Core
`pypeline.py` keeps the generic building blocks it's built from: `make_uint_t`,
`make_int_t`, `struct`, and the operator-registration functions (see
[Operator Registry](#operator-registry)).

### Predefined Types

```
uint1_t  uint2_t  uint3_t  uint4_t  uint8_t  uint16_t  uint32_t  uint64_t
int1_t   int2_t   int3_t   int4_t   int8_t   int16_t   int32_t   int64_t
```

All declared as proper `class` statements (not variable assignments) so static analysis tools
accept them. `float16_t`, `float32_t`, `float64_t` are predefined (with `+`/`-`/`*`/`/`
already registered) in `include/pypeline/floating_point.py`, not here.

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

Array brackets are mangled: `[` → `_`, `]` removed. If the full name exceeds
`_MAX_MANGLE_NAME_LEN` (64 chars) it is replaced with `{class_name}_{sha256[:8]}` of the
full name. The full name is always preserved in `_pypeline_ctype_canonical` for debugging.
Because a field whose type is itself truncated uses the shorter `_pypeline_ctype_name` as
its field-type string, truncation propagates upward through nested structs naturally.

Examples:

```python
# class point_t with fields x: uint32_t, y: uint32_t   (38 chars — kept)
# _pypeline_ctype_name = "point_t_x_uint32_t_y_uint32_t"

# class float_t with fields sign: uint1_t, exp: uint8_t, man: uint23_t, defined directly
# inside make_float_t(exponent_width, mantissa_width) -- the field-derived part alone is
# "float_t_sign_uint1_t_exp_uint8_t_man_uint23_t" (46 chars), but a struct defined inside a
# factory function also gets that factory's own parameters appended (see "Factory parameter
# disambiguation" below), pushing this one over 64 chars and into the truncated form:
# _pypeline_ctype_canonical = "float_t_sign_uint1_t_exp_uint8_t_man_uint23_t_exponent_width_8_mantissa_width_23"
# _pypeline_ctype_name      = "float_t_bdfae6fa"                           (used in VHDL)

# Deeply nested stream_pipeline_t (field types themselves have truncated names → > 64 chars)
# _pypeline_ctype_canonical = "stream_pipeline_t_stream_out_stream_t_..."  (full, for debug)
# _pypeline_ctype_name      = "stream_pipeline_t_d1e1fd20"                 (used in VHDL)
```

Two factory calls with identical class name, field types, *and* (for a struct defined inside
a factory function) identical factory parameters produce the same canonical name and share a
single VHDL type declaration — correct deduplication without module prefixing.

**Factory parameter disambiguation:** a struct class defined directly inside a factory
function (its `__qualname__` contains `.<locals>.`) has that factory's own declared
parameters appended to its canonical name, sorted by parameter name — unconditionally, as a
pure function of the call's own inputs, so the result never depends on elaboration order (no
shared registry is consulted). This is what makes `make_fixed_t(4, 8)` and `make_fixed_t(8, 4)`
produce different canonical names even when both calls happen to produce a field of the exact
same width (e.g. `val: int12_t` either way) — without requiring any change at the `@struct`
call site. A pypeline C type parameter contributes its own canonical name; `int`/`bool`
contributes its value (a negative value uses a `neg` prefix, since a bare `-` is not legal
inside a VHDL identifier); `None` contributes `"None"`. A bare, module-level `@struct` (no
enclosing factory function) is unaffected.

**Field names** are Python identifiers at this layer and are not mangled here — VHDL
reserved-word mangling for individual field names (e.g. a field literally named `label` or
`signal`) happens on the elaboration side, in `PY_TO_LOGIC.py`, everywhere a field name is
turned into a `struct_to_field_type_dict` key or ref_toks token. See
[PY_TO_LOGIC_DESIGN.md's VHDL Identifier Safety section](PY_TO_LOGIC_DESIGN.md#vhdl-identifier-safety--name-sanitization)
for the full list of call sites.

**2. Adds `__class_getitem__`** via `_struct_class_getitem` so that `point_t[10]`
produces `_make_ctype("point_t_x_uint32_t_y_uint32_t[10]")` — a valid array C type usable
in further annotations. The canonical name is used as the base. As with `_CTypeMeta.__getitem__`
above, the returned array class also gets `_elem_ctype = point_t` set, so the simulator can
zero-initialize `point_t[10]` arrays as a list of zero-valued `point_t` instances rather than
a list of bare `0`s.

**3. Overrides `__new__`** with `_typed_new` to wrap scalar integer fields — and scalar
*array* fields, element-wise — in typed simulation values when constructing struct
instances. This enables `left.exp` in `float_add` to carry the correct `_ctype` (`uint8_t`
for float32) so `concat(x_hidden, left.man)` can infer field widths without being told.
`_typed_new` first normalizes positional args to keyword args by zipping them against
`klass._fields`, then updates with any explicit keyword args — supporting positional-only,
keyword-only, and mixed positional+keyword struct construction identically (mirroring
Python's own `NamedTuple.__new__` semantics). Two code paths:

- **Normal sim mode** (`SIM_RAW_INTS=False`): scalar fields are cast via `_sim_cast(v, ftype)`
  — mask/sign-extend to the field's declared bit width, exactly like a hardware-typed
  assignment. This runs *unconditionally*, even when `v` already carries some other `_ctype`:
  `_sim_cast` itself short-circuits to a no-op only when the value's ctype already matches
  `ftype` exactly. This matters because arithmetic on a struct field's value can promote its
  width (e.g. `uint4_t + int` yields a `uint5_t`-tagged `SimVal`) — a value carrying *any*
  ctype is not the same as a value already typed to *this* field, so recasting down to `ftype`
  is required. (Bug fixed 2026-07-24: an earlier version skipped the cast whenever `v` was
  already a typed `SimVal`, so `p_t(c=a.c+1)` at `uint4_t` max silently returned `16` instead
  of wrapping to `0` — divergent from field assignment (`o.c = a.c+1`), which always recasts
  via `_sim_cast_deep` regardless of the RHS's existing ctype. See
  [`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md#regt-simulation--stateful-registers-across-clock-cycles).)
  A field whose type is an array of a scalar pypeline int (e.g. `keep: uint1_t[n]`) and whose
  value is a plain Python `list` (e.g. a list-literal argument) has each element cast
  individually via `_sim_cast(e, elem_ctype)`, using the element ctype resolved by
  `_array_elem_ctype`
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

## Enum Support

### `@enum` Decorator

The `@enum` decorator turns a Python `IntEnum` subclass (or a plain class with int members,
which is auto-converted) into a Pypeline enum type.  Enums are integer-encoded scalar types —
not compound types like structs.

**At decoration time**, `@enum`:

1. Converts a plain class to `IntEnum` if needed.  The plain-class branch iterates
   `vars(cls)` **in definition order** (Python 3.7+ dict order is insertion order).
   Each non-underscore member is handled as follows:
   - `isinstance(v, auto)` → assigns the current 0-based counter, then increments it.
   - `isinstance(v, int)` → uses the explicit value and resets the counter to `v + 1`.
   
   This gives `auto()` a 0-based start (matching PipelineC's C enum convention) with
   no special base class required.  The result is passed to `IntEnum("name", members_dict)`
   which bypasses the `start=1` default entirely.
2. Derives a canonical C type name: `name_MEMBER1_val1_MEMBER2_val2` (members sorted by
   value). SHA256-truncates if the name exceeds `_MAX_MANGLE_NAME_LEN`.
3. Stamps `_pypeline_ctype_name`, `_pypeline_ctype_canonical`, `_pypeline_is_enum = True`,
   and `_pypeline_enum_int_ctype` (e.g. `"uint2_t"`) on the class.

The `_pypeline_ctype_name` attribute means enum types are handled uniformly by
`_inner_ctype_to_str`, `_annotation_to_ctype`, and `_ctype_str` — the same machinery
that already handles struct types.

### `_enum_bit_width(enum_cls) → int`

Computes the minimum uint bit width to represent all enum member values:
```
max(1, max_value.bit_length()) if max_value > 0 else 1
```
Never stored — computed fresh from the IntEnum members whenever needed.

### `_is_scalar_pypeline_int(ctype)` — Enum Path

Updated to check `getattr(ctype, "_pypeline_is_enum", False)` before the `_ctype_name`
path. This makes enum types transparent scalars throughout simulation: `_TypedAnnAssignRewriter`
inserts `_sim_cast` calls, struct `_typed_new` wraps enum-typed fields, and `_sim_type_wrap`
casts arguments and return values.

### Parameterizable Enums

Since `@enum` is callable with a class as its argument, user factories call
`enum(IntEnum("name", members_dict))` — directly analogous to the `@struct` pattern.
No library-provided `make_enum_t` helper: each project writes its own factories.

### `PypelineEnum` Base Class

For users who prefer the `IntEnum`-subclass style over plain classes, `PypelineEnum`
is an `IntEnum` subclass that overrides `_generate_next_value_` to return `count`
(0-based) instead of `start` (1-based):

```python
class PypelineEnum(_IntEnum):
    @staticmethod
    def _generate_next_value_(name, start, count, last_values):
        return count   # 0, 1, 2, …
```

`EnumMeta` resolves `auto()` during class construction, so by the time `@enum` sees
a `PypelineEnum` subclass the values are already correct integers.  No special handling
needed in `@enum` itself — the IntEnum-subclass branch is taken unchanged.

Both `auto()` forms (plain class and `PypelineEnum`) produce identically-typed enums
with the same canonical name and `_pypeline_enum_int_ctype`.

### Introspection API

```python
enum_bit_width(enum_cls) → int       # minimum bit width from member values
enum_uint_type(enum_cls) → uintN_t   # corresponding pypeline uint type
```

---

## Char Array Support

### `char_t` — Predefined Scalar Type

```python
char_t = _make_ctype("char")
```

A plain predefined scalar, exactly parallel to `uint8_t` (single global instance, no
factory function). `char_t[16]` rides the existing `_CTypeMeta.__getitem__` array
machinery for free, producing C-type-string `"char[16]"` — the same convention
PipelineC's C frontend already uses, so the shared backend (`C_TO_LOGIC.py`/`VHDL.py`)
needs no changes to understand `char`/`char[N]` from Pypeline.

`_CTypeMeta.width` special-cases `"char"` → 8 (mirroring `VHDL.py`'s
`GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR`), since its general `(u?)int(\d+)_t` regex doesn't
match the bare name `"char"`. `_ctype_is_int("char")` correctly returns `False` — `char_t`
is excluded from generic integer arithmetic promotion (`_arith_promote`), matching the C
frontend's own behavior where `char` is interchangeable with `uint8_t` only via an
explicit swap in binary ops, not general promotion.

Fixed-size char arrays (`char_t[N]`) require **no other special-casing anywhere** in the
array/struct machinery: `_array_elem_ctype`, `_array_len`, `_make_sim_zero`,
`_sim_cast_deep` (this file) and `_is_array`/`_annotation_to_ctype`/struct discovery
(`PY_TO_LOGIC.py`) are all generic over any scalar element ctype already. A `char_t[16]`
struct field, function param/return, or nested `char_t[3][3]` grid works through the
exact same code paths as `uint8_t[16]` today.

### String Literal Initializers

`name: char_t[16] = "hello"` (and the equivalent struct-field, return, and call-argument
forms) elaborate a Python `str` constant to a **single CONST wire**, mirroring PipelineC's
C frontend exactly (`C_TO_LOGIC.NON_ENUM_CONST_VALUE_STR_TO_LOGIC`/`BUILD_CONST_WIRE`) —
not per-character wires. See
[`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md#string-literal-initializers) for the full
elaboration-side writeup, including the target-type-override trick that gives free
zero-padding via the existing VHDL `to_byte_array` helper, and the known
underscore-in-literal limitation inherited unmodified from the shared backend.

### `strlen(arr)` Builtin

Constant-folds to `arr`'s **declared array length** (its first dimension) at elaboration
time — deliberate parity with PipelineC's `C_AST_STRLEN_FUNC_CALL_TO_LOGIC`, which is
*not* a runtime scan for a NUL terminator. `strlen()` on a `char_t[16]` holding `"hello"`
returns `16`, not `5`. Works for any array type, not just char arrays. The sim-mode
equivalent (`pypeline.strlen`) is just `len(arr)`.

For content-length string display in simulation, use `str(arr)` instead (see
[`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md) — a `char_t[N]` sim value is a
`CharArray` whose `__str__` stops at the first NUL byte) — deliberately distinct from
`strlen()` so the capacity-vs-content distinction stays visible in the API surface.

### Known Limitation: `Reg[T]` Initializers

`Reg[T]` where `T`'s leaf element type is `"char"` (a bare `char_t` register, or any
`char_t[...]` array) **cannot have an explicit initializer** — `= 65`, `= "hello"`, and
`= [65, 66, ...]` all hit a pre-existing bug in `VHDL.CONST_VAL_STR_TO_VHDL`'s char branch,
which assumes its input is always a quoted C-AST character-literal token (e.g. `"'A'"`)
and mishandles a plain Python-int-derived value from Pypeline's
`INIT_PYTHON_VAL_TO_VHDL_INIT_STR` register-init path. This reproduces even for the
simplest case (`Reg[char_t] = 65`, no arrays or strings involved), so it predates and is
independent of char-array support specifically; fixing it would require editing
`VHDL.py`, which char-array support deliberately avoids. `Reg[char_t[N]]` with **no**
initializer (zero-init) is unaffected and works normally through the generic `Reg[T]`
machinery.

---

## Type ↔ Bytes Conversion

```python
byte_length(t) → int
make_type_to_bytes(t, endian="little") → hardware function
make_type_from_bytes(t, endian="little") → hardware function
```

Generic packing of any pypeline type (scalar, array, `@struct`, or any nesting) into a
fixed `uint8_t[N]` array and back, as a packed/unpadded layout (each leaf scalar field
rounds up to a whole byte; no other padding). Replaces hand-written per-type
`concat()`/bit-slicing conversion code such as wireguard-fpga's `bytes_to_uint320()`.
Enum types are not supported (raise `NotImplementedError`, checked recursively).

`byte_length(t)` is a pure-Python recursive walk over the type object — `ceil(width /
8)` per leaf, summed/multiplied through arrays and structs — with no elaborator
involvement, the same shape as `enum_bit_width`/`enum_uint_type` above.

`make_type_to_bytes`/`make_type_from_bytes` generate a **flat** (non-nested)
`def <name>(...): ...` source string per `(type, direction, endian)`, `exec()` it after
patching `linecache` so `inspect.getsource()` succeeds on the result, and tag it
`@wires`. Full mechanics — why the source must be flat rather than a closure, the
`_try_elab_bit_slice` restriction that requires materializing array-indexed leaves into
a plain local before bit-slicing them, and the nested-struct auto-registration helper
— are in [`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md#type-to-bytes-conversion-byte_length-make_type_to_bytes-make_type_from_bytes).

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
  `reg.nested.arr = [...]`, `reg.nested.field = SubStruct_t(...)`) are supported in both
  backends: simulation via
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
- At least one writer function; any number of readers; each writer function must have
  exactly one instance in the design hierarchy. Compound-typed wires (structs and
  arrays, nested arbitrarily) may be split across **multiple** writer functions with
  pairwise-disjoint driven leaves — see "Splitting a compound wire across writers"
  below. A writer may live anywhere in the hierarchy (a helper called from a `@MAIN`),
  not only in a `@MAIN` body.
- No initializer allowed at declaration
- In single-function simulation (`sim_call`): limited support; multi-MAIN simulation via `pypeline_sim.py` is the intended path

**The flattened-leaf model.** A compound global wire behaves exactly as if flattened
into one independent global wire per scalar leaf (each leaf = one scalar reachable
through struct fields / array indices): each leaf is driven by whichever function
writes it, leaves nobody drives read zero, and every reader — including the writer
functions themselves — sees each leaf's live value. All of the semantics below follow
from this one model.

**Reading and writing the same wire, in its writer function.** The writer function
may read the wire it writes. For leaves it drives itself: normal local-variable
semantics — writes/reads interleave in program order, read-before-write returns
**zero**, and the value everyone else sees that cycle is the value at the end of the
writer's body. For leaves a **different** function drives: the read returns that
function's live value (a real cross-function read, not local zeros).

**Partial (field/element) writes and the implicit zero default.** A `Wire[T]` (or
`Output[T]`) of struct/array type does not need every field/element assigned by its
writer(s). Every leaf no function ever touches — and, within a writer, every own leaf
read before it is written — resolves to zero, as if the wire had been implicitly
assigned a whole-value zero immediately on entry to each writer, before its real
assignments. Writes may also be conditional (`if en: w.x = v`): on cycles the branch
doesn't execute, the leaf reads its zero default — the write lowers to a mux whose
else-value is the implicit zero init. Mechanically: `elaborate()` **hoists**
write-declaration of every pre-scanned written wire to before the body (so a wire
whose first textual touch is inside an `if` still has its base declared ahead of the
branch merge), and `_declare_global_write_wire` in `PY_TO_LOGIC.py` gives the base an
implicit first alias using the exact same alias-chain mechanism `_declare_var` uses
for an ordinary local variable (see
[`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md#global-wires)). That first alias is
driven by zeros (`0` / `C_TO_LOGIC.COMPOUND_NULL`) for a write-only function, or by
an internal **readback input wire** (below) for a function that also reads the wire.

**Readback: a writer that also reads its wire.** When the pre-scan finds a function
both writes and reads the same wire, `_declare_global_write_wire` creates an extra
input wire `<name>_PYPELINE_READBACK` of the same type, registers it in the function's
`read_only_global_wires` (so the existing `global_to_module` record-field / entity
read-stage machinery feeds it with zero extra plumbing) and in
`Logic.readback_global_wires`, and uses it as the implicit first alias's driver. The
top level (`VHDL.py`) then feeds that readback record field per region: **zeros in the
regions this function itself drives** (own read-before-write = 0, conditional own
writes default to 0) and **the owning writer's live `module_to_global` value in
foreign regions** — which is precisely the flattened-leaf readback semantics, decided
entirely at the top level with no own/foreign distinction needed during elaboration.
For a single-writer wire every region is its own, so the feed is all zeros; if the
wire is used by nobody else (`GLOBAL_VAR_IS_SHARED` false), a dedicated pass still
emits the all-zeros readback feed. The write side is untouched: the final alias still
drives the base wire and `module_to_global.<name>` exactly as before.

**Splitting a compound wire across writers.** Any static path may be claimed by a
writer, at any depth: nested struct leaves (`w.a.x = ...`), whole subtrees
(`w.a = some_point` — note a struct *literal* RHS is decomposed by
`_elab_compound_init` into per-leaf writes, so only a struct-typed variable/expression
RHS records the interior path itself), and constant array indices (`w.arr[2] = ...`,
including unrolled-loop indices, which elaboration resolves to precise int tokens).
`_write_ref` records each driven path in
`C_TO_LOGIC.Logic.global_wire_driven_paths[wire_name]` — a set of path tuples of
field-name strs / index ints, `()` meaning "whole wire" — skipping the implicit
zero-init write itself (that's a fallback default, not a claimed leaf). A
variable-index write instead marks the wire in
`Logic.global_wire_dynamic_index_writes`, since its concrete driven path can't be
known until runtime and so can't be safely combined with a second writer.

Post-elaboration validation (`PY_TO_LOGIC.py`, end of `PARSE_FILE`) requires at least
one writer per `Wire`/`Output`, each with exactly one hierarchy instance, and — when
there is more than one writer — runs `_check_no_overlapping_driven_paths` over every
writer's driven-path set: two paths from different writers conflict iff one is a
prefix of the other (so `()` conflicts with everything, equal paths conflict, and a
whole-subtree claim conflicts with any deeper claim inside it), which is exactly
"these two writers' claimed leaf territory overlaps," independent of nesting shape.
Any writer of a multi-writer wire found in `global_wire_dynamic_index_writes` is
rejected outright.

On the VHDL side, `VHDL.py`'s "Directly connected global wires" top-level wiring keeps
today's single whole-wire assignment **byte-identical** when a wire has exactly one
writer and no readback (protecting every existing C-frontend and Pypeline design).
When a wire has more than one writer, `BUILD_MULTI_WRITER_REGIONS` recursively splits
the wire's type tree against all writers' driven-path sets into the coarsest list of
`(vhdl_suffix, region_c_type, owner_or_None)` regions — an exactly-claimed path
becomes one region at its own depth, structs/arrays with claims strictly below recurse
per field / per constant element, unclaimed subtrees get `owner=None` — and, for every
reader instance, the `Output[T]` port case, and each writer's readback feed, emits one
concurrent VHDL assignment per region:
`global_to_module.<reader>.<var><suffix> <= module_to_global.<owner>.<var><suffix>;`
for an owned region (array steps render as `(i)`, struct steps as `.field`), or
`... <= <zero constant for that region's type>;` (`C_TYPE_STR_TO_VHDL_NULL_STR`) for
an unclaimed region — and, in a writer's own readback feed, for that writer's own
regions too. Per-region concurrent assignment to distinct static sub-elements of a
shared record/array signal is not a new VHDL pattern here — it mirrors the existing
`INST_ARRAY` multiple-write-instance mechanism (`(i)` sub-element assignment from
distinct writer instances), generalized over the whole type tree. The per-function
`<func>_module_to_global_t` record type is unchanged either way — a writer's own
internal variable still holds the *whole* wire value (implicit zeros in the leaves it
doesn't drive included); only the *top-level* wiring harvests just each writer's own
claimed regions.

Native sim mirrors the per-writer zero default with **runtime claim tracking** rather
than static analysis: every rewritten write call carries the writing function's
qualified name (`claim_key`) and records the concrete path it wrote — static fields,
nested paths, unrolled-loop and dynamic indices all land as the exact elements touched
— into `_sim_wire_claims`; a one-line prologue (`_sim_wire_reset_claims`) zeros
exactly those claimed leaves at the top of each of that function's invocations.
Resetting only the function's own claims (never the whole wire) is essential for
multi-writer wires: a whole-wire reset would transiently wipe a different writer's
already-committed leaves within the same simulated cycle's convergence loop, since
`_sim_wire_state` is shared, persistent process state, not per-invocation-scoped. See
[`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md).

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

### `AUTOPIPELINE(func, depth=-1)` — Forced Submodule Pipelining with `.latency`

Python equivalent of PipelineC's `#pragma AUTOPIPELINE <depth>`, plus a feedback
channel the C pragma doesn't have. `AUTOPIPELINE(func)` is a class (all-caps factory
style, like `MULTI_CYCLE`) whose instances are callable tags: calls made through one
force the synthesizer to slice (insert pipeline registers) through that call's
submodule, even inside a register/feedback context that would otherwise forbid added
latency — and the instance's `.latency` attribute reads back the stage count the
synthesis sweep actually chose:

```python
MY_AP = AUTOPIPELINE(some_func)           # auto depth
MY_AP = AUTOPIPELINE(some_func, depth=2)  # explicit depth
rv = MY_AP(x)                             # some_func(x), autopipelined
MY_AP.latency                             # int, 0 until known
```

At plain simulation time `MY_AP(x)` is a plain identity passthrough (`func(x)`), and
`.latency` stays 0 (the module-level latency cache it reads,
`pypeline._autopipeline_latency_cache`, is only populated by the `pipelinec` driver —
between the pin-and-confirm loop's real synthesizing passes, and again before a
non-`--comb` `--sim` run's native-sim design import, where `.latency` then reads the
built stage count and `MY_AP(x)` emulates the N-stage pipeline with a per-call-site
delay line — see `SYN_DESIGN.md` and `pypeline_sim_DESIGN.md` §"Pipelined native sim").
`.latency` is a read-tracked property: any read flips a module flag
(`AUTOPIPELINE_LATENCY_WAS_READ`) the driver uses to skip the extra pass entirely for
designs that never consume the value. `AUTOPIPELINE.__repr__` is deliberately
address-free *and fully distinguishing* (it embeds the wrapped func's canonical key
when the compiler is loaded): instances get captured in factory closures whose cell
reprs feed canonical entity-name hashing, so an address-bearing repr would rename
entities on every design re-execution, while a repr hiding the wrapped func's
identity would collide wrappers around different factory-produced cores (e.g. several
`make_stream_pipeline` invocations in one design).

The class-level `_is_autopipeline_pragma` flag is the only thing the elaborator
duck-type probes (mirroring `@sim_output`'s `_is_sim_output` flag). See
[`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md#autopipelinefunc-depth--forced-submodule-pipelining)
for how `PY_TO_LOGIC.FuncElaborator._elab_call` elaborates the wrapped func and tags
the resulting submodule instance. The `Logic()` depth field
(`sub_inst_to_autopipeline_depth`) and the synthesis-side forced-slicing mechanism are
shared, unmodified, with the C frontend; the Pypeline frontend additionally records
`sub_inst_to_autopipeline_key` (instance -> `AUTOPIPELINE.canonical_key`) so the sweep's
discovered latencies can be harvested per call site and fed back into `.latency`.

The internal helper `_autopipeline_with_io_regs(func, has_input_reg, has_output_reg)`
(used by `make_stream_pipeline` and the FIR library) wraps `AUTOPIPELINE(func)` with
optional unconditional `Reg[T]` boundary registers and returns
`(wrapped_func, autopipeline_call)` so library code can read `.latency`.

### `AUTOFSM(func)` — Resource-Shared State Machines with `.latency`

The resource-minimizing dual of `AUTOPIPELINE`. Where `AUTOPIPELINE(func)` builds
one full copy of `func`'s hardware cut into pipeline stages (initiation interval
1, maximum area), `AUTOFSM(func)` builds a state machine holding ONE copy of each
distinct operation and runs `func` over several cycles (initiation interval N,
minimum area). Twelve identical adds become one adder used in twelve states.

```python
UPDATE = AUTOFSM(next_state)     # pure single-argument @hw_func
o = UPDATE(req)                  # req/o are {data, valid}: UPDATE.in_stream_t / .out_stream_t
UPDATE.latency                   # fixed in->out cycle count; 0 until a real build
```

Structurally a sibling of `AUTOPIPELINE`, and deliberately so: a duck-type marker
the elaborator probes for (`_is_autofsm_pragma`), a module-global cache the
`pipelinec` driver installs between passes (`SET_AUTOFSM_SCHEDULE_CACHE`,
carrying `canonical_key -> schedule dict` instead of `-> stage count`), a
snapshot taken at construction so one design execution sees one consistent view,
a `canonical_key` computed lazily via `PY_TO_LOGIC.CANONICAL_CALLABLE_KEY`, and
an address-free `__repr__` for the same entity-naming-determinism reason.

The differences worth knowing:

- **The call site's submodule is not `func`.** It is a generated wrapper: a
  combinational passthrough when no schedule is installed, and the generated FSM
  when one is. Both are built by `src/AUTOFSM.py` and elaborated as ordinary
  Pypeline source.
- **`.latency` is not read-tracked.** AUTOPIPELINE can skip its second pass when
  no Python consumed the value; an AUTOFSM schedule always changes the hardware,
  so the second pass is unconditional.
- **`in_stream_t` / `out_stream_t`** are auto-generated `{data, valid}` structs
  built by the pypeline.py-local `_make_autofsm_stream_t`. It is a deliberate
  twin of `include/pypeline/stream/stream.py`'s `make_stream_t` rather than an
  import of it: `pypeline.py` is the base module every design imports and keeps
  zero dependency on the `include/pypeline` library. The two are structurally
  identical and duck-type compatible.
- **`max_latency=`** is reserved for the planned latency cap and raises
  `NotImplementedError` rather than being accepted and ignored.
- **Native simulation** models the generated FSM's registers directly
  (`_sim_fsm`, keyed on `_SIM_AUTOFSM_STATE_KEY`), following the same
  committed-read / buffered-write discipline as `_sim_delay_line`.

Full design in [`AUTOFSM_DESIGN.md`](AUTOFSM_DESIGN.md).

### `MULTI_CYCLE[ncycles]` — Multi-Cycle Path Tag

Python equivalent of PipelineC's `#pragma MULTI_CYCLE <ncycles> <start_reg> <end_reg>`.
Unlike `PART(...)`, this is not a call at all — `MULTI_CYCLE` (like `AUTOPIPELINE`) is a
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

Unlike `AUTOPIPELINE(...)` (a callable tag for calls) or `MULTI_CYCLE[...]` (tags a `Reg[T]`
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
`@sim_output`'s `_is_sim_output` flag and `AUTOPIPELINE`'s `_is_autopipeline_pragma`
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
| `"INFERRED_MULT"` | `*` — not `"MULT"`/`"TIMES"`; `"MULT"` is a separate name the C frontend uses |
| `"DIV"` | `/` — not `"DIVIDE"` |
| `"SL"` | `<<` |
| `"SR"` | `>>` |
| `"NEGATE"` | `-` (unary) |

(`BIN_OP_MAP` in `PY_TO_LOGIC.py` is the source of truth mapping each `ast`
operator node type to its op string.)

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

**`_push_scoped_registrations(scope_key)`** merges scoped entries for `scope_key` into the
global registries and returns a save-list of `(registry, key, old_value)` triples for
restoration. **`scope_key` must be the exact object passed as `scope=...` at registration
time** — since `register_*(..., scope=my_func)` runs *after* `@hw_func` has already wrapped
`my_func`, that object is the wrapper, not the pre-decoration function. Every internal
caller inside `_sim_type_wrap` (both `_run_body`, shared by the two non-`SIM_RAW_INTS`
wrapper variants, and the two `SIM_RAW_INTS` wrapper variants' own inline push/pop) passes
its own `wrapper`, not the `fn` closure variable that same code also has in scope — passing
`fn` there is a bug that silently disables a function's own scoped registrations for every
call that isn't itself wrapped in an *outer* `sim_call(the_wrapper, ...)` (which pushes
using the correct object as an independent side effect), i.e. for any plain nested call
from inside another `@hw_func` body.

**`_pop_scoped_registrations(saved)`** restores the previous global registry state (dict
entries *and* fast-path set membership, see below) using that save-list.

**Performance:** `_scoped_funcs: set` tracks `id(func)` for any function that has ever had
a scoped registration. `_push_scoped_registrations` returns the module-level singleton
`_EMPTY_SAVED = []` immediately when `id(func) not in _scoped_funcs`, avoiding the dict
iteration entirely for the vast majority of functions.

**`_registered_binary_op_names`** and **`_registered_unary_op_names`** are module-level
sets that track which op names have at least one registration. `SimVal.__rshift__`,
`__lshift__`, `__neg__`, `__invert__` check these sets and skip dispatch entirely when no
registration exists — critical for performance in the common case (see
`pypeline_sim_DESIGN.md` performance section).

`register_operator` and `register_left_operator` add to `_registered_binary_op_names` when
`scope is None`. `register_unary_operator` adds to `_registered_unary_op_names` when `scope
is None`. For a *scoped* registration, `_push_scoped_registrations` provisionally adds the
op name to the relevant set too (recorded in the save-list as a `_SCOPED_SET_ADD`-tagged
entry, removed again on pop via `.discard()`, only if the name wasn't already present) —
without this, a scoped-only registration (the common case: a factory's own internal
NEGATE/SR/SL helpers, never registered globally) would never actually dispatch unless some
unrelated module happened to also hold a global registration for that same op name, purely
as an accidental side effect of the fast-path-set optimization.

### Struct-Type Operator Dispatch

The registries above are also consulted by `@struct`-decorated types directly, not just
`SimVal`: `struct()` gives every decorated class `__add__` / `__sub__` / `__mul__` /
`__truediv__` (bound to `_struct_dispatch_binary_op`) and `__neg__` (bound to
`_struct_dispatch_unary_op`), so `a + b` on two registered struct instances works the same
whether it's elaborated to hardware or executed as plain Python (`sim_call` or otherwise).
Unlike `SimVal`'s int fallback, there's no meaningful default for `+` on a struct with
nothing registered — an unregistered pair raises `TypeError` naming the op and both
ctypes, rather than falling through to `NamedTuple`'s tuple concatenation/repeat.

Both dispatch functions route through `_struct_dispatch_call(fn, args)`, which mirrors
`sim_call`'s own body (activate `_sim_active`, push `fn`'s scoped registrations, call, pop,
restore) for the looked-up impl. This matters because `_sim_type_wrap`'s wrapper only casts
arguments/return values and honors `Reg[T]` state (via its "AST-rewritten sim body", see
`PY_TO_LOGIC_DESIGN.md`) while `_sim_active` is already `True` — a bare `a + b` at module
scope, with no enclosing `sim_call`, would otherwise silently run the impl's raw,
un-rewritten source.

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

The other `BIT_MANIP_FUNC_NAMES` members (`bit_dup`, `rotl`, `rotr`, `bswap`, `bit_assign`,
`array_to_uint_be/le`, `uint_to_array_be/le`) are dual-mode the same way: each has a real
Python body in `pypeline.py` (shared width-inference via `_bit_manip_width`/
`_bit_manip_result_ctype`) whose bit-level semantics mirror the VHDL each one elaborates to
in `RAW_VHDL.py` (`x rol/ror n`, big/little-endian byte packing, etc.) — verified by direct
comparison against those VHDL code generators, not just re-derived independently.

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
        "vhdl(...) has no attached simulation model. ..."
    )
```

This means a function whose body is `vhdl(...)` elaborates to hardware normally, but
cannot be exercised through `sim_call()`/`pypeline_sim.py`/a direct call — doing so
raises `NotImplementedError` immediately, rather than silently returning a wrong value or
running real (but unrelated) Python code, as could happen if `vhdl` were missing
entirely (`NameError`) or aliased to something else. To simulate a `vhdl(...)`-bodied
function, attach a Python simulation model with `sim_model(target)` — either an
`@hw_func` delegate or an arbitrary Python class — which the wrapper then runs instead of
the body (see `pypeline_sim_DESIGN.md` → "`sim_model` — Python Simulation Models"; the
attached model is simulation-only and invisible to elaboration). See
`PY_TO_LOGIC_DESIGN.md` → "Raw VHDL Passthrough (`vhdl(...)`)" for the elaboration side,
including how the text argument is resolved via `_try_eval_const` (so it can be any
compile-time-computed Python string, not just a literal) and how it's stored on the
shared `Logic.vhdl_module_text` field (also used by the C frontend's `__vhdl__("...")`).

---

## Reference: `pypeline.py` Public API

| Name | Purpose |
|---|---|
| `uint1_t` … `uint64_t` | C unsigned integer types as real Python classes (`_CTypeMeta` metaclass) |
| `int1_t` … `int64_t` | C signed integer types |
| `make_uint_t(n)` | Dynamically creates `uintN_t` for arbitrary bit width `n` |
| `make_int_t(n)` | Dynamically creates `intN_t` for arbitrary bit width `n` |
| `NamedTuple` | Re-export of `typing.NamedTuple` |
| `@struct` | Adds `__class_getitem__`, stamps canonical `_pypeline_ctype_name`, wraps scalar fields in sim |
| `@MAIN` | Registers a function as a hardware entry point; implies `@hw_func`; appends to `_main_registry` |
| `@sim_output` | Marks a function as simulation output-only; no-op during convergence passes; executes in final pass per cycle |
| `sim_print(fstring_or_str)` | printf-style console output — same once-per-cycle firing as `@sim_output`, but *also* elaborates to a real VHDL `write(output, ...)` statement (see `PY_TO_LOGIC_DESIGN.md`) |
| `sim_assert(cond, msg=None)` | simulation-only condition check — raises `AssertionError` in native sim, elaborates to VHDL `assert ... report ... severity failure;` (see `PY_TO_LOGIC_DESIGN.md`) |
| `sim_finish()` | simulation-only stop signal — raises `SimFinish` in native sim (caught by `pypeline_sim.py`'s CLI run loop), elaborates to VHDL `std.env.finish;` (see `PY_TO_LOGIC_DESIGN.md`) |
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
| `array_to_uint_be/le`, `uint_to_array_be/le` | Array ↔ integer packing primitives (hardware + sim) |
| `concat(*args)` | Bit concatenation — works in hardware (→ `TUPLE_CONCAT`) and simulation (→ typed `SimVal`) |
| `BIT_MANIP_FUNC_NAMES` | Frozenset of function names intercepted as built-in bit manipulation by the elaborator |
| `vhdl(text)` | Raw VHDL passthrough — recognized structurally by name in `PY_TO_LOGIC._elab_stmt`, never called during elaboration; the real function only runs when called outside elaboration (directly, via `sim_call()`, or via `pypeline_sim.py`) and raises `NotImplementedError` unless a simulation model is attached via `sim_model` |
| `sim_model(target, copy_state=True)` | Attaches a Python simulation model to an `@hw_func`/`@MAIN` function (exactly one per target): an `@hw_func` delegate with matching signature, or a class/callable holding arbitrary per-instance state with Reg-like deepcopy-commit timing; sim-only, invisible to elaboration (see `pypeline_sim_DESIGN.md`) |
| `sim_zero(ctype)` | Returns a zero-initialized simulation value for any pypeline ctype (scalar/struct/array) — the same value `Reg[T]` uses for its reset default; a public wrapper around `_make_sim_zero` for `sim_model` authors needing a typed placeholder (e.g. an empty buffer/queue's output slot) |
| `_make_ctype(name)` | Dynamically creates C type class objects (used by `make_uint_t`, array subscript, etc.) |
| `SimVal` | Simulation typed integer: bit-slice `__getitem__`, operator dispatch, hardware-accurate arithmetic |
| `_RawField` | Raw-mode int subclass for struct fields: C-level arithmetic + `__getitem__` for bit slicing |
| `_sim_cast(val, ctype)` | Cast a Python int/SimVal to a pypeline ctype: mask to bit width, two's-complement sign |
| `_sim_val_make(v, ctype)` | Fast `SimVal` allocation bypassing Python `__new__`; checks flyweight cache first |
| `_SIM_CONST_CACHE` | Flyweight cache: `(int_value, ctype)` → `SimVal` for values 0–15 per ctype |
| `AUTOFSM(func)` | Tag object: implements a pure single-argument function as a resource-shared FSM; `.latency`, `.in_stream_t`, `.out_stream_t`; see AUTOFSM_DESIGN.md |
| `hw_func` | Decorator for inner hardware functions; adds sim-mode type casting and register state management |
| `hw_arg_types(func)` | Returns a hardware function's parameter types, in declaration order, as a tuple — reads through `__wrapped__`/`__annotations__` so it works on `@hw_func`-wrapped or plain functions alike |
| `hw_return_type(func)` | Returns a hardware function's declared return type — same unwrapping as `hw_arg_types` |
| `is_hw_func(func)` | Returns True if `func` is already `@hw_func`/`@MAIN`-decorated (checks the `_is_hw_func` marker `_sim_type_wrap` sets on its wrapper); used by factories (`make_autopipeline`, `make_valid_ready_mcp`, `make_stream_pipeline`) to validate a caller-supplied `func` before calling it from their own hardware function body |
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

## Tests

`src/tests/pypeline_tests/` exercises the type system, struct support, operator registry,
and elaboration paths described above against real `.py` design files in `inst/`. The suite
is split across three scripts, run together via `run_all.py`:

- **`native_sim_tests.py`** — plain `python3 <file>` simulation tests (no elaboration). See
  [pypeline_sim_DESIGN.md § Tests](pypeline_sim_DESIGN.md#tests) for what these cover.
- **`elab_tests.py`** / **`synth_tests.py`** — `pipelinec` elaboration and synthesis runs
  against the same design files. See
  [PY_TO_LOGIC_DESIGN.md § Tests](PY_TO_LOGIC_DESIGN.md#tests) for details.

The bidirectional-port mechanism `@interface`
(`include/pypeline/interface/interface.py`) reuses this module's compound-type introspection
(`_array_elem_ctype`/`_array_len`, `@struct` `_fields`/`__annotations__`) to split an interface
into its two one-directional structs, and `_enclosing_factory_param_suffix` to name generated
modules deterministically. It exposes no new pypeline.py API — the generated function is an
ordinary `@hw_func` + `@struct` pair, and `make_stream_t(data_t, feedback_t=uint1_t)` is now just
the feedforward half of `make_stream_interface(...)`. Library modules that carry backpressure
declare interface ports: `stream/stream_pipeline.py`, `stream/stream_fifo.py`,
`multi_cycle_path.py`, `dsp/`, and all of `axi/axis.py` (whose `make_axis_broadcast_interlock`
uses an *array* interface port for fan-out). `fifo.py`'s raw `make_fifo` deliberately does not —
its three loose signals are literally the wrapped VHDL entity's ports. See
[PY_TO_LOGIC_DESIGN.md § `@interface`](PY_TO_LOGIC_DESIGN.md#interface--generated-reverse-wiring)
and tests `inst/interface_test.py`, `inst/interface_func*_test.py`,
`inst/interface_boundary_test.py`, `inst/interface_array_port_test.py`,
`inst/interface_mixing_rules_test.py`.

```
python3 src/tests/pypeline_tests/run_all.py            # run everything, in parallel
python3 src/tests/pypeline_tests/run_all.py -j 4        # cap parallelism at 4 workers
python3 src/tests/pypeline_tests/run_all.py --category sim
```

These scripts replace the old `run_all.sh`: each test gets its own tmp output directory
(`common.py`'s `make_tmp_root()`/`run_test()`), tests run in parallel via a thread pool
(default worker count = `cpu_count() // 2`), and all paths are resolved relative to the
repository root (`common.REPO_ROOT`) rather than hardcoded — the suite runs unmodified on
any checkout. A summary table reports PASS/FAIL per test, with output directories of any
failed test printed for inspection. `native_sim_tests.py`, `elab_tests.py`, and `synth_tests.py`
can each also be run standalone.
