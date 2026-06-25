# Pypeline Simulation — Design Document

This document covers the simulation infrastructure for pypeline designs — both the
in-process sim layer embedded in `pypeline.py` (`@hw_func`, `sim_call`, `Reg[T]`/`Feedback[T]`
simulation, bit-accurate arithmetic) and the multi-MAIN CLI runner in `pypeline_sim.py`.
For the shared pypeline.py type system and `SimVal` foundations, see
[`pypeline_DESIGN.md`](pypeline_DESIGN.md). For the hardware elaborator, see
[`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md).

## Table of Contents

**In-Process Sim Layer (`pypeline.py`)**
- [Overview](#overview)
- [`_sim_cast(val, ctype)`](#_sim_castval-ctype)
- [`@hw_func` / `_sim_type_wrap` — Per-Function Type Propagation](#hw_func--_sim_type_wrap--per-function-type-propagation)
- [`_sim_active` Guard — Elaborator-Probing Protection](#_sim_active-guard--elaborator-probing-protection)
- [`sim_call(func, *args)` — Simulation Entry Point](#sim_callfunc-args--simulation-entry-point)
- [Bit-Accurate Arithmetic](#bit-accurate-arithmetic)
  - [`SIM_STRICT_ARITH` — Typed Arithmetic Promotion](#sim_strict_arith--typed-arithmetic-promotion)
  - [`_TypedAnnAssignRewriter` — Truncation at Every Typed Assignment](#_typedannassignrewriter--truncation-at-every-typed-assignment)
- [`_build_reg_sim_func` — AST Transformation at Decoration Time](#_build_reg_sim_func--ast-transformation-at-decoration-time)
- [`_GlobalWireRewriter` — Wire Read/Write Interception](#_globalwirerewriter--wire-readwrite-interception)
- [`Reg[T]` Simulation — Stateful Registers Across Clock Cycles](#regt-simulation--stateful-registers-across-clock-cycles)
- [`Feedback[T]` Simulation — Combinatorial Convergence](#feedbackt-simulation--combinatorial-convergence)

**Multi-MAIN Runner (`pypeline_sim.py`)**
- [`Wire[T]` / `Input[T]` / `Output[T]` Global Wire Simulation](#wiret--inputt--outputt-global-wire-simulation)
- [`pypeline_sim.py` — Multi-MAIN Clock-Cycle Simulation](#pypeline_simpy--multi-main-clock-cycle-simulation)
- [Simulation Modes](#simulation-modes)

**Reference**
- [Limitations](#limitations)
- [Simulation Performance — Hot Paths and Key Optimizations](#simulation-performance--hot-paths-and-key-optimizations)
- [Tests](#tests)

---

## Overview

Pypeline simulation has two layers:

**Layer 1 — In-process sim (`pypeline.py`):**
The `@hw_func` decorator (`_sim_type_wrap`) transforms hardware functions at decoration time
using AST rewriting (`_build_reg_sim_func`). This enables single-function simulation via
`sim_call(func, *args)`: registers are kept in `_sim_reg_state`, feedback wires converge
iteratively, and all arithmetic can be made bit-accurate via `SimVal` + `SIM_STRICT_ARITH`.

**Layer 2 — Multi-MAIN runner (`pypeline_sim.py`):**
Designs that use `Wire[T]` global signals require running multiple `@MAIN` functions
together. The `pypeline_sim.py` CLI handles this with a delta-cycle convergence queue and
atomic register commit timing to match hardware clock-edge semantics.

The two layers share state (`_sim_reg_state`, `_sim_wire_state`, `_sim_active`) and are
designed so that a design file's simulation behaviour is identical whether driven by
`sim_call` or `pypeline_sim.py`.

---

## `_sim_cast(val, ctype)`

Converts a Python `int` / `SimVal` to a typed `SimVal` with the correct hardware value:

1. Mask to `len(ctype)` bits (implements unsigned wrap-on-overflow)
2. Two's-complement sign extension for signed types (`int…_t`)
3. Set `_ctype` to `ctype`

**Enum types:** `_sim_cast_params(ctype)` checks `getattr(ctype, "_pypeline_is_enum", False)`
first and computes `(mask, sign_bit=0, is_signed=False)` from `_enum_bit_width(ctype)` —
the minimum bit width derived from the largest member value.  This path is hit for
`@enum`-decorated `IntEnum` types.  Since `IntEnum` members are int subclasses (`isinstance(m,
int)` is True), `_run_body` in `_sim_type_wrap` casts them correctly without any special
casing beyond the `_sim_cast_params` update.

**Identity fast-path:** if `type(val) is SimVal and val._ctype is ctype`, return `val`
immediately with no work.

**Pre-computed parameters:** `_sim_cast_param_cache: dict` caches `(mask, sign_bit, is_signed)`
per ctype. Populated lazily by `_sim_type_init(ctype)` on first use; inline `try/except KeyError`
avoids the per-hit overhead of an `lru_cache` function call frame.

**Three call sites:**
1. By `@hw_func` / `_sim_type_wrap` to cast function inputs and outputs at call boundaries.
2. By `SimVal._dispatch_unary`/`_dispatch_binary` as a fallback when a dispatched function
   returns an untyped value.
3. By `_TypedAnnAssignRewriter`-generated code to truncate typed local variable assignments
   inside `@hw_func` bodies.

---

## `@hw_func` / `_sim_type_wrap` — Per-Function Type Propagation

The `@hw_func` decorator (`hw_func` is an alias for `_sim_type_wrap`) wraps a pypeline
hardware function to propagate type information through the simulation call graph.

At **decoration time**, `_sim_type_wrap` calls `_build_reg_sim_func(fn)`. Based on whether
the function contains `Reg[T]`/`Feedback[T]` (the `has_state` flag), one of two (or three
in raw mode) wrapper variants is emitted:

### `has_state=False` — Fast Combinational Path

No register state; no instance tracking needed:

```python
def wrapper(*args, **kwargs):
    if not _sim_active:
        return fn(*args, **kwargs)   # elaborator probe → fall through to raw fn
    saved = _push_scoped_registrations(original_fn)
    try:
        cast_args = [_sim_cast(a, pt) for a, pt in zip(args, param_types) if scalar]
        result = sim_body_fn(*cast_args, **kwargs)
        return _sim_cast(result, return_type) if scalar_return else result
    finally:
        _pop_scoped_registrations(saved)
```

Skips `sys._getframe`, `_sim_inst_stack` push/pop, and `co_positions()` entirely (~1.7 s
saved on the VGA donut benchmark).

### `has_state=True` — State-Aware Path

Functions with `Reg[T]` or `Feedback[T]` must push to `_sim_inst_stack` for correct
per-instance register state tracking:

```python
def wrapper(*args, **kwargs):
    if not _sim_active:
        raise TypeError(f"{fn.__qualname__!r} has Reg[T]/Feedback[T] and "
                        f"cannot be called outside sim_call()")
    frame = sys._getframe(1)
    call_loc = (frame.f_code.co_filename, frame.f_lineno, ...)
    _sim_inst_stack.append((fn.__qualname__, call_loc))
    saved = _push_scoped_registrations(original_fn)
    try:
        ...cast and call sim_body_fn...
    finally:
        _pop_scoped_registrations(saved)
        _sim_inst_stack.pop()
```

`SIM_TRACE_LOCATIONS=False` (default): captures only `(filename, lineno)` — sufficient to
distinguish two calls to the same function on different source lines.

`SIM_TRACE_LOCATIONS=True`: uses `frame.f_code.co_positions()` to capture column offsets
(Python 3.11+), enabling disambiguation of two calls on the same line. The `co_positions()`
call is expensive (allocates per-bytecode tuples) so it is off by default.

### Hardware Transparency

`_elaborate_live_func` calls `inspect.unwrap(func)` before `inspect.getsource` and closure
extraction, so `@hw_func`-wrapped functions elaborate from the original source code, not the
wrapper body. Elaboration uses `func_for_source.__globals__` (the unwrapped function's
imports) rather than the wrapper's globals in `pypeline.py`.

**`functools.wraps`** preserves `__name__`, `__annotations__`, and merges `__dict__`, so
custom attributes like `clz.out_t` or `shifter_SL.amount_t` survive wrapping.

### Usage in Factory Functions

```python
def make_negate(value_t, out_t):
    @hw_func
    def negate(a: value_t) -> out_t:
        a_signed: out_t = a
        return ~a_signed + 1
    return negate

def make_clz(value_t):
    n_bits = len(value_t)
    out_t = make_uint_t(n_bits.bit_length())
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

---

## `_sim_active` Guard — Elaborator-Probing Protection

`_sim_active` is `False` by default. It is set to `True` in two places:

- `pypeline_sim.py` sets `pypeline._sim_active = True` before the first clock cycle.
- `sim_call` sets `_sim_active = True` for the duration of each call.

The hardware elaborator never calls `sim_call` and never sets this flag.

**Why it's needed:** `_elab_assign` calls `_try_eval_const(stmt.value)` on every assignment
RHS to test whether it is a plain Python constant. `_try_eval_const` evaluates the
expression in `{**module_globals, **const_env}` — which includes live callables like
`vga_timing`. Without the guard, the elaborator would probe `vga_timing()`, the wrapper
would run the simulation body, return a concrete `vga_timing_signals_t`, and `_try_eval_const`
would cache it as a constant — causing an elaboration error later when hardware wires derived
from it are not in `self.env`.

**`has_state` split:**

- **`has_state=False`** (pure combinational): `if not _sim_active: return fn(*args)` — the raw
  function body is called. This is intentional: a pure function called by the elaborator may
  return a useful constant (used as compound init), or raise `NameError`/`TypeError` from
  touching a hardware wire (causing `_try_eval_const` to return `None`).

- **`has_state=True`** (has `Reg[T]` or `Feedback[T]`): `if not _sim_active: raise TypeError(...)`.
  An explicit error is raised rather than calling `fn()`. The reason: `Reg[T] = init_val`
  syntax is a Python annotated assignment **with a value**, which Python executes
  unconditionally — `h_cntr` would be bound to `H_START` in the local scope. Calling the
  raw function body would **succeed** and return a real value, causing `_try_eval_const`
  to cache it as a constant and bypass hardware elaboration.

---

## `sim_call(func, *args)` — Simulation Entry Point

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

Sets `_sim_active = True` so `@hw_func` wrappers with `has_state=True` run their sim bodies
rather than raising `TypeError`. Pushes scoped operator registrations keyed on `id(func)` so
that custom operators (e.g. float adder) are active during the call.

**Key design choice:** `func` is used directly (not `inspect.unwrap`) to look up scoped
registrations. When `@hw_func` is applied to `float_add`, scoped operators are registered
under `id(wrapped_float_add)` (since `scope=float_add` refers to the wrapped name). Using
`func` as-is ensures the correct `id` is used.

`sim_reset()` clears all `_sim_reg_state` and `_sim_wire_state`. After the reset, each
`_sim_reg_read` returns the per-register `default` — the declared init value (which may be
non-zero from `Reg[T] = val`) or zero when no initializer was given. This models hardware
power-on reset that applies VHDL signal initial values.

---

## Bit-Accurate Arithmetic

Python's arbitrary-precision integers cause two classes of hardware divergence:

1. **Arithmetic overflow** — `int16_t(20000) + int16_t(20000)` produces `40000` in Python
   but wraps to `-25536` in hardware (int17_t intermediate, truncated to int16_t).
2. **Typed-assignment truncation** — `vxi14: int16_t = big_expr` is a no-op Python type
   hint; hardware truncates `big_expr` to 16 bits at that assignment.

Two complementary mechanisms close these gaps:

### `SIM_STRICT_ARITH` — Typed Arithmetic Promotion

When `SIM_STRICT_ARITH = True` (default), `SimVal.__add__`, `__sub__`, and `__mul__` apply
hardware type-promotion when **both** operands carry a known `_ctype`. The masking is inlined
in each operator (no extra `_sim_cast` call):

```python
# int16_t + int16_t:
SimVal(20000, int16_t) + SimVal(20000, int16_t)
# → _arith_output_ctype("add", int16_t, int16_t, ...) → int17_t
# → result & mask → 40000 & 0x1FFFF = 40000; no sign flip (< sign_bit)
# → SimVal(40000, int17_t)

# int16_t * int16_t:
SimVal(-25536, int16_t) * SimVal(-25536, int16_t)
# → _arith_output_ctype("mul", ...) → int32_t
# → SimVal(652_087_296, int32_t)
```

`_arith_promote` and `_arith_output_ctype` are defined in `pypeline.py` and shared with the
elaborator (see `pypeline_DESIGN.md`).

**When strict arith doesn't fire:** if either operand has no `_ctype` (plain int literal,
shift result, `__radd__`/`__rsub__` where left is plain int), the result is a bare `SimVal`
with no `_ctype`. Chain integrity requires typed operands on both sides; `@hw_func` input
casts and `_TypedAnnAssignRewriter` re-inject ctypes at assignment points.

Set `pypeline.SIM_STRICT_ARITH = False` to disable (useful for performance testing).

### `_TypedAnnAssignRewriter` — Truncation at Every Typed Assignment

An `ast.NodeTransformer` applied by `_build_reg_sim_func` to the function body AST.
Applies two rewrite rules:

**Rule 1 — Annotated assignment** (`AnnAssign` with value, scalar int type):
```python
var: uint16_t = expr    →    var = _sim_cast(expr, uint16_t)
```

**Rule 2 — Plain re-assignment to a previously-declared typed variable** (`Assign` node
where `var` was declared with a scalar integer annotation earlier in the same function):
```python
var = expr    →    var = _sim_cast(expr, declared_type)
```

Rule 2 covers loop-body re-assignments like `t = t + d` where `t: int16_t` was declared
earlier — matching hardware where a signal's type is fixed at declaration and every write
truncates. Bare declarations (`var: T` with no RHS) register `var`'s type for Rule 2 without
generating an assignment.

The rewriter traverses the entire function body recursively; `_declared_types` is populated
top-to-bottom so declarations always precede uses in well-structured hardware code.

`__sim_ann_{lineno}_{col_offset}__` is a unique name per rewrite site; the ctype object is
injected into the compiled function's `__globals__` at decoration time.

**Rule 3 — Bare struct/array local declarations** (`AnnAssign`, no value, compound type):

```python
rv: my_struct_t    →    rv = _make_sim_zero(my_struct_t)
rv: keep_t          →    rv = _make_sim_zero(keep_t)        # keep_t = uint1_t[n]
```

A bare struct or array declaration with no value binds no name in plain Python (`x: T`
alone is annotation-only), so the canonical PipelineC idiom carried over into pypeline —
`rv: T` then field/index writes — raised `UnboundLocalError` on first use under simulation,
even though the same source elaborates fine through the real AST elaborator
(`PY_TO_LOGIC.py`, which has no such gap; see [`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md)).
Rule 3 closes that gap by zero-initializing the variable, exactly mirroring how `Reg[T]`
bare declarations are zero-initialized (see [`Reg[T]` Simulation](#regt-simulation--stateful-registers-across-clock-cycles)
below). `var: T = value` (an initializer already present) needs no rewrite — plain Python
already binds the name — but the variable is still tracked (see Rule 4).

`_is_compound_pypeline_type(ctype)` distinguishes struct (`hasattr(ctype, "_fields")`) and
array (`hasattr(ctype, "_ctype_name") and "[" in ctype._ctype_name`) annotations from
`Wire[T]`/`Input[T]`/`Output[T]` descriptor objects, none of which carry either attribute, so
those continue to fall through to their own dedicated handling untouched. `Reg[T]`/`Feedback[T]`
are also wrapper objects with neither attribute, but their `inner_ctype` is checked separately —
see Rule 3b below — so a compound-typed register/feedback wire is tracked too.

**Rule 3b — `Reg[T]`/`Feedback[T]` locals where `T` is compound** (`AnnAssign`, annotation
evaluates to a `_RegType`/`_FeedbackType` instance whose `inner_ctype` is a struct/array):

```python
reg: Reg[my_struct_t]              # tracked in _compound_declared; AnnAssign left untouched
reg.field = expr                   # → reg = _sim_lens_set(reg, ["field"], expr)   (Rule 4)
```

`ann_val` for a `Reg[T]`/`Feedback[T]` annotation is the wrapper object itself (`_RegType`/
`_FeedbackType`), not `T` — so `_is_compound_pypeline_type(ann_val)` (Rule 3's check) is always
`False` for these, even when `T` is a struct/array. Rule 3b checks `ann_val.inner_ctype` instead:
when it's compound, the variable name is added to `_compound_declared` exactly as Rule 3 does,
but **the `AnnAssign` node itself is left untouched** — `reg`'s read/zero-init is handled
separately by `_build_reg_sim_func` step 6 below (`_sim_reg_read`/`__reg_zero_<name>__`), not by
`_make_sim_zero` at the rewrite site. The only effect of Rule 3b is making Rule 4 fire for nested
writes through `reg`.

Before this rule existed, `reg.field = expr` (any nesting depth, scalar **or** array-typed field)
fell through untouched, then ran as plain Python attribute assignment on the immutable
`NamedTuple` returned by `_sim_reg_read` — raising `AttributeError: can't set attribute` at
runtime. Single-element index writes on an already-reachable list (`reg.arr[i] = x`) never hit
this gap, since mutating a list in place needs no `NamedTuple.__setattr__` call — which made the
bug easy to miss until a whole-field write (`reg.arr = [...]`) was attempted. The
`PY_TO_LOGIC.py` elaborator has an analogous gap for the same `obj.field = [...]` pattern; see
[`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md#compound-initializer-syntax).

**Rule 4 — Partial writes to a tracked compound local** (`Assign` with an `Attribute` or
`Subscript` target, chain rooted at a name from Rule 3 or 3b):

```python
rv.field = expr        →    rv = _sim_lens_set(rv, ["field"], expr)
rv.dim[i] = expr        →    rv = _sim_lens_set(rv, ["dim", i], expr)
```

Structs are immutable `NamedTuple`s (see [Struct Support](pypeline_DESIGN.md#struct-support)
in `pypeline_DESIGN.md`), so `rv.field = expr` cannot mutate in place — it must rebuild `rv`
via `rv._replace(field=...)`. `_sim_lens_set` (below) does this generically for arbitrarily
nested `.field`/`[i]` chains, rewritten by walking the assignment target's `Attribute`/
`Subscript` chain back to its root `Name` (`_chain_to_path`). Only chains rooted at a name
tracked by Rule 3/3b are rewritten — an untracked object's `.attr = x` is left as plain Python
attribute assignment, so arbitrary non-Pypeline objects used as locals are unaffected.

**Leaf-ctype casting (`_sim_cast_deep`):** `_compound_declared` stores the root variable's
*ctype*, not just a membership flag, specifically so Rule 4 can resolve the statically-known
type of the leaf being written. `_chain_to_path` returns a parallel `kinds` list alongside the
runtime path nodes — `('attr', field_name)` for each `.field` step (the name is already a
plain Python string on the AST node, no eval needed) and `('idx', None)` for each `[i]` step
(the index value is irrelevant to the type, since every element of an array shares one
declared ctype). `_resolve_leaf_ctype(root_ctype, kinds)` walks `root_ctype` through `kinds` —
`'attr'` steps look up `ctype.__annotations__[field_name]`; `'idx'` steps move to
`_array_elem_ctype(ctype)` (the same `_elem_ctype`-preferred / `_ctype_name`-suffix-stripping
helper `_make_sim_zero` uses below) — returning `None` if it can't resolve (defensive: falls
back to the old uncast behavior rather than erroring). When a leaf ctype *is* resolved, the
rewriter wraps `node.value` in `_sim_cast_deep(value, leaf_ctype)` before it reaches
`_sim_lens_set`:

```python
rv.field = expr        →    rv = _sim_lens_set(rv, ["field"], _sim_cast_deep(expr, field_ctype))
wide_reg.frag.keep = [0]*n  →  wide_reg = _sim_lens_set(wide_reg, ["frag", "keep"],
                                              _sim_cast_deep([0]*n, uint1_t_n_ctype))
```

Without this, a value with no `_ctype` flowing through a partial write — a raw Python list
literal (`wide_reg.frag.keep = [0,0,1,1]`), or a read of an already-untyped element elsewhere
— stayed an untyped plain `int`/`list` indefinitely, since `_sim_lens_set` itself just stores
whatever it's given. Plain-int bitwise ops then silently diverge from hardware: Python
`~0 == -1` and `~1 == -2` are **both truthy**, so an `if ~field:` idiom on an untyped 1-bit
value was always-true regardless of the real bit — a real (non-cosmetic) correctness bug,
not just a typing nicety, since it breaks the extremely common
`valid_or_ready: uint1_t = ~some.field` hardware pattern. Found while building `dwidth_widen`/
`dwidth_narrow` in `include/pypeline/axi/axis.py`, where `chunks[c].valid = wide.frag.keep[...]`
(reading an array-of-scalar `keep` field) and `wide_out_reg.data.frag.keep = [0] * wide_n`
(writing one) both fed an `if ~chunks[0].valid:` realignment loop.

### `_sim_cast_deep(value, ctype)` — Typed Casting Through Arrays

```python
def _sim_cast_deep(value, ctype):
    if hasattr(ctype, "_fields"):
        return value                                    # struct: self-types via _typed_new
    elem_ctype = _array_elem_ctype(ctype)
    if elem_ctype is not None:
        return [_sim_cast_deep(v, elem_ctype) for v in value]   # array: recurse per element
    return _sim_cast(value, ctype)                       # scalar: mask/sign-extend
```

Used by Rule 4 above (with a statically-resolved leaf ctype) and conceptually mirrors what
`_typed_new` does for struct constructor kwargs (see
[Struct Support](pypeline_DESIGN.md#struct-support) in `pypeline_DESIGN.md`) — both now
recurse through array-of-scalar values element-wise rather than only handling top-level
scalars. Struct-typed values are passed through unchanged: a struct instance reaching this
point either already went through its own `_typed_new` (already typed) or isn't a pypeline
value at all, so no further action is needed at this level.

`_array_elem_ctype(ctype)` (a small shared helper, also used by `_make_sim_zero` below) returns
an array ctype's element ctype — preferring `_elem_ctype` (set at array-type-creation time,
see [C Type System](pypeline_DESIGN.md#c-type-system) in `pypeline_DESIGN.md`) over re-deriving
it from `_ctype_name`'s trailing `[N]` — or `None` if `ctype` isn't an array.

**What is NOT rewritten:**
- `Wire[T]`, `Input[T]`, `Output[T]` descriptor annotations, and `Reg[T]`/`Feedback[T]` whose
  inner type is scalar (a bare `reg = expr` reassignment has no nested chain to rewrite)
- Tuple-unpack targets: `a, b = f()`
- Whole-variable reassignment of a compound local (`rv = some_full_value`) — no cast or
  lens rewrite applies; plain Python rebinding is already correct
- Global wire `AnnAssign` nodes (already converted to `Expr(Call)` by `_GlobalWireRewriter`)

**`@hw_func` is required.** The rewriter runs at decoration time inside `_build_reg_sim_func`,
itself only invoked from inside the wrapper `_sim_type_wrap` builds. `sim_call(func, ...)`
calls `func(*args, **kwargs)` directly with **no** wrapping, so an undecorated function —
including one called as a plain nested call from inside another hardware function's body —
never goes through this rewriter at all, regardless of whether its body needs Rule 1-4. Inner
hardware functions (including `make_*` factory-produced ones) must carry `@hw_func` to opt in.

**`is_hw_func(func)` — validating caller-supplied functions at factory entry.** Factories
that accept a caller-supplied `func` and then *call* it from inside their own `@hw_func`
body — `make_autopipeline`, `make_valid_ready_mcp`, `make_stream_pipeline` — must have
`func` itself already `@hw_func`-decorated, or `func`'s own `Reg[T]`/`Feedback[T]`/bare
struct-array locals silently fall through the gap above and raise `UnboundLocalError`
deep inside `sim_call` (a confusing failure far from its cause). `_sim_type_wrap`/`hw_func`
sets `wrapper._is_hw_func = True` on the wrapper it returns; `is_hw_func(func)` reads that
marker (`pypeline.py`, next to `hw_arg_types`/`hw_return_type`). Each of these three
factories calls `is_hw_func(func)` right after its `hw_arg_types`/`hw_return_type`
introspection and raises `TypeError` immediately if it's `False`, surfacing the problem at
the factory call site (elaboration/import time) instead of inside a later `sim_call`.

This was deliberately chosen over having the factories silently call `hw_func(func)`
themselves when `func` isn't yet decorated: `_sim_type_wrap`'s closure-variable resolution
(`_build_reg_sim_func`, see the "Closure Variable Caveat" above) reads
`fn.__code__.co_freevars`/`fn.__closure__` directly off whatever is passed in, without
unwrapping first — wrapping an already-`@hw_func`-decorated function a second time would
resolve closure variables off the *wrapper's own* closure instead of the original
function's, silently breaking any `Reg[T, X]`-style annotation that depends on a closure
variable. Requiring explicit decoration up front avoids that risk entirely and matches
the existing convention (`make_negate`/`make_clz` factory examples above) of writing
`@hw_func` on every inner hardware function definition.

**Combined effect:** with all four rules active, simulation accurately models hardware at
every typed arithmetic operation, every typed scalar variable assignment, AND the canonical
bare-declare-then-fill idiom for structs and arrays — including loop-body re-assignments
that lack an explicit type annotation.

### `_sim_lens_set(obj, path, value)` — Immutable-Aware Deep Set

A small free function (not part of the rewriter class) used by the code Rule 4 generates:

```python
def _sim_lens_set(obj, path, value):
    if not path:
        return value
    head, rest = path[0], path[1:]
    if isinstance(head, str):                     # struct field
        child = getattr(obj, head)
        return obj._replace(**{head: _sim_lens_set(child, rest, value)})
    new_list = list(obj)                            # array index
    new_list[int(head)] = _sim_lens_set(new_list[int(head)], rest, value)
    return new_list
```

`path` is a list of field-name strings (`.field`) or indices (`[i]`), root-to-leaf order,
covering arbitrarily nested chains (`rv.a[i].b = x`, `rv[i].field = x`) with no special-casing
per shape: structs reconstruct via `_replace` at each level, arrays copy-and-set via `list(obj)`.
Each call returns a new top-level value; the rewritten `Assign` rebinds the root variable name
to it, matching the existing per-statement alias semantics the rest of the simulator already
uses for hardware variables.

---

## `_build_reg_sim_func` — AST Transformation at Decoration Time

Called once when `@hw_func` (or `@MAIN`) is applied to a function. Builds a transformed
function body and compiles it via `exec`. Returns `(transformed_fn_or_None, has_state)`.

**7-step pipeline:**

1. **Retrieve source** — `inspect.getsourcelines(inspect.unwrap(fn))` + `textwrap.dedent` to
   normalize indentation. Unlike plain `getsource`, `getsourcelines` also returns the function's
   real starting line number in its file; `ast.increment_lineno(tree, first_lineno - 1)` is
   applied right after parsing (step 2) to shift every node's `lineno` to match — see
   [Traceback Line Numbers](#traceback-line-numbers) below.

2. **Parse** — `ast.parse` + find the top-level `FunctionDef`.

3. **Discover global wire names** — scan `fn.__globals__['__annotations__']` for
   `Wire[T]`/`Input[T]`/`Output[T]` names. Also scan all module objects in `fn.__globals__`
   for cross-module wires (`module_wire_attrs` dict for `board_vga.vga_pmod`-style accesses).

4. **Apply `_GlobalWireRewriter`** — rewrites all wire reads/writes in the function body to
   `_sim_wire_read(name)` / `_sim_wire_write(name, value)` calls.

5. **Apply `_TypedAnnAssignRewriter`** — rewrites typed local variable assignments (two rules
   above). Skipped entirely when `SIM_RAW_INTS=True`.

6. **Detect `Reg[T]`/`Feedback[T]`** — walks the (now rewritten) body in source order,
   evaluating each `AnnAssign` annotation node against `_eval_ns` = `fn.__globals__` +
   closure variables (the only way to detect `_RegType`/`_FeedbackType` without running the
   hardware elaborator, since Python never stores local annotations in `fn.__annotations__`).
   For `Reg[T]` nodes with an init expression, evaluates the init to get the
   `__reg_init_<name>__` default.

   `_eval_ns` alone can't resolve annotations that reference a **local** assigned earlier in
   the same body — e.g. `MC = MULTI_CYCLE[32]` then `data0: Reg[my_struct_t, MC.start]`: `MC`
   is a per-call local, not a module global or closure variable, so a bare `eval(..., _eval_ns)`
   raises `NameError` and the register would be silently skipped (`has_state` would come back
   `False`, leaving the same `UnboundLocalError` Rule 3 above fixes for bare struct/array
   locals — but for the register itself). The walk accumulates a `_local_const_ns` dict in
   parallel: for every plain `Assign` to a single `Name` target encountered before the current
   statement, it tries to eval the RHS against `{**_eval_ns, **_local_const_ns}` and stores the
   result on success (silently skipped on failure — most RHS expressions reference hardware
   wires and can't evaluate as plain Python, same as the elaborator's `const_env`/
   `_try_eval_const` in `PY_TO_LOGIC.py`). Each `AnnAssign` annotation is then evaluated
   against the merged `{**_eval_ns, **_local_const_ns}` namespace instead of `_eval_ns` alone.

7. **If no Reg/Feedback/wires found and no typed-rewriter changes:** return `(None, False)`,
   meaning the original undecorated `fn` runs as-is. "No typed-rewriter changes" means
   `ann_ctypes_out` is empty (Rule 1/2 scalar casts) **and** `_typed_rewriter.modified` is
   `False` (Rule 3/4 compound zero-init/lens rewrites — tracked separately since Rule 4 lens
   rewrites don't add to `ann_ctypes_out`, having no ctype to inject). Otherwise build the
   **transformed function body** (see below), compile via `exec` into a new globals dict
   (which must also expose `_make_sim_zero`/`_sim_lens_set` alongside `_sim_cast` and the
   register/wire helpers for Rule 3/4's generated calls to resolve), and return
   `(sim_body_fn, has_state)`.

### Transformed Function Body Pattern

**Registers + Feedback:**

```python
def accum_func(data_in: uint32_t) -> uint32_t:
    __ip__ = _sim_current_inst_path()
    acc = _sim_reg_read(__ip__, "acc", __reg_init_acc__)   # init default injected
    f = 0                                                   # feedback zero-init
    __fb_iters = 0
    try:
        while True:    # only present if Feedback[T] exists
            __fb_iters += 1
            if __fb_iters > _SIM_FEEDBACK_MAX_ITER: raise RuntimeError(...)
            __reg_init_acc_snap = acc   # for per-iteration reset
            __fb_snap_f = f
            # original body (Reg/Feedback AnnAssign nodes removed):
            acc = acc + data_in
            f = acc & 1
            if acc == __fb_snap_f: break
    finally:
        _sim_reg_write(__ip__, "acc", acc)
    return acc
```

Decorator nodes are stripped before `compile`/`exec` to prevent re-wrapping. The compiled
function's `__globals__` is a copy of `fn.__globals__` augmented with the sim helpers and
per-register defaults. Closure variables are merged in via `fn.__code__.co_freevars` /
`fn.__closure__`.

### Closure Variable Caveat

Python only captures a name in `fn.__closure__` if it appears in the function *body*.
Annotation-only uses (`a: value_t`, `def f(a: value_t)`) are not captured. Fix: before
`exec`, cross-reference parameter annotation `Name` nodes against `orig_fn.__annotations__`
(already-evaluated type objects keyed by parameter name) and inject any missing names into
`new_globals`. This is safe because `__annotations__` holds resolved objects, not source strings.

### Traceback Line Numbers

`compile(tree, src_file, "exec")` (step 7) passes the **real** file path as `src_file`, so that
errors raised from the exec'd body show real, navigable file/line references rather than a
synthetic name. But `ast.parse` numbers any standalone source snippet starting from line 1,
regardless of where in the real file that snippet actually starts — and `inspect.getsource`
returns only the function's own snippet. Left uncorrected, a node at snippet-line 3 (say) would
be compiled with `lineno=3`, then an exception there would print a traceback pointing at line 3
of the *real* file — typically an unrelated `import` or `sys.path.insert` near the top — not the
line that actually failed.

Step 1 uses `inspect.getsourcelines` instead of `inspect.getsource` to additionally capture
`first_lineno` (the snippet's real starting line), and step 2 applies
`ast.increment_lineno(tree, first_lineno - 1)` immediately after parsing — before any further
rewriting — so every node's `lineno` (original statements and anything `copy_location`d from
them) matches its true position in the real file. New synthetic statements introduced later
(register read/write boilerplate, etc.) inherit a correct `lineno` too, via
`ast.fix_missing_locations` copying down from the now-correctly-numbered `FunctionDef`.

---

## `_GlobalWireRewriter` — Wire Read/Write Interception

An `ast.NodeTransformer` applied as step 4 of `_build_reg_sim_func`. Rewrites all accesses
to module-level `Wire[T]`/`Input[T]`/`Output[T]` names to call the sim wire state helpers:

| Original AST | Transformed AST |
|---|---|
| `Name(id='wire', ctx=Load)` | `_sim_wire_read('wire')` |
| `wire = expr` (Assign) | `_sim_wire_write('wire', expr)` (Expr stmt, no local binding) |
| `wire: T = expr` (AnnAssign with value) | `_sim_wire_write('wire', expr)` |
| `module_alias.wire` (Attribute, Load) | `_sim_wire_read('wire')` |
| `module_alias.wire = expr` (Attribute, Store) | `_sim_wire_write('wire', expr)` |

Module-level wire declarations (`wire: Wire[T]` with no value) are `AnnAssign` nodes with
`value=None` and are left untouched.

For cross-module wire access (`board_vga.vga_pmod = ...`), `_build_reg_sim_func` also scans
all module objects in `fn.__globals__` for `Wire[T]`/`Input[T]`/`Output[T]` annotations and
builds a `module_wire_attrs` dict `{(alias_name, attr_name): bare_wire_name}`. This is passed
to `_GlobalWireRewriter` alongside the bare `global_wire_names` set.

---

## `Reg[T]` Simulation — Stateful Registers Across Clock Cycles

Two problems must be solved:

**Problem 1 — `NameError` before assignment.** `acc: Reg[uint32_t]` inside a function body
is an annotation-only statement and creates no local variable. Any subsequent read of `acc`
raises `NameError`.

**Problem 2 — Multiple hardware instances.** Each call site of `accum_func` is a distinct
flip-flop in hardware. The simulator must route reads/writes to the correct per-instance copy.

Both are solved by **`_build_reg_sim_func`** + the **instance path stack** in `_sim_type_wrap`.

### Instance Path Stack

`_sim_inst_stack` is a module-level list. Each `@hw_func`/`@MAIN` wrapper pushes
`(func_qualname, (filename, lineno, col_offset, end_col_offset))` before calling and pops in
`finally`. The `call_loc` tuple is read from the **caller's** frame (`sys._getframe(1)`) so
that two calls to the same function at different source lines produce different entries —
exactly as the hardware elaborator produces distinct instance names from `_loc_str`.

`_sim_current_inst_path()` returns `tuple(_sim_inst_stack)` — an immutable snapshot used
as the dict key for register state.

### Per-Instance Register State

```python
_sim_reg_state: dict[tuple, dict[str, object]]
# _sim_reg_state[inst_path][reg_name] = current value
```

Three helpers:

```python
def _sim_reg_read(inst_path, reg_name, default=0): ...
# Returns stored value, or `default` if never written.
# default = _make_sim_zero(inner_ctype) (no init) or evaluated init expression.

def _sim_reg_write(inst_path, reg_name, value): ...
# Stores value as-is — struct/array instances preserved without int() coercion.

def _make_sim_zero(ctype): ...
# a typed zero SimVal (_sim_cast(0, ctype)) for scalar; recursively zero-initialised
# NamedTuple for @struct types; recursively zero-initialised list for array types (each
# element zeroed the same way, so arrays of structs and multi-dimensional arrays both work).
```

Array element type resolution (`_array_elem_ctype`, also used by `_sim_cast_deep` above)
prefers `ctype._elem_ctype` (set by `_CTypeMeta.__getitem__` / `_struct_class_getitem` at
array-type-creation time — see [C Type System](pypeline_DESIGN.md#c-type-system) in
`pypeline_DESIGN.md`) over re-deriving it by stripping the trailing `[N]` from
`ctype._ctype_name`: the string-only path can't recover a struct element type's field layout,
only its name, so `_elem_ctype` is what makes `point_t[10]` zero-initialize to ten real
zero-valued `point_t` instances rather than ten bare `0`s. The string-derived fallback remains
for array ctypes built without `__getitem__`.

**Scalar leaf typing:** the scalar fallback returns `_sim_cast(0, ctype)` — a properly typed
`SimVal` — rather than a bare Python `0`. This matters most for **arrays of scalar ints**
(e.g. `keep: uint1_t[n]`): a struct field's scalar zero gets retyped anyway when the recursive
call's result is passed through the struct's own constructor (`_typed_new` wraps it — see
[Struct Support](pypeline_DESIGN.md#struct-support) in `pypeline_DESIGN.md`), but a *list*
built by the array branch here has no constructor to route through, so each element needed to
already be typed coming out of the recursive `_make_sim_zero(elem_ctype)` call. Before this
fix, `_make_sim_zero(uint1_t[4])` produced `[0, 0, 0, 0]` with every element a plain `int` —
combined with the Rule 4 gap above, this was the root cause of `if ~chunks[0].valid:`-style
conditionals always evaluating true regardless of the real bit (Python `~0`/`~1` are both
truthy on plain ints; only a 1-bit-masked `SimVal` alternates correctly).

`_make_sim_zero` is also used directly by `_TypedAnnAssignRewriter` Rule 3 (above) to
zero-initialize bare struct/array **local variables**, not just `Reg[T]` defaults — the two
share one implementation since both need the same "default value for this ctype" behavior.

`sim_reset()` clears `_sim_reg_state`. The first `_sim_reg_read` after reset returns the
per-register default — the declared init value (non-zero when `Reg[T] = val`) or zero.

### Multi-Instance Trace Example

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
        rv = accum_func(data_in)  # line 71 → instance 1
    else:
        rv = accum_func(data_in)  # line 73 → instance 0
    return rv
```

```
sim_reset()
sim_call(regs_multi_inst, sel=1, data_in=1)
  → inst_path includes (accum_func, (test.py, 71, …)) → acc reads 0 → writes 1
sim_call(regs_multi_inst, sel=0, data_in=1)
  → inst_path includes (accum_func, (test.py, 73, …)) → acc reads 0 → writes 1  (different instance!)
sim_call(regs_multi_inst, sel=1, data_in=1)
  → inst_path includes (accum_func, (test.py, 71, …)) → acc reads 1 → writes 2  ✓
```

---

## `Feedback[T]` Simulation — Combinatorial Convergence

Functions with `Feedback[T]` are wrapped in a convergence loop. Two problems:

1. **`NameError` before assignment** — `f: Feedback[uint1_t]` creates no local variable.
2. **Combinatorial convergence** — feedback wires have no meaningful initial value within a
   clock cycle; the stable value emerges iteratively.

### Transformation

`_build_reg_sim_func` wraps the original body in a convergence loop:

```python
def feedback_test(a: uint1_t, b: uint1_t) -> uint1_t:
    f = 0              # ← zero-initialise feedback var
    __fb_iters = 0
    while True:
        __fb_iters += 1
        if __fb_iters > _SIM_FEEDBACK_MAX_ITER:
            raise RuntimeError("Feedback[T] sim: convergence failed in 'feedback_test'")
        __fb_snap_f = f    # snapshot before this pass
        rv = f | a
        f = ~b
        if f == __fb_snap_f:   # all feedback vars must match snapshot
            break
    return rv           # trailing return moved outside the loop
```

`_SIM_FEEDBACK_MAX_ITER = 1000` is the safety limit; valid combinatorial feedback converges
in 1–2 iterations.

### Interaction with `Reg[T]`

When a function contains both `Reg[T]` and `Feedback[T]`, registers are read once before
the convergence loop and reset to their initial value at the start of each iteration — so
they act as constant combinatorial inputs throughout the loop, matching hardware semantics
where combinatorial feedback resolves before the clock edge latches any state:

```python
def fb_reg_accumulate(load: uint1_t, data: uint8_t) -> uint8_t:
    __ip__ = _sim_current_inst_path()
    acc = _sim_reg_read(__ip__, "acc")   # read once
    __reg_init_acc = acc                 # snapshot for per-iteration reset
    f = 0
    __fb_iters = 0
    try:
        while True:
            __fb_iters += 1
            if __fb_iters > _SIM_FEEDBACK_MAX_ITER: raise RuntimeError(...)
            acc = __reg_init_acc         # reset register to initial each pass
            __fb_snap_f = f
            out = acc + f
            f = acc & 1
            acc = data if load else out
            if f == __fb_snap_f: break
    finally:
        _sim_reg_write(__ip__, "acc", acc)   # commit after convergence
    return out
```

---

## `Wire[T]` / `Input[T]` / `Output[T]` Global Wire Simulation

`Wire[T]` declarations at module level create `__annotations__` entries but no Python variable.
Inside `@MAIN` bodies, bare assignments like `main_a_out = r` would silently create local
variables, and `r = ~main_a_in` would raise `NameError`. The `_GlobalWireRewriter` step in
`_build_reg_sim_func` resolves this at decoration time.

### Global Wire State

```python
_sim_wire_state: dict[str, int]   # wire name → current value
```

Wire names are singletons — not keyed by instance path. Reads return 0 if the wire has
never been driven.

```python
def _sim_wire_read(name: str)               # returns current value; records reader dependency
def _sim_wire_write(name: str, value)       # stores value as-is (struct types preserved)
```

`sim_reset()` clears both `_sim_reg_state` and `_sim_wire_state`.
`sim_wire_reset()` clears only `_sim_wire_state`.

Multi-MAIN simulation via `pypeline_sim.py` is required when global wires are used, since
all MAINs sharing wires must converge together each clock cycle.

---

## `pypeline_sim.py` — Multi-MAIN Clock-Cycle Simulation

CLI tool for running multi-MAIN designs:

```
python3 src/pypeline_sim.py my_design.py --run 1000
```

Imports the design file (triggering all `@MAIN`/`@hw_func` decorations, populating
`_main_registry`), discovers global wire names recursively from module `__annotations__`,
and runs N simulated clock cycles.

### Per Clock Cycle

```
1. _sim_reg_begin_buffer()           ← register writes go to buffer, not _sim_reg_state
2. _sim_converging = True
   delta-cycle convergence queue runs (see below)
3. _sim_converging = False
   all MAINs run once more — the **final pass**:
     @sim_output functions fire; print/side-effects execute with converged wire values
4. _sim_reg_flush_buffer()           ← simulated clock edge: all flip-flops update
```

### Delta-Cycle Convergence Queue

Each convergence iteration uses a queue (not round-robin) to avoid re-executing MAINs whose
inputs haven't changed, mirroring VHDL delta-cycle / Verilog event-driven simulation:

```
queue = all MAINs                    ← start of each cycle
wire_readers = {}                    ← built lazily; persists across cycles

while queue not empty:
    main = dequeue()
    snapshot wire state
    set _sim_current_main = main
    sim_call(main)                   ← _sim_wire_read records main as reader of each wire it reads
    _sim_current_main = None

    for each wire whose value changed:
        for each MAIN that has read that wire (from wire_readers):
            if not already queued: enqueue it
```

After the first clock cycle, the dependency graph is fully built and only affected MAINs are
re-queued. Safety limit: 10 000 total MAIN executions per cycle; error lists wires still changing.

### Register Commit Timing

Registers must not commit until all MAINs have converged — matching hardware flip-flops that
all latch simultaneously at the clock edge.

1. **Buffered writes:** `_sim_reg_write` checks `_sim_reg_write_buffer`. When active, writes
   accumulate in the buffer; each MAIN re-run overwrites its own buffer entries with the
   final converged value.
2. **Simultaneous flush:** `_sim_reg_flush_buffer()` copies all buffered entries to
   `_sim_reg_state` in one operation after the final pass.

### `@sim_output` — Controlled Side Effects

Functions decorated with `@sim_output` are called normally in the final pass but are no-ops
(returning `SimVal(0)`) during convergence iterations. This prevents `print`, file writes,
and matplotlib updates from firing multiple times with intermediate wire values.

```python
@sim_output
def capture_pixel(sig, px):
    plt.update(...)   # fires once per cycle in final pass only
```

The `_is_sim_output = True` attribute set by `@sim_output` is checked by
`FuncElaborator._elab_stmt` in the hardware elaborator to silently skip such calls in
hardware function bodies. See `PY_TO_LOGIC_DESIGN.md` for the elaborator side.

---

## Simulation Modes

`pypeline_sim.py` exposes three accuracy/speed trade-offs via `--mode`:

| Mode | `SIM_STRICT_ARITH` | `SIM_RAW_INTS` | Description |
|---|---|---|---|
| `strict` (default) | `True` | `False` | Full hardware accuracy — integer widths masked at every typed operation |
| `loose` | `False` | `False` | `SimVal` objects preserved (bit-indexing works) but no bit-width masking on arithmetic |
| `raw` | `False` | `True` | Maximum speed — plain Python ints throughout; use for structural tests where overflow is not needed |

Both flags are set in `run_sim` **before** `_import_design` is called, because `@hw_func`
decorators read them at decoration time to select which wrapper variant to emit.

### Raw Mode Detail

When `SIM_RAW_INTS=True`, three decoration-time changes are made:

1. **Third `_sim_type_wrap` variant** — no arg-casting loop, no result cast; calls
   `sim_body_fn` (or `fn`) directly. Eliminates per-call `isinstance` + `_is_scalar_pypeline_int`
   + `_sim_cast` for every typed parameter.

2. **`_TypedAnnAssignRewriter` skipped** — the AST rewriter that injects `_sim_cast(expr, T)`
   around typed local assignments is not applied. Generated sim body runs with plain
   Python assignments.

3. **`SimVal` arithmetic returns plain `int`** — all arithmetic dunder methods return a plain
   Python `int` immediately. After the first arithmetic on a struct-field `SimVal`, all
   subsequent values are plain `int` and bypass `SimVal` dispatch entirely.

`raw` mode limitation: bit-indexing on the *result of arithmetic* (`(a + b)[0]`) fails since
the result is plain `int`. Bit-indexing on struct fields still works because `_RawField(int)`
subclass has `__getitem__`.

---

## Limitations

- **Registers (`Reg[T]`)** — supported; functions must carry `@hw_func` (or `@MAIN`).
  `Reg[T, MULTI_CYCLE[...].start/.end]` tags are resolved even when the `MULTI_CYCLE[...]`
  call is assigned to a local (`MC = MULTI_CYCLE[32]`) earlier in the same body (`_local_const_ns`).
- **Feedback wires (`Feedback[T]`)** — supported via convergence loop; functions must carry `@hw_func`.
- **Bare struct/array locals** (`rv: my_struct_t` / `rv: uint1_t[n]`, no initializer, followed
  by `rv.field = ...` / `rv[i] = ...`) — supported (`_TypedAnnAssignRewriter` Rules 3-4,
  `_make_sim_zero`, `_sim_lens_set` above); functions must carry `@hw_func` (or `@MAIN`), same
  as `Reg[T]`/`Feedback[T]`.
- **Global wires (`Wire[T]`, `Input[T]`, `Output[T]`)** — supported via `pypeline_sim.py`;
  multi-file designs supported (`_discover_wire_names` recursively scans imported sub-modules).
  Wire sim-keys are bare names (no module prefix); unique wire names across sub-modules assumed.
- **Closures from factory functions** — add `@hw_func` to the inner closure definition.
  `_build_reg_sim_func` resolves `Reg[T]` annotations using closure-captured variables.
  Factories that accept and then call a caller-supplied function
  (`make_autopipeline`/`make_valid_ready_mcp`/`make_stream_pipeline`) require that
  function to already be `@hw_func`-decorated and raise `TypeError` at the factory call
  site otherwise — see `is_hw_func(func)` above.
- **Global variables** — only `Wire[T]`/`Input[T]`/`Output[T]` annotations are valid as
  shared cross-function globals. No other form of module-level mutable state is supported.
- **Bit-accurate arithmetic** — `SIM_STRICT_ARITH=True` + `_TypedAnnAssignRewriter` together
  make simulation hardware-accurate for functions decorated with `@hw_func` or `@MAIN`. Inner
  functions must carry `@hw_func` to opt in. See Bit-Accurate Arithmetic section for ctype-chain
  limitations (plain int operands, shifts, `__radd__`).
- **`Input[T]` wires** — initialized to zero; setting `Input[T]` values before each cycle is
  not yet supported by `pypeline_sim.py`.

---

## Simulation Performance — Hot Paths and Key Optimizations

Benchmark reference: `python3 src/pypeline_sim.py examples/pypeline/vga_donut.py --run 1000`
(1000 clock cycles of the VGA donut renderer; exercises the full hot path: `vga_donut` →
`render_pixel` → `donut` → `length_cordic` called ~32× per active pixel → fixed-point
arithmetic → `_sim_cast`).

Baselines:
- Before optimizations (1280×720): ~27.9 s
- Before Round 2 optimizations (1920×1080): ~26 s strict, ~21 s loose, ~3.3 s raw

### 1. `_sim_cast` Hot Path (~6 M calls / 1000 cycles)

`_sim_cast` is the single hottest function. Three complementary fixes:

**Pre-computed mask/sign parameters** (`_sim_cast_param_cache`): replaces per-call
`len(ctype)` + regex with a two-level inline dict cache (`try/except KeyError` avoids `lru_cache`
frame overhead on hits). First miss populates both `_sim_cast_param_cache` and `_SIM_CONST_CACHE`.

**Identity fast-path**: `if type(val) is SimVal and val._ctype is ctype: return val` — exits
immediately when the value is already the right type (common when the same typed value flows
through multiple typed assignments).

**`_sim_val_make` bypass**: calling `SimVal(v, ctype=ctype)` invokes Python `__new__` adding
~0.1 µs per allocation. Pre-binding the C-level constructors (`_int_new = int.__new__`,
`_obj_setattr = object.__setattr__`) and calling them directly eliminates that frame.
**~4.2 s saved.**

**`_SIM_CONST_CACHE` flyweight pool**: caches `SimVal` instances for values 0–15 per ctype,
keyed by `(int_value, ctype)`. VGA control signals and step counters produce heavy reuse of
0/1 for `uint1_t`. **~0.3–0.5 s saved.**

### 2. `SimVal` Arithmetic Operators

The hot path for `+`, `-`, `*`, `<<`, `>>`, `~`, `-` (unary):

**Inline masking**: operators previously called `_sim_cast(result, out_ctype)`. Now the
`_sim_cast_param_cache` lookup and masking are inlined directly in each operator, eliminating
one function-call frame per arithmetic operation. **~0.5 s saved.**

**Direct `._ctype_name` access**: replaced `str(self._ctype)` (Python method dispatch) with
`self._ctype._ctype_name` (direct slot access). The `r` operand from `_infer_literal_ctype`
is already a string, so an `isinstance` guard avoids an attribute lookup on the common literal
case. **~1.0 s saved.**

**`lru_cache` on type helpers**: `_ctype_is_int`, `_ctype_info`, `_arith_promote`,
`_arith_output_ctype`, `_is_scalar_pypeline_int`, `_ctype_str`, `_infer_literal_ctype` are
all cached. A side effect: the same `(op, types)` key in `_arith_output_ctype` always returns
the same class object, enabling `is`-comparison fast-paths. **~2.1 s saved.**

**`type(x) is SimVal` everywhere**: replaces `isinstance(x, SimVal)` — a C-level pointer
comparison vs MRO traversal. Also `o._ctype if type(o) is SimVal else None` replaces
`getattr(o, "_ctype", None)`. **~0.4 s saved.**

### 3. Operator Dispatch Bypass

Shift and negate operators (`__rshift__`, `__lshift__`, `__neg__`, `__invert__`) were
entering `_dispatch_binary`/`_dispatch_unary` (two dict lookups each) even when no custom
operators were registered.

**`_registered_binary_op_names`** and **`_registered_unary_op_names`** module-level sets
track which op names have any global registration. `__rshift__`, `__lshift__`, `__neg__`,
`__invert__` check the set and skip dispatch entirely when the op name is absent:

```python
def __rshift__(self, o):
    v = int(self) >> int(o)
    if self._ctype is None or "SR" in _registered_binary_op_names:
        return self._dispatch_binary("SR", o, v, preserve_ctype=True)
    return _sim_val_make(v, self._ctype)
```

`__rshift__` runs ~1.95 M times/1000 cycles in the CORDIC benchmark. **~3.3 s saved.**
Unary dispatch bypass: **~0.15 s saved.**

### 4. `_push_scoped_registrations` Short-Circuit

Called for every `@hw_func` invocation even when most functions have no scoped registrations.

`_scoped_funcs: set` tracks `id(func)` for any function with a scoped registration. Returns
module-level singleton `_EMPTY_SAVED = []` immediately for functions not in the set.
`_pop_scoped_registrations` uses a `_SCOPED_MISSING` sentinel object instead of creating
`object()` on each pop. **~0.2 s saved.**

### 5. Two-Path `_sim_type_wrap`

`_build_reg_sim_func` returns `(fn_or_None, has_state)`. `_sim_type_wrap` uses `has_state`
at decoration time to choose between a fast combinational wrapper and a state-aware wrapper.

**`has_state=False` fast path**: skips `sys._getframe`, `_sim_inst_stack` push/pop, and
`co_positions()` entirely. `co_positions()` was particularly expensive — it allocates a list
of `(lineno, end_lineno, col, end_col)` tuples for every bytecode instruction in the caller
frame on each call. **~1.7 s saved.**

### 6. Raw Mode Path (`SIM_RAW_INTS=True`)

Three decoration-time changes described in [Simulation Modes](#simulation-modes) together
achieve ~9× speedup vs. baseline in raw mode:

- **Third `_sim_type_wrap` variant**: no boundary casting. **~3 s saved.**
- **Skip `_TypedAnnAssignRewriter`**: no `_sim_cast` injected in body. **~3 s saved.**
- **`SimVal` arithmetic returns plain `int`**: breaks the `SimVal` chain after first op. **~3 s saved.**
- **`_RawField` for struct fields**: `int` subclass preserving `__getitem__`; C-level arithmetic.
  Eliminates `_typed_new` calling `_int_new(SimVal,…)` for every struct field access. **~0.75 s saved.**

### Summary

| Mode | Before optimizations (1280×720) | After optimizations |
|---|---|---|
| `strict` | ~27.9 s | ~15 s (~1.9×) |
| `loose` | ~27.9 s | ~12 s (~2.3×) |
| `raw` | ~27.9 s | ~3 s (~9×) |

| Mode | Before Round 2 (1920×1080) | After Round 2 |
|---|---|---|
| `strict` | ~26 s | ~25.3 s |
| `loose` | ~21 s | ~20.4 s |
| `raw` | ~3.3 s | ~2.5 s (1.3×) |

The remaining time in raw mode is dominated by Python function-call overhead across the sim
loop (`_run_clock_cycle`, `_convergence_loop`, `sim_call`) and `_sim_reg_read`/`_sim_reg_write`
dict lookups. Further speedup would require C extension code or a numpy-vectorised strategy.

## Tests

`src/tests/pypeline_tests/sim_tests.py` covers the simulation behaviors described in this
document directly — `Reg[T]`/`Feedback[T]`/`Wire[T]` simulation, bit-accurate arithmetic
(`SIM_STRICT_ARITH`), and `sim_call()` — by running the plain-`python3` test files under
`inst/` (e.g. `pypeline_test.py`, `bit_math_test.py`, `reg_init_test.py`), each of which
asserts on `sim_call()` results and exits non-zero on failure. It also covers the
multi-MAIN clock-cycle runner (`pypeline_sim.py` § above) via `global_wires_sim_test.py`,
invoked as `python3 src/pypeline_sim.py inst/global_wires_sim_test.py --run 10`.

```
python3 src/tests/pypeline_tests/sim_tests.py            # just the sim tests
python3 src/tests/pypeline_tests/sim_tests.py -j 4
python3 src/tests/pypeline_tests/run_all.py --category sim
```

No `pipelinec` elaboration/synthesis happens in this script — that's covered separately by
`elab_tests.py`/`synth_tests.py` (see
[PY_TO_LOGIC_DESIGN.md § Tests](PY_TO_LOGIC_DESIGN.md#tests)). Tests run in parallel via a
thread pool (`common.py`, shared with the other two scripts); see
[pypeline_DESIGN.md § Tests](pypeline_DESIGN.md#tests) for the full-suite runner.
