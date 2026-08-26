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
- [`sim_model` — Python Simulation Models](#sim_model--python-simulation-models)

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

**Call sites:**
1. By `@hw_func` / `_sim_type_wrap` to cast function inputs and outputs at call boundaries.
2. By `SimVal._dispatch_unary`/`_dispatch_binary` as a fallback when a dispatched function
   returns an untyped value.
3. By `_TypedAnnAssignRewriter`-generated code to truncate typed local variable assignments
   inside `@hw_func` bodies.
4. By `_CTypeMeta.__call__` for a scalar-destination cast (`T(x)`, one positional
   argument, no keywords — see `pypeline_DESIGN.md`'s Casting section) after a registry
   miss — this is exactly what makes `y = type2_t(x)` and `y: type2_t = x` identical:
   both eventually call `_sim_cast` with the same `(val, ctype)`. A compound-destination
   cast dispatches through the registry instead, in `_CastDispatchMeta.__call__` (a
   metaclass, not `_typed_new` — see Casting for why), never touching `_sim_cast` itself.

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
    if not prev_active:
        _sim_input_cache.clear()
        _sim_reg_begin_buffer()
    _sim_active = True
    saved = _push_scoped_registrations(func)
    try:
        return func(*args, **kwargs)
    finally:
        _pop_scoped_registrations(saved)
        _sim_active = prev_active
        if not prev_active:
            _sim_reg_flush_buffer()
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

**Outermost-call register buffer (bug fixed 2026-07-11).** `prev_active` (already used to
gate the once-per-cycle `_sim_input_cache` reset) also gates a register-write buffer: the
outermost `sim_call()` opens one via `_sim_reg_begin_buffer()` before running `func`, and
flushes it via `_sim_reg_flush_buffer()` in `finally` — the same buffered-commit machinery
`pypeline_sim.py` opens once per clock cycle (see below). This makes one top-level
`sim_call()` behave like one atomic hardware clock edge for every `Reg[T]`/`@sim_model`
write in the whole call tree, no matter how deep. It fixes a state-consistency bug where a
`Feedback[T]` convergence loop (see below) re-invoking a *stateful child* `@hw_func`
multiple times per call let a later convergence pass observe the child's `Reg` value as
already written by an earlier pass — since `_sim_reg_write` committed immediately with no
buffer active, unlike the parent's own `Reg` locals (which are reset from a local
`__reg_init_<name>` snapshot each pass, never re-committed until final convergence). Because
`_sim_reg_read` only ever reads committed `_sim_reg_state` (see [`Reg[T]`
Simulation](#regt-simulation--stateful-registers-across-clock-cycles) below), buffering every
write for the whole outer call is sufficient: every convergence pass, at any nesting depth,
now sees the same true cycle-start state, and only the last pass's write survives once the
outermost call's buffer flushes. `pypeline_sim.py` was never vulnerable to this bug — it
already brackets an entire clock cycle (every MAIN, every convergence re-evaluation) with
its own single `_sim_reg_begin_buffer()`/`_sim_reg_flush_buffer()` pair, and never resets
`_sim_active` between cycles, so `sim_call(main_fn)` always sees `prev_active == True` there
and skips this branch — no double-buffering conflict.

### `sys.path` bootstrap — and the one case it doesn't cover

Both `pypelinec` (real builds, via `PY_TO_LOGIC.py`) and `pypelinec --sim` (native sim, via
`pypeline_sim.py`'s `_import_design`) insert two directories onto `sys.path` before importing
the design file: the design file's own directory (so its local sibling imports work) and the
repo's `include/pypeline` directory (so `from stream import ...`, `from dsp.fir import ...`,
etc. resolve without any manual setup). This means a normal install only needs the repo's
`src/` directory on `PATH` for the `pypelinec` command — see the [Quick Start](README.md).
Invoking `pypeline_sim.py` directly (`python3 src/pypeline_sim.py my_design.py --run 1000`)
goes through the same `_import_design` bootstrap and needs no separate setup either.

**The one case that does need manual `PYTHONPATH`** is `sim_call`-style usage as described
above: running a design file itself as a plain script (`python3 my_design.py`), calling
`sim_call(func, ...)` directly rather than going through `pypelinec`/`pypeline_sim.py`.
There's no bootstrap step in that path, so the design file never gets `include/pypeline`
added to `sys.path` on its own. If you do this, set:
```
export PYTHONPATH=$PYTHONPATH:$(pwd)/src:$(pwd)/include/pypeline
```
first, or add an equivalent `sys.path.insert(...)` at the top of the design file.

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

### Bitwise Operators (`&`, `|`, `^`) — `_ctype` Preservation and Masking

Unlike `+`/`-` (which can change width via carry/borrow and so need `_arith_promote`),
hardware `and`/`or`/`xor` require matching-width operands and the result simply *keeps*
that width — no promotion table needed. `SimVal.__and__`/`__or__`/`__xor__` implement this
via a small `_bitwise_ctype(self, o)` helper: `self._ctype` if set, else `o._ctype` if `o`
is a `SimVal`, else `None` (bare, untyped result — same as arithmetic ops with no typed
operand). When a ctype is resolved, the result is also masked to that ctype's width/
signedness under `SIM_STRICT_ARITH` (mirroring `__invert__`/`__lshift__` and every
arithmetic dunder) — see "Bug fixed 2026-07-11" below for why this masking step is required,
not just the ctype tag.

`__rand__`/`__ror__`/`__rxor__` (plain-int `op` `SimVal`, e.g. `0xFF & some_uint32`) mirror
`__radd__`/`__rsub__`: `o` is always a non-`SimVal` int here (Python only calls the reflected
method when the left operand isn't a `SimVal` subclass instance), so they just reuse
`self._ctype` directly (and mask against it) — AND/OR/XOR are commutative, so no promotion
logic is needed.

**Bug fixed 2026-07-04:** `__and__`/`__or__`/`__xor__` originally did
`return SimVal(int(self) ^ int(o))` — constructing a **`_ctype=None`** result even when both
operands were fully-typed. Bit-manipulation primitives (`rotl`, `rotr`, `bswap`, `bit_dup`,
`bit_assign`) infer their operand's width via `_bit_manip_width`, which — when `_ctype` is
`None` — falls back to `int(v).bit_length()`. That fallback silently returns a width
*narrower* than the real type whenever the value happens to have leading zero bits (e.g.
`0x0EFAF702` has `_ctype` uint32_t but `.bit_length() == 28`), so `rotl(x ^ y, n)` on an
untyped XOR result rotated within the wrong (too-narrow) field — a completely different,
but equally plausible-looking, 32-bit result. This was the root cause of a native-sim-only
ciphertext corruption in the wireguard-fpga ChaCha20 port: `rotl(state[d] ^ a1, 16)` inside
`quarter_round` lost `_ctype` at the `^`, corrupting every round's output while
`chacha20_init` (no bitwise ops) matched GHDL exactly and scalar `rotl` alone (independently
tested) was fine. Found by bisecting with matched `sim_print` probes between
`pypeline_sim.py` and `pipelinec --comb --sim --cocotb --ghdl` at successively earlier
points in the call chain (chacha20_block_step → chacha20_init) until one boundary matched
and the next didn't, then hand-verifying the suspect intermediate value against the `rotl`
formula directly in Python — the 28-bit-vs-32-bit rotation was diagnostic. See
`project_pypeline_fixes` memory (Fix 9) for the full bisection method, worth reusing for any
future "native sim disagrees with GHDL on a bit-manipulated value" bug.

**Bug fixed 2026-07-11:** the 2026-07-04 fix above made `__and__`/`__or__`/`__xor__` (and the
reflected forms) *preserve* a ctype tag, but none of them actually *masked* the raw int
result to that ctype's width — unlike every other typed dunder in the class. This made
`_sim_cast`'s fast path (`if type(val) is SimVal and val._ctype is ctype: return val`, used
by every struct-field/typed-local assignment) unsound: a bitwise op combining an
out-of-range operand with a properly-typed sibling could produce a `SimVal` tagged with the
*correct* target ctype but an out-of-range value, which `_sim_cast` then let through
unmasked. Concretely: `o.field = ~some_reg | y` where `some_reg: Reg[uint1_t]` holds a value
*committed from a previous sim cycle* — see the `_TypedAnnAssignRewriter` scalar-`Reg[T]`
tracking gap fixed below, which is what actually produced the out-of-range operand in this
case — masked correctly on cycle 1 (power-on) but returned raw two's-complement (`-2`/`-1`
instead of `0`/`1`) on later cycles, because `~some_reg` lost its ctype (untyped fallback),
picked the *sibling* operand's ctype back up via `_bitwise_ctype` in the `|`, and `_sim_cast`
trusted that tag without re-masking. Fixed by adding the same mask/sign-extend step already
used by `__invert__`/`__lshift__`/arithmetic to all six bitwise dunders. Root-caused via
three cross-checked codebase explorations plus direct source reads while debugging
`dsp/fir_interp.py`'s zero-stuffer (`~have | last_beat`); see `project-uint1-field-mask-bug`
memory for the full repro and cycle-by-cycle trace.

**Bug fixed 2026-07-24:** `_typed_new` (struct constructor kwargs, see
[pypeline_DESIGN.md](pypeline_DESIGN.md#struct-decorator)) had the same class of
unsound "trust the existing ctype tag" shortcut, but for the *constructor* path rather than
bitwise dunders: it only cast a scalar-int kwarg to the field's declared `ftype` when the
value wasn't already a typed `SimVal` (`if type(v) is not SimVal or v._ctype is None`). This
assumed any already-typed `SimVal` must already be typed *to this field* — false whenever
arithmetic promotes width, e.g. `uint4_t + int` yields a `SimVal` tagged `uint5_t`, not
`uint4_t`. So `p_t(c=a.c+1)` at `uint4_t` max (`a.c=15`) constructed a field holding the raw,
unmasked `16` tagged `uint5_t`, while the corresponding field-assignment form
`o.c = a.c+1` correctly wrapped to `0` (assignment always recasts unconditionally via
`_sim_cast_deep`, regardless of the RHS's existing ctype). Fixed by making the constructor
path unconditionally call `_sim_cast(v, ftype)` too — `_sim_cast`'s own fast path already
no-ops when the ctype already matches `ftype` exactly, so this costs nothing in the common
already-correctly-typed case. Native-sim-only divergence: VHDL elaboration
(`PY_TO_LOGIC.py`) never calls `_typed_new` — it detects struct-construction call nodes
structurally and generates per-field VHDL assignments directly from annotated types, so
hardware codegen was never affected. Regression test:
`src/tests/pypeline_tests/inst/struct_ctor_narrow_test.py`.

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
`_array_elem_ctype(ctype)` (the same `_elem_ctype`-preferred / leftmost-`[N]`-stripping
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
it from `_ctype_name`'s *leftmost* `[N]` — or `None` if `ctype` isn't an array. Its sibling
`_array_len(ctype)` returns that same array's own outer/first dimension (`_arr_len`, or the
leftmost `[N]` as a fallback). The leftmost bracket is always the outer/first dimension —
matching C's `T x[A][B]` and `PY_TO_LOGIC.py`'s elaboration-side `_array_first_dim`/
`_array_elem_type` (`PY_TO_LOGIC_DESIGN.md`) — for any chain of dimensions, not just one.

**What is NOT rewritten:**
- `Wire[T]`, `Input[T]`, `Output[T]` descriptor annotations
- The `Reg[T]`/`Feedback[T]` `AnnAssign` node itself, for either scalar or compound inner
  types — `_build_reg_sim_func` handles the actual read/zero-init injection separately.
  A scalar inner type (e.g. `have: Reg[uint1_t]`) is exempt from Rule 4 (no nested `.field=`/
  `[i]=` chain to rewrite), but **is** tracked into `_declared_types` (Rule 2's dict) so a
  later bare `have = expr` reassignment in the same body is still auto-cast, exactly like a
  non-`Reg` scalar local — fixed 2026-07-11 (see "Bug fixed 2026-07-11" above); previously
  this tracking was skipped entirely for scalar `Reg[T]`/`Feedback[T]`, letting a plain
  reassignment commit an untyped/unmasked raw Python int as the register's persisted state
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

### Char Arrays — `CharArray` and Unified Deep Casting

A `char_t[N]` simulation value is a **`CharArray`** (`pypeline.py`) — a `list` subclass of
`char_t`-typed `SimVal`s that also behaves like the Python string it represents:

```python
class CharArray(list):
    def __str__(self): ...   # stops at the first NUL (0) element, mirrors hardware %s
    def __eq__(self, other): ...  # compares equal to a plain Python str via str(self)
```

This is what lets every sim-side string boundary — `sim_call` args/kwargs, `sim_call`
return values, `Reg[T]` init, struct-field construction, and local var/field assignment
inside a simulated function body — accept a bare Python `str` on the way in and compare
equal / `str()`-format correctly on the way out, with **no user-facing conversion
functions**. (Earlier revisions of this feature required calling
`str_to_char_array`/`char_array_to_str` explicitly at each of these boundaries; both were
removed once `CharArray` made the conversion automatic everywhere.)

`CharArray`'s `__str__` is deliberately distinct from `strlen()`, which returns the array's
*declared capacity* (see [pypeline_DESIGN.md](pypeline_DESIGN.md#char-array-support)), not
the NUL-terminated content length `str()` stops at — conflating the two would hide a real
semantic difference behind one overloaded name. `uint8_t[N]` arrays are deliberately **not**
wrapped in `CharArray` — they're raw byte arrays, not display strings.

**`_sim_cast_deep(value, ctype)`** (the pre-existing generic recursive array caster) is the
single mechanism behind all of this: extended to accept a bare `str` for any target whose
array element is `char`/`uint8_t` (zero-padding/length-checking exactly like the
elaboration-side `_elab_str_literal`), and to wrap the result in `CharArray` whenever the
element is specifically `char` — at any nesting depth, so a `char_t[3][3]` grid built from
`["ab", "cd", "ef"]` recurses correctly. Every call site below now routes through this one
function instead of a bespoke `isinstance(v, str)` branch:

1. **`_TypedAnnAssignRewriter` Rule 1** (`var: char_t[N] = "literal"`) and **Rule 4**
   (`.field = "literal"` / `[i] = "literal"`) both emit a call to the same
   `_sim_cast_deep`-wrapping helper (`_make_deep_cast`) used for every other compound-typed
   write — no separate string-literal-detection code path needed once `_sim_cast_deep`
   itself understands `str`.
2. **Call-argument casting** (`_sim_cast_call_arg` for positional args, `_run_body`'s kwarg
   loop) — gated by `_is_char_like_array(pt)` (true for an array, at any nesting depth,
   whose ultimate element is `char`/`uint8_t`) rather than `isinstance(v, str)`, so both a
   bare string *and* a nested list-of-strings (2D grid) are handled uniformly. This covers
   a string literal passed directly as a call argument (e.g. `echo_name("Current:")`) and
   `sim_call(fn, s="hello")`.
3. **Return-value casting** (`_run_body`) — previously array-typed return values were never
   cast at all (only scalar-int returns were); now a `_is_char_like_array(ret_t)` return
   type routes the result through `_sim_cast_deep` too, which is what makes
   `sim_call(some_char_returning_fn)` produce a `CharArray` (comparable to `str`) rather
   than a plain list.
4. **`_typed_new`** (struct construction) — the array-of-scalar field-casting branch now
   also accepts a bare `str` kwarg (e.g. `packet_t(name="sensor_1", ...)`), routed through
   `_sim_cast_deep` the same way.

`_build_reg_sim_func`'s per-register init-value evaluation routes **every** `Reg[T] = <literal>`
init value through `_sim_cast_deep(init_val, T)` before storing it in `reg_zeros` — not just
the `str` case described next (fixed 2026-07-11; previously a scalar or array-of-scalar
literal init, e.g. `have: Reg[uint1_t] = 1`, was stored as a bare untyped Python value,
the same failure mode as the `_declared_types` gap above but present from cycle 0). This is
safe/idempotent for every shape `_sim_cast_deep` accepts: struct dict/ctor values pass
through its `_fields` fast path unchanged, arrays recurse element-wise, and scalars get
cast/masked.

`Reg[T] = "literal"` power-on-reset values are also supported **in simulation only**, as one
case of the above: a `str` init value for a char-like array target. This has **no** corresponding
hardware-elaboration support — `Reg[T]` where `T`'s leaf element type is `"char"` raises
`ElaborationError` for any initializer at all (see
[pypeline_DESIGN.md](pypeline_DESIGN.md#char-array-support) for why: a pre-existing
`VHDL.py` bug in the Python-value register-init path, out of scope to fix here). This is a
deliberate, documented sim/hardware asymmetry, not an oversight — useful for pure-Python
prototyping of a design before its register-init strategy is finalized, but such a
function cannot be elaborated to hardware as written.

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
| `wire = expr` (Assign, whole-wire) | `_sim_wire_write('wire', expr)` (Expr stmt, no local binding) |
| `wire: T = expr` (AnnAssign with value) | `_sim_wire_write('wire', expr)` |
| `module_alias.wire` (Attribute, Load) | `_sim_wire_read('wire')` |
| `module_alias.wire = expr` (Attribute, Store, whole-wire) | `_sim_wire_write('wire', expr)` |
| `wire.field = expr` / `wire[i] = expr` (any nesting, incl. `module_alias.wire.field = expr`) | `_sim_wire_lens_write('wire', [path...], expr)` |
| `wire += expr` (AugAssign, whole-wire) | `_sim_wire_write('wire', _sim_wire_read('wire') + expr)` |
| `wire.field += expr` (AugAssign, field/index) | `_sim_wire_lens_write('wire', [path...], _sim_wire_lens_read('wire', [path...]) + expr)` |

Module-level wire declarations (`wire: Wire[T]` with no value) are `AnnAssign` nodes with
`value=None` and are left untouched.

For cross-module wire access (`board_vga.vga_pmod = ...`), `_build_reg_sim_func` also scans
all module objects in `fn.__globals__` for `Wire[T]`/`Input[T]`/`Output[T]` annotations and
builds a `module_wire_attrs` dict `{(alias_name, attr_name): bare_wire_name}` **and** a
parallel `module_wire_ctypes` dict of the same shape holding each wire's `inner_ctype` (read
straight off the `_WireType`/`_InputType`/`_OutputType` annotation object). Both are passed to
`_GlobalWireRewriter` alongside the bare `global_wire_names`/`wire_ctypes` maps. Every
discovered wire's ctype is also registered globally in `_sim_wire_ctype` (keyed by the
qualified `<module>.<wire>` sim name) so `_sim_wire_lens_read`/`_sim_wire_lens_write` can
build a typed zero value for a compound wire before any whole-wire write has ever landed in
`_sim_wire_state`.

### Field/index lens writes: `_sim_wire_lens_write` / `_sim_wire_lens_read`

A target chain rooted at a wire (`wire.field`, `wire[i].field`, `module.wire.field`, at any
nesting depth) is detected by `_wire_chain_to_path`, which walks the `Attribute`/`Subscript`
chain down to its base and — if the base resolves to a global wire — returns the qualified
sim key, the root-to-leaf path (as AST nodes: `Constant(field_name)` for attribute steps, the
raw slice node for subscript steps, so a dynamic index expression is evaluated at sim runtime
exactly as written), and the statically-resolved leaf ctype (walking the wire's declared
struct/array type through the path). This mirrors `_TypedAnnAssignRewriter._chain_to_path`
exactly, except the root is resolved against `wire_names`/`module_wire_attrs` instead of a
local `_compound_declared` map — the two rewriters compose in sequence (`_GlobalWireRewriter`
runs first) without conflict, since each only ever rewrites chains rooted in its own kind of
name.

```python
def _sim_wire_lens_read(name: str, path: list)                      # lens-get into the wire's current (or zero-default) value; records reader dependency
def _sim_wire_lens_write(name: str, path: list, value, claim_key)   # lens-set: _sim_wire_state[name] = _sim_lens_set(current_or_zero, path, value); records the concrete path under claim_key
```

Both reuse `_sim_lens_set` (the same struct-`_replace`/list-copy mechanism
`_TypedAnnAssignRewriter` uses for local compound variables — see below) and
`_sim_wire_current_or_zero`, which returns `_sim_wire_state[name]` if present, else a fresh
`_make_sim_zero(ctype)` built from the registered `_sim_wire_ctype[name]`. A leaf write is
`_sim_cast_deep`-wrapped when the leaf ctype was staticaly resolvable, exactly like a local
compound variable's field write — but since a ctype object can't be embedded directly as an
`ast.Constant` value (Python's compiler only accepts literal types there), the rewriter stashes
it in a `leaf_ctypes_out` out-dict under a synthetic `__wire_leaf_ctype_<line>_<col>__` name and
references that name instead, exactly mirroring `_TypedAnnAssignRewriter`'s
`__sim_ann_<line>_<col>__` mechanism (see below); the decoration site merges `leaf_ctypes_out`
into the rewritten function's exec namespace alongside `ann_ctypes_out`.

### Per-invocation zero-reset via runtime claim tracking

`_sim_wire_state` is one persistent module-level dict shared across *every* invocation of a
function within a simulated clock cycle — not just across cycles. In particular, `_run_clock_cycle`
runs each `@MAIN` at least twice per cycle: once (or more) during the convergence pass, then once
more in the final `@sim_output`-enabling pass. Without correction, a function that both reads and
writes the same wire would see, on its second invocation, the *first* invocation's already-written
value as if it were "read before write", and a conditionally-skipped write would leave last
cycle's value latched — the opposite of the zero default elaboration gives an undriven leaf
(see `PY_TO_LOGIC_DESIGN.md`'s Global Wires section).

The reset is scoped by **runtime claim tracking**, not static analysis. Every rewritten write
call carries the writing function's qualified name as `claim_key`
(`f"{fn.__module__}.{fn.__qualname__}"`, baked in as an `ast.Constant` by
`_GlobalWireRewriter`): `_sim_wire_write(name, value, claim_key)` records a whole-wire `()`
claim, `_sim_wire_lens_write(name, path, value, claim_key)` records the **concrete** path
written this call (field strs, indices normalized to ints) into the module-level
`_sim_wire_claims[claim_key][name]` set. When the rewriter saw any write in the body
(`written_wire_names` non-empty), the decoration site injects a single
`_sim_wire_reset_claims(claim_key)` statement at the very top of the rewritten body: it zeros
exactly the claimed leaves — the whole wire for a `()` claim, else one
`_sim_lens_set(..., _make_sim_zero(leaf_ctype))` per claimed path (leaf ctype resolved by
walking `_sim_wire_ctype[name]` along the path via `_sim_ctype_at_path`).

Runtime claims are what make the reset exact for every write shape elaboration supports
statically *and* the ones it can't: static nested paths, unrolled `for i in range(...)` loops
(a real Python loop with a variable index at sim time — the claims accumulate the concrete
indices actually touched), and genuinely dynamic indices. Claims grow monotonically and are
never dropped between cycles, matching hardware, where the mux-to-zero structure exists for
every leaf the function ever writes, every cycle; they are cleared with the rest of the wire
state by `sim_reset()`/`sim_wire_reset()`. Resetting only the invoking function's own claimed
leaves — never the whole wire — is what lets multiple writer functions share one compound wire:
a whole-wire reset would transiently clobber a different writer's already-committed leaves
within the same cycle's convergence loop. (Cross-writer readback needs no extra sim machinery
at all: a writer's read of a foreign leaf is an ordinary `_sim_wire_read`/`_sim_wire_lens_read`
of the shared state, which also registers the reader for convergence re-queueing when the
foreign writer's value changes.)

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
    f = __fb_zero_f__  # ← zero-initialise feedback var (typed: _make_sim_zero(inner_ctype))
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

`__fb_zero_f__` is precomputed once at decoration time (`feedback_zeros[name] =
_make_sim_zero(ann_val.inner_ctype)`, mirroring `reg_zeros`) and injected into `new_globals`
alongside `__reg_zero_<name>__`. This matters for `Feedback[struct_t]`: the bootstrap value on
the loop's first pass must be a real zeroed struct instance, not a bare `int 0` — a body that
reads a field off the feedback var before its own later assignment (the documented "declare
before use" idiom) would otherwise hit `AttributeError: 'int' object has no attribute '...'`
on iteration 1, before convergence ever gets a chance to settle it.

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
    f = __fb_zero_f__
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

This per-pass reset only covers a function's *own* `Reg[T]` locals — it has no reach into a
*nested* `@hw_func` call's registers, which live in `_sim_reg_state` under that child's own
instance path and are read/committed independently by the child's own wrapper each time the
parent's convergence loop re-invokes it. Correctness for that case (a `Feedback[T]` wire
driven from, or consumed by, a stateful child) instead comes from the outermost `sim_call`'s
register-write buffer described above — every convergence pass's writes to *any* descendant
register land in that one shared buffer, and `_sim_reg_read` never observes them until the
whole outer call finishes and the buffer flushes, so a child re-invoked mid-convergence always
reads the true cycle-start value regardless of what earlier passes wrote.

**Bug fixed 2026-07-11:** before the outermost-`sim_call` buffer existed, a `Feedback[T]`
wire driven from a *stateful child's* `Reg`-backed output corrupted values on cycles where
that child's old and new `Reg` value differed. Concretely:

```python
@hw_func
def producer_child(x: uint1_t) -> uint1_t:
    r: Reg[uint1_t]
    out: uint1_t = r      # Reg-driven output (previous cycle's x)
    r = x
    return out

@hw_func
def parent(x: uint1_t) -> p2_t:
    fb: Feedback[uint1_t]
    cnt: uint8_t = consumer_child(fb)   # fb consumed by a second stateful child
    prod: uint1_t = producer_child(x)   # fb produced by a stateful child
    fb = prod
    ...
```

`consumer_child`'s presence (any consumer of `fb`, stateful or not, forces at least one extra
convergence pass) meant `producer_child` was re-invoked more than once per outer call. Each
invocation's `finally`-block commit (`_sim_reg_write(__ip__, "r", r)`) wrote straight to
`_sim_reg_state` with no buffer active, so the *second* pass's read of `r` returned the
*first* pass's freshly-written value instead of the true previous-cycle value — one cycle's
output ended up a mix of two convergence passes. This exact composition is what corrupted
`include/pypeline/dsp/fir_interp.py`'s window state (`fir_ready: Feedback[uint1_t]` driven
from `make_stream_pipeline`'s `Reg`-backed ready signal), producing `[15, 75, 45, 0, 0]`
instead of the correct impulse response `[15, 30, 45, 30, 15]`. Regression coverage:
`inst/feedback_reeval_test.py` (`native_sim_tests.py`).

**Interface-function-generated instances simulate through this exact path.** A function annotated
with a whole `@interface` (see `docs/PY_TO_LOGIC_DESIGN.md`) compiles to an ordinary `@hw_func`
whose body threads each backward edge through a `Feedback[T]` — so the generated function needs no
sim-specific handling: it is `_build_reg_sim_func`-wrapped and converges like any hand-written
`Feedback` design. This includes *feedforward* loops (an FSM consuming a value produced by a call
emitted after it), which become a `Feedback` on the forward value and converge the same way.
Because the same generated artifact is what elaborates, native sim and VHDL stay in lockstep by
construction. An **array** interface port (fan-out) is no different: each element's reverse value
gets its own `Feedback`, and they are assembled into a local array immediately before the call.
Coverage: `inst/interface_func_test.py`, `inst/interface_func_loop_test.py`,
`inst/interface_boundary_test.py` (both style crossings, plus plain non-interface signals
crossing them) and `inst/interface_array_port_test.py` (`native_sim_tests.py`), all checked
against hand-written explicit twins.

**Annotation re-evaluation.** `_build_reg_sim_func` re-`exec`s the function definition, so its
parameter and return annotations are re-evaluated in a rebuilt namespace. A name used *only* in
an annotation is not captured as a free variable, which used to make factory-local types
invisible here (`x: some_fb_t[n]` → `NameError` on `some_fb_t`, even though `n`, used in the body,
resolved). Each parameter's already-resolved annotation object is now bound to a generated name
and substituted into the AST, which works for every annotation form rather than bare names only.

Note the limit of that guarantee: it covers the *wiring*, not port **types**. Native sim is
duck-typed, so passing a bare `uint1_t` where a module expects an interface's `{ready}` struct
simulates fine and is caught only by VHDL type-checking — run the synth/vhdl_sim tiers after a
port-shape change.

---

## `sim_model` — Python Simulation Models

`sim_model(target, copy_state=True)` (public API, defined next to `vhdl()`) attaches a
Python model to any `@hw_func`/`@MAIN` function: in simulation the model runs instead of
the function's own body. This is the hook that makes `vhdl(...)`-bodied functions
simulable, and it works equally as a fast-model override for ordinary hardware functions.
Elaboration is untouched — the elaborator never sees models.

### Model Routing Cell

`_sim_type_wrap` creates a one-element closure list `_model_cell = [None]` per decorated
function and exposes it as `wrapper._sim_model_cell`. `sim_model(target)` validates and
stores `(model, kind, copy_state)` into it, where `kind` is `"hw_func"` (delegate),
`"class"`, or `"callable"` (pre-constructed instance). Exactly one model per target —
a second attachment raises `ValueError`; a non-`@hw_func` target raises `TypeError`, as
does an `@hw_func` delegate whose arg/return types differ from the target's.

Every wrapper variant checks the cell per call — the no-model hot path pays one
`is not None` test:

- `_run_body` (shared by the two casting wrappers) routes to
  `_call_sim_model(...)` before the `sim_body_fn`/`fn` dispatch, so **arg and return
  casting are shared with normal calls** (model outputs wrap to the declared return
  width for free).
- The `has_state=False` fast path normally skips the instance stack entirely; when a
  model is attached it pushes `(fn.__qualname__, call_loc)` around the call (via
  `_sim_capture_call_loc`, which honors `SIM_TRACE_LOCATIONS`), because class models key
  their state by instance path.
- The `SIM_RAW_INTS` wrappers route to the model with **no casting**, consistent with
  raw mode.
- The `if not _sim_active:` elaborator-probe fallbacks are unchanged — models never run
  outside simulation.

### Evaluation Semantics (`_call_sim_model`)

**hw_func delegates** are simply called: the delegate's own wrapper manages its
`Reg[T]`/`Feedback[T]` state and pushes its own stack entry *on top of the target's*, so
two call sites of the target keep independent delegate state. Double arg/return casting
through both wrappers is idempotent.

**Class/callable models** get Reg-like commit timing. Per evaluation:

```python
inst_path = _sim_current_inst_path()
committed = _sim_reg_read(inst_path, "__sim_model__", None)   # reserved key
if committed is None:
    committed = model()          # lazy per-instance creation (fresh power-on state)
working = copy.deepcopy(committed)
result  = working(*args, **kwargs)
_sim_reg_write(inst_path, "__sim_model__", working)           # buffer-aware commit
```

Storing the instance under the reserved `"__sim_model__"` key in `_sim_reg_state` means
buffered commit, `_sim_reg_flush_buffer`, and `sim_reset()` (models re-`__init__`) all
come for free from the existing register machinery.

The invariant this buys: **every evaluation computes outputs from a deepcopy of the
state committed at the last clock edge** — outputs are a pure function of (cycle-start
state, current inputs), which is exactly "combinational logic + registered state".
Consequences per context:

- **Plain `sim_call`** — the outermost call opens a register-write buffer for its whole
  duration (see [`sim_call`](#sim_callfunc-args--simulation-entry-point) above), so state
  advances exactly once per top-level call, computed from converged inputs — the same
  invariant as the `pypeline_sim.py` case below, including through nested `Feedback[T]`
  convergence loops.
- **`pypeline_sim.py` wire convergence** — the model may re-evaluate many times per
  cycle with changing input wire values; committed state never moves mid-cycle, so each
  re-evaluation recomputes fresh and a combinational input→output path through the model
  converges exactly like ordinary comb logic. The final post-convergence pass's buffered
  copy is what `_sim_reg_flush_buffer` commits — state advances exactly once per cycle,
  computed from converged inputs.
- **`Feedback[T]` loops in Layer 1** (bug fixed 2026-07-11) — a model called inside a
  feedback convergence loop now also commits once per outermost `sim_call`, not once per
  convergence iteration, since the outermost call's write buffer covers the whole call
  tree the same way `pypeline_sim.py`'s per-cycle buffer does. This is the same fix that
  makes nested `Reg[T]` hw_funcs inside feedback loops convergence-safe — both write
  through the identical `_sim_reg_write` buffered-commit path (a `sim_model` instance is
  just another `_sim_reg_state` entry, keyed by `"__sim_model__"`).
- **Side effects** — model `__call__` bodies multi-fire during convergence; keep them
  side-effect-free or check `pypeline._sim_converging` (the rule `@sim_output` encodes).

`copy_state=False` opts out of the deepcopy for heavy state: the instance is created
once (written directly to `_sim_reg_state`, bypassing the buffer — otherwise re-
evaluations in the creation cycle would re-instantiate) and mutated in place. Faster,
but not convergence-safe; only sound when inputs are final the first time the model runs
each cycle.

---

## `make_fifo` Simulation Model (`_FifoFwftModel`)

`include/pypeline/fifo.py`'s `make_fifo` attaches a `collections.deque`-based FWFT model
to its inner `vhdl(...)`-bodied `fifo` function via `@sim_model(fifo)` — a `class`-form
model, `copy_state=True` (the default), so it gets the same Reg-like deepcopy/
buffered-commit timing described above. `make_stream_fifo` and `make_stream_pipeline`
need no changes of their own: both call `make_fifo` from inside their own `@hw_func`
bodies, so the attached model is picked up automatically.

**Capacity rounding.** Real hardware always rounds a requested `depth` up to a power of
two (`DEPTH_LOG2 = ceil(log2(depth))` in the spliced VHDL). The model computes
`capacity = 2 ** ceil(log2(depth))` in Python and enforces exactly that limit, so
`data_in_ready` deasserts at the same fill level as real hardware — not at the raw
requested `depth`.

**Entry-state/registered-output contract.** `data_out`/`data_out_valid`/`data_in_ready`
are computed from `self.q`'s state as of entry to `__call__` — i.e. as committed at the
last clock edge — before any push/pop for this cycle is applied. Push/pop only mutate
`self.q` for the *next* commit. Consequences:
- A same-cycle push is never visible via `data_out` that same cycle.
- A same-cycle pop never frees capacity for a same-cycle push (the `data_in_ready`
  returned this cycle was already computed from the pre-pop occupancy).

This mirrors the real FIFO's independent read/write pointers into the same memory,
without needing to model pointers or a memory array directly.

**Deliberate, documented deviation from cycle-accuracy.** The real
`pipelinec_fifo_fwft` entity has a one-word FWFT "prefetch register" that can
transiently hold one item beyond `2**DEPTH_LOG2`, and a 2-cycle (not 1-cycle)
push→visible latency when starting from empty. The model reproduces neither — it
backpressures at or before real hardware's true capacity limit, never after, which is
the safe direction for verifying overflow-avoidance and dataflow correctness (e.g.
`make_stream_pipeline`'s `MAX_IN_FLIGHT`-sized never-overflow invariant) without
attempting cycle-exact co-simulation against GHDL.

**Empty-queue placeholder.** `data_out` when `self.q` is empty is `sim_zero(data_t)` — a
correctly-typed but otherwise arbitrary value. Real hardware gives no guarantee about
`data_out`'s content when `data_out_valid` is 0 either; consumers must always gate on
`data_out_valid`, never read `data_out` directly.

---

## `Wire[T]` / `Input[T]` / `Output[T]` Global Wire Simulation

`Wire[T]` declarations at module level create `__annotations__` entries but no Python variable.
Inside `@MAIN` bodies, bare assignments like `main_a_out = r` would silently create local
variables, and `r = ~main_a_in` would raise `NameError`. The `_GlobalWireRewriter` step in
`_build_reg_sim_func` resolves this at decoration time.

### Global Wire State

```python
_sim_wire_state: dict[str, ...]   # wire name → current value (int or struct/array instance)
```

Wire names are singletons — not keyed by instance path. Every wire discovered by
`_discover_wire_names` (see below) is pre-seeded to a correctly-typed zero
(`_make_sim_zero(inner_ctype)`, recursing into struct/array fields) before any `@MAIN` runs,
so reading a wire that simply hasn't been driven yet this cycle returns that zero — never a
bare `0` for a struct/array-typed wire. Reading a wire name that was never discovered at all
(an actual bug, not a normal "not yet driven" state) raises `RuntimeError` rather than
silently returning `0` — this used to fall back to a bare `int 0`, which crashed confusingly
several frames away the first time a caller accessed a field on it (see `_discover_wire_names`
below for the discovery gap that used to trigger this).

```python
def _sim_wire_read(name: str)               # returns current value; records reader dependency; raises if name was never discovered
def _sim_wire_write(name: str, value)       # stores value as-is (struct types preserved)
```

`sim_reset()` clears both `_sim_reg_state` and `_sim_wire_state`.
`sim_wire_reset()` clears only `_sim_wire_state`.

Multi-MAIN simulation via `pypeline_sim.py` is required when global wires are used, since
all MAINs sharing wires must converge together each clock cycle.

---

## `pypeline_sim.py` — Multi-MAIN Clock-Cycle Simulation

CLI tool for running multi-MAIN designs. Normal usage goes through the `pypelinec` wrapper:

```
pypelinec my_design.py --sim --comb --run 1000
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
hardware function bodies, and `@sim_output`/`@sim_input` functions are also excluded from
`PARSE_FILE`'s unconditional top-level "elaborate every annotated function" sweep (so a
`@sim_input` function with a `-> T` return annotation — the return-value form's natural
signature — is never independently elaborated as an orphan function either). See
`PY_TO_LOGIC_DESIGN.md` for the elaborator side.

**Direct global-wire access.** `sim_output(fn)` routes `fn` through `_sim_type_wrap` (the
same machinery `@hw_func`/`@MAIN` use), so a `@sim_output` function's body may reference a
module-level `Wire[T]`/`Input[T]`/`Output[T]` directly by bare name (or `module.attr` for a
cross-module wire), not only receive values as passed-in arguments:

```python
out0: Wire[uint32_t]

@sim_output
def check_direct_read():
    print(int(out0))   # bare-name read, not passed in as an argument
```

This works from anywhere in the design — a top-level `@MAIN` body or a nested non-MAIN
helper — not just one fixed call site.

`_build_reg_sim_func`'s bailout check (whether to run `fn` unmodified vs. a rewritten body)
is keyed on whether *this function's own body* actually references a wire
(`_GlobalWireRewriter.modified`), not merely whether the defining *module* declares any
wire — this is what keeps every pre-existing `@sim_output` usage (none of which reference a
wire directly) running the exact same code path as before this capability was added.

**Caveat:** a `@sim_output` function that *does* reference a wire directly, and *also* uses
`global x; x = ...` to mutate an unrelated plain Python module-level variable, only sees
that mutation on its own subsequent calls — its rewritten body runs `exec`'d against a
detached snapshot of the module's globals dict, not the live module `__dict__`, so other
code reading the true module attribute externally (e.g. an `atexit`-registered cleanup
function) won't observe the change. Functions that don't reference a wire directly (the
common case) are unaffected — they always run unmodified, sharing the real live globals.

### `@sim_input` — Driving Simulation Inputs

`@sim_input` is the temporal/directional mirror of `@sim_output`: instead of firing once at
the *end* of a cycle (after convergence) to observe values, it fires once near the *start*
of a cycle, so its driven `Input[T]` value is available and stable throughout that cycle's
convergence rather than only after it.

Two call forms, usable interchangeably or together:

```python
in0: Input[uint32_t]

@sim_input
def in_global():
    in0 = python_stuff()          # direct-write form: body writes the wire itself

@sim_input
def in_return() -> uint32_t:
    return python_stuff()          # return-value form: caller assigns the return value

in1: Input[uint32_t]

@MAIN
def tb_inputs():
    in_global()
    in1 = in_return()
```

Like `@sim_output`, both forms may be called from anywhere in the design — not restricted
to one fixed location — though a dedicated testbench `@MAIN` (as above) is the typical
usage.

**Once-per-cycle caching.** The real body runs at most once per simulated clock cycle: the
first call anywhere (during delta-cycle convergence or the final pass) computes for real and
caches the result (keyed by function identity); every later call the same cycle is a pure
cache hit. This is required, not just an optimization — without it, a non-idempotent driving
value (a counter, a queue pop) would appear to change on every re-invocation (a `@MAIN` is
called at least twice per cycle: during convergence and again, unconditionally, in the final
pass), which both gives the wrong per-cycle value and can destabilize delta-cycle
convergence (or trip its 10,000-execution safety limit).

The cache (`pypeline._sim_input_cache`) is reset once per cycle: at the top of
`pypeline_sim.py`'s `_run_clock_cycle` for Layer 2, and on the outermost (non-reentrant)
`sim_call()` invocation for Layer 1, where each top-level call represents one clock cycle.
`sim_reset()` also clears it.

**Known limitation:** the cache key is the function identity only (no args/kwargs
awareness) — a `@sim_input` function called with different arguments within the same cycle
returns the first call's cached result regardless of the later call's own arguments.

### `sim_print` — printf-style Console + Hardware Output

`sim_print(...)` looks like `@sim_output` (same once-per-cycle/final-pass firing) but is
**dual-mode**, not sim-only: it also elaborates to a real VHDL `write(output, ...)`
statement in hardware, reusing PipelineC's C-frontend printf backend
(`C_TO_LOGIC.py`/`VHDL.py`) unmodified. Where `@sim_output`-decorated calls are invisible to
the hardware compiler (skipped entirely by the elaborator), `sim_print(...)` calls produce a
real submodule instance — see `PY_TO_LOGIC_DESIGN.md`'s "`sim_print` — printf-style Console
Output" section for the elaboration side.

```python
n: Reg[uint8_t]
sim_print(f"n={n} hex={hex(n)}")   # prints once per cycle, final pass only, AND
                                    # elaborates to hardware console output
```

Simulation-side, `sim_print` is intentionally trivial — a plain `print(s)` gated by
`_sim_converging`, since Python already evaluates the f-string into a final string *before*
`sim_print` is ever called:

```python
def sim_print(s):
    if _sim_converging:
        return SimVal(0)
    print(s)
    return SimVal(0)

sim_print._is_sim_print = True   # distinct from _is_sim_output -- see PY_TO_LOGIC_DESIGN.md
```

Correctness under both simulation layers follows directly from the existing
`_sim_converging` semantics documented above for `@sim_output`: always fires under plain
`sim_call()` (`_sim_converging` stays `False` there), fires only in the final pass under
`pypeline_sim.py`.

### `sim_print(..., debug=True)` — tagged prints for `pypeline_sim_debug.py`

`sim_print`'s optional `debug` keyword (default `False`) is not a distinct dual-mode builtin
mechanism of its own — when `debug=True`, it prefixes the message with a
`[SIM DEBUG PRINT: <abs path>:<N>]` tag (using the caller's frame, `sys._getframe(1)`) before
falling through to the same `print(s)`. The path is made absolute (`os.path.abspath`, not just a
basename) so the tag reads as clickable `path:line` text in terminals/editors that recognize
that shape:

```python
def sim_print(s, debug=False):
    if _sim_converging:
        return SimVal(0)
    if debug:
        frame = sys._getframe(1)
        tag = f"[SIM DEBUG PRINT: {os.path.abspath(frame.f_code.co_filename)}:{frame.f_lineno}]"
        s = f"{tag}: {s}"
    print(s)
    return SimVal(0)

sim_print._is_sim_print = True
```

It inherits `sim_print`'s own `_sim_converging` gating and hex/format behavior for free. The
elaboration side (`PY_TO_LOGIC_DESIGN.md`'s "`sim_print(..., debug=True)`" section) builds the
*same* tag text from `stmt.lineno`/`self.src_file` at elaboration time, rather than from a
runtime frame — both sides read line/file off the same source, so the tag is guaranteed
byte-identical between native and VHDL sim. That byte-identical tagging (plus `sim_print`'s
pre-existing format-string-sharing between native and VHDL rendering) is what lets
`pypeline_sim_debug.py` (`src/pypeline_sim_debug.py`) diff `debug=True` lines between the two
sims as plain strings, with no per-value normalization needed. See `docs/pypeline_guide.md`'s
`sim_print(..., debug=True)` section for usage.

### `sim_assert` / `sim_finish` — simulation control builtins

Two more dual-mode builtins alongside `sim_print`, same `_sim_converging`-gated shape and same
"real Python function stamped with a marker attribute" pattern — see `PY_TO_LOGIC_DESIGN.md`'s
"`sim_assert` / `sim_finish` — simulation control builtins" section for the elaboration/VHDL
side.

```python
def sim_assert(cond, msg=None):
    if _sim_converging:
        return SimVal(0)
    assert cond, (msg if msg is not None else "sim_assert failed")
    return SimVal(0)

sim_assert._is_sim_assert = True


class SimFinish(Exception):
    """Raised by sim_finish() to signal that simulation should stop now."""


def sim_finish():
    if _sim_converging:
        return SimVal(0)
    raise SimFinish()

sim_finish._is_sim_finish = True
```

`sim_assert` is just a gated Python `assert` — a failing condition raises `AssertionError`
exactly like it would outside simulation, with the same optional message. `sim_finish` can't
"just return" the way `sim_print`/`sim_assert` do, since stopping simulation is a control-flow
event, not a value or side effect the caller can react to — it raises `SimFinish`, a dedicated
exception (not `sys.exit`) so callers can catch it deliberately. `src/pypeline_sim.py`'s
`run_sim()` CLI driver catches `SimFinish` around its per-cycle `_run_clock_cycle(...)` call and
breaks out of the run loop cleanly (prints an early-stop message, still prints the final
elapsed-time summary) instead of treating it as a crash; `sim_call()`-based tests instead
typically assert `SimFinish` is raised directly (see
`src/tests/pypeline_tests/inst/sim_assert_finish_test.py`).

### Invocation via `pipelinec --sim --run N`

`pypeline_sim.py`'s multi-MAIN runner is also reachable through the main compiler driver,
`src/pipelinec`, without naming it explicitly:

```
python3 src/pipelinec my_design.py --sim --run 1000
```

is equivalent to `python3 src/pypeline_sim.py my_design.py --run 1000` **plus a full build
first when `--comb` is absent** (see the next section). Simulator selection is implemented in
`src/SIM.py`:

- `SET_SIM_TOOL(cmd_line_args, source_file)` defaults `SIM_TOOL` to the `pypeline_sim` module
  itself (used as a module-identity sentinel, the same pattern as `COCOTB`/`EDAPLAY`/etc.) when
  `source_file` ends in `.py` and none of the explicit backend flags were passed. Native sim is
  thus the *implicit* default for a `.py` design — there is no `--native` flag, because absence
  of every other simulator flag already selects it. `.c` sources keep defaulting to `EDAPLAY` —
  behavior is unchanged there.
- `DO_OPTIONAL_SIM(...)` calls `pypeline_sim.run_sim(...)` in-process (no subprocess) when
  `SIM_TOOL is pypeline_sim`, passing the final per-MAIN latencies
  (`SIM.GET_MAIN_FUNC_LATENCIES`) and the converged AUTOPIPELINE harvest
  (`SYN.HARVEST_AUTOPIPELINE_LATENCIES`) whenever a build's `parser_state`/timing params are
  available — all zeros/None on the comb path.
- `src/pipelinec` checks `SIM.NATIVE_SIM_SKIPS_BUILD(args)` right after tool selection — true
  when `SIM_TOOL is pypeline_sim` and **comb** simulation was requested (`--sim --comb`/
  `--sim_comb`, or `--no_synth`) — and if so calls `DO_OPTIONAL_SIM` and exits immediately —
  **no VHDL elaboration or synthesis happens on this path**, mirroring how `pypeline_sim.py`
  works standalone. A non-`--comb` `--sim` run instead
  falls through to the full build (path-delay measurement → throughput sweep → AUTOPIPELINE
  pin-and-confirm), and the native sim launches at the end with the discovered latencies
  emulated — the same "no `--comb` means pipelined" rule the VHDL simulators follow. (If no
  synthesis tool is installed, the run degrades to the comb zero-latency sim with a warning.)

Explicitly requesting `--cocotb --ghdl` (or any other backend) on a `.py` design is unaffected
and still goes through the full elaboration → VHDL → cocotb path described elsewhere in this
document and in `PY_TO_LOGIC_DESIGN.md` — the two simulation systems remain independent. There
is currently no `pipelinec` equivalent of `pypeline_sim.py`'s `--mode` flag; the native path
always runs at the default `strict` accuracy.

### Pipelined native sim (non-`--comb` `pipelinec --sim`)

Plain native sim runs the design's combinational Python at zero pipeline latency (only explicit
`Reg[T]`/FIFO state advances). A non-`--comb` `pipelinec --sim` run instead does the **full
build first** — path-delay measurement, the throughput sweep, and the AUTOPIPELINE
pin-and-confirm loop (`SYN_DESIGN.md` §6.5) — and then launches native sim with the discovered
per-instance pipeline latencies **emulated by delay lines wrapped around the unchanged
combinational Python**. Because the sliced/autopipelined logic is purely combinational, delaying
its outputs by N cycles is an exact model of the N register stages the sweep inserted — so the
native run stays cycle-accurate against the generated VHDL. This is verified end-to-end by
`src/pypeline_sim_debug.py` (which no longer needs `--comb`); the wireguard-fpga
encrypt/decrypt/shared syn testbenches all `MATCH` their pipelined GHDL builds cycle-for-cycle.

This section documents **how it is implemented**. Everything below lives in `src/pypeline.py`,
`src/pypeline_sim.py`, `src/SIM.py`, `src/SYN.py`, and `src/pipelinec`.

#### End-to-end control flow

1. `src/pipelinec`: the native-sim short-circuit (`SIM.NATIVE_SIM_SKIPS_BUILD`, which normally
   runs the sim and exits before any elaboration) is gated on `args.comb or args.no_synth`. A
   non-`--comb` `--sim` run therefore *falls through* to the full build path, exactly like a
   cocotb build would.
2. The build runs to completion, ending at `SYN.WRITE_FINAL_FILES` with the converged
   `multimain_timing_params`.
3. `SIM.DO_OPTIONAL_SIM(args.sim, parser_state, args, multimain_timing_params, ...)` dispatches
   to the `pypeline_sim` branch, which builds two latency maps and hands them to `run_sim`:
   - `main_latencies = SIM.GET_MAIN_FUNC_LATENCIES(parser_state, multimain_timing_params)` —
     `{main hw name → GET_TOTAL_LATENCY}` for every `@MAIN`.
   - `autopipeline_latencies, _ = SYN.HARVEST_AUTOPIPELINE_LATENCIES(parser_state, tpl)` —
     `{AUTOPIPELINE canonical_key → stage count}`. Harvested here (not read from
     `pypeline._autopipeline_latency_cache`) so it is populated even for designs whose Python
     never read `.latency`, where the pin-and-confirm loop never ran. Divergences are already a
     fatal driver error for any non-`--comb` `.py` build, so they are ignored here.
4. `run_sim(source_file, args.run, main_latencies=…, autopipeline_latencies=…)` installs the
   AUTOPIPELINE cache, re-imports the design fresh in sim mode, wires up the two emulation
   mechanisms, and runs the ordinary multi-MAIN cycle loop.

#### Cache install + module eviction (`run_sim`, `pypeline_sim.py`)

Before importing the design, `run_sim`:
- calls `pypeline.SET_AUTOPIPELINE_LATENCY_CACHE(autopipeline_latencies)` — so every
  `AUTOPIPELINE(func)` object *constructed during the import* captures its real `._latency` (set
  in `__init__` from the cache). This is what makes `.latency`-derived structure — most
  importantly `make_stream_pipeline`'s `fifo_depth = max(2, 1 + latency + 1)` — elaborate to the
  *same* shape the VHDL build's pin-and-confirm final pass produced. Get this wrong and the
  native FIFO would be a different depth than the hardware and diverge immediately.
- calls `_evict_design_modules()`, which deletes from `sys.modules` every module imported since
  `PY_TO_LOGIC._modules_before_first_parse` (the snapshot taken at the first `PARSE_FILE`). The
  build already imported the design's submodules **in non-sim mode** (with `_sim_active` False
  and an empty/older cache); without eviction, `_import_design`'s re-import would silently reuse
  those stale modules and the `@hw_func` decorators would never rebuild their sim bodies. The
  helper is a self-guarding no-op in every other context (pure native runs never import
  `PY_TO_LOGIC`; the comb short-circuit runs before any parse, leaving the snapshot `None`).

#### Mechanism A — AUTOPIPELINE call sites (`AUTOPIPELINE._sim_delay_line`, `pypeline.py`)

When `_sim_active and self._latency > 0`, `AUTOPIPELINE.__call__` stops being an identity
passthrough and routes through a per-call-site output **delay line** modelling
`out(t) = func(in(t − N))`, N = `self._latency`:

```
inst_path = _sim_current_inst_path()
committed  = _sim_reg_read(inst_path, _SIM_AP_DELAY_KEY, None)
if committed is None:                       # power-on: empty pipeline
    committed = [sim_zero(hw_return_type(self.func)) for _ in range(N)]
now = self.func(*args, **kwargs)            # the ordinary comb result, this cycle's inputs
_sim_reg_write(inst_path, _SIM_AP_DELAY_KEY, committed[1:] + [deepcopy(now)])
return deepcopy(committed[0])               # value pushed N cycles ago
```

Key implementation points:
- **Instance identity.** `__call__` pushes `("AUTOPIPELINE:" + self.canonical_key, call_loc)`
  onto `_sim_inst_stack` (the same stack `Reg[T]` and `@sim_model` use), so each call site gets
  its own delay line keyed by `_sim_current_inst_path()`. `canonical_key` distinguishes two
  *different* AUTOPIPELINE objects invoked from the same source line (e.g. a loop over
  factory-produced pipelines whose inner funcs share a `__qualname__`); it is already computed
  because a non-empty cache forced it in `__init__`.
- **Convergence safety.** The read (`_sim_reg_read`) always returns the state committed at the
  last clock edge, never the write buffer; the write (`_sim_reg_write`) goes into the buffer
  while the per-cycle buffer is open. So during a cycle's delta-convergence the output
  (`committed[0]`) is input-independent — it cannot cause churn — and re-evaluations only rewrite
  the buffered shift, last-write-wins. `_sim_reg_flush_buffer` commits the **final pass's** shift
  as the clock edge. This is the identical discipline `_call_sim_model` uses for class models.
- **Warm-up.** The first N outputs are typed zeros of `func`'s return type, matching hardware's
  empty pipeline.
- **Aliasing.** Both the pushed `now` and the returned `committed[0]` are `deepcopy`d: `func` may
  return an object aliasing its input, and `committed[0]` is handed to every re-evaluation in the
  cycle, so caller mutation must not corrupt the committed line.
- The surrounding elastic handshake of `make_stream_pipeline` (its `ready`/in-flight `Reg[T]` and
  output FIFO) is **not** emulated here — those are ordinary stateful sim constructs that native
  sim already models exactly. Only the feed-forward AUTOPIPELINE core inside gets the delay line.

#### Mechanism B — naturally-pipelined pure MAINs (write-side delay)

A **pure** `@MAIN` (no `Reg[T]`/`Feedback[T]` — checked via the `wrapper._pypeline_has_state`
flag set in `_sim_type_wrap`) that the sweep sliced to latency N > 0 gets *write-side* delay
emulation. `run_sim` maps each final MAIN hw name back to its registry function via
`PY_TO_LOGIC._hw_func_name(prefix, fn.__name__)` (prefix `None` for the top file loaded as
`"pypeline_design"`, else the sub-module name with dots→underscores — the same mangling
elaboration uses) and fills:

```
pypeline._sim_pipelined_main_info[fn] = {"latency": N, "queue": deque(), "collector": []}
```

(An empty dict = feature off, one truthiness test on the wire-write hot paths. Stateful MAINs
are skipped — see Limitations.) The delay is applied to the MAIN's **global-wire writes**:

- While a pipelined MAIN executes (`_sim_current_main` is it), `_sim_wire_write` /
  `_sim_wire_lens_write` append `(wire_name, lens_path, value)` to that MAIN's `collector`
  instead of touching `_sim_wire_state`. The lens path is preserved so partial/field writes
  replay leaf-wise later without clobbering another writer's leaves of the same wire.
- `_sim_wire_reset_claims` (the per-invocation zeroing that models hardware's implicit
  mux-to-zero for every leaf a function drives) **also** diverts into the collector as
  zero-valued entries. This is essential: it must **not** touch `_sim_wire_state`, or it would
  wipe the N-cycles-old values `_sim_apply_delayed_writes` placed there this cycle.
- Claim *recording* (`_sim_wire_claims`) stays live even when diverted, because the diverted
  reset path reads it to know which leaves to zero.

The per-cycle sequence in `_run_clock_cycle` (`pypeline_sim.py`):

1. **Apply** — for each pipelined MAIN whose queue holds ≥ N sets, `popleft()` the oldest and
   replay it onto `_sim_wire_state` via `_sim_apply_delayed_writes` (ordered lens-sets). During
   warm-up (queue shorter than N) nothing is applied, so the wires hold their typed-zero reset
   values — hardware's empty pipeline. This runs *before* convergence; the delayed values are
   cycle-constant and every MAIN starts queued each cycle, so no requeue is needed.
2. Convergence loop and final pass run as usual. Reads of the pipelined MAIN's output wires see
   the step-1 delayed values; the MAIN's own writes this cycle go into its collector.
   `_sim_current_main` is now set around the **final pass** too (previously only the convergence
   loop set it), so final-pass writes divert correctly.
3. `_sim_reg_flush_buffer()` — the clock edge for ordinary `Reg[T]`.
4. **Push** — append `deepcopy(collector)` to each pipelined MAIN's queue and clear the
   collector. The deepcopy prevents later-cycle mutation from aliasing queued values.

Ordered replay makes conditional/partial writes exact: within a cycle the collector accumulates
`[reset-zeros, writes]` from every convergence iteration and the final pass, in order, so the
last (final-pass) `[reset-all-claimed-leaves, then-actual-writes]` fully determines the replayed
state — a leaf whose write condition ended up false is left at its reset zero, matching the
hardware mux.

**Why write-side, not read-side.** Delaying writes (rather than shadowing each reader N cycles
back) needs no read-set discovery or snapshotting, and it keeps `sim_assert`s *inside* the
pipelined MAIN evaluating on real current values (no spurious warm-up failures). The cost is the
per-wire-uniformity assumption in Limitations below.

#### Driver-side correctness fixes this required

Two pre-existing behaviours in the build had to change so that the latency the native sim
emulates provably equals the latency the VHDL was built with:

- **`HARVEST_AUTOPIPELINE_LATENCIES` invalidates every `TimingParams` memo first.** The sweep
  planner mutates submodule `_slices` *after* container totals were first memoized, so a stale
  memoized `GET_TOTAL_LATENCY` could report e.g. 10 while the entity actually written (and
  confirmed by synthesis) is 26 clocks. The harvest now clears all caches before walking.
- **The pin-and-confirm loop no longer stops on "timing met" alone.** It stops only when the
  post-confirmation harvest *equals* the latencies this pass's Python consumed. Realizing the
  seeded fractional slices hierarchically (into pipelined built-in `div`/`mult` entities with
  their own stage granularity) can change an instance's total latency even on a *passing*
  confirmation; stopping then would emit VHDL whose real depth contradicts every
  `.latency`-derived constant baked into it — and desync this emulation. An extra pass (typically
  pass 3) re-elaborates with the realized numbers and converges.

#### Limitations (read before trusting a pipelined cycle diff)

The emulation is a **black-box output-delay** model of a feed-forward, initiation-interval-1
pipeline. It is exact within that model, but the following are genuine boundaries. Two of them
are **detected and turned into hard errors** (loud `sys.exit`/`RuntimeError` — the design is
refused rather than silently mis-simulated); the rest are constraints on how you write probes:

- **Feed-forward II=1 only.** The model assumes the sliced/autopipelined logic accepts one input
  per cycle with no internal stall. This is exactly what AUTOPIPELINE and the sweep produce
  (combinational logic cut into register stages), so it always holds for their output — but the
  delay line is not a general model of a hand-built multi-cycle or back-pressured pipeline.
  (An `AUTOFSM` call site has initiation interval N, not 1, and is deliberately *not* modelled
  by this delay line — it gets its own register-level model instead; see below.)
- **Warm-up data is not comparable.** VHDL's added pipeline registers are declared with no
  initializer and read `'U'` in GHDL during the first N cycles; native delay lines start at typed
  zeros. Any `sim_print(debug=True)` used for a pipelined cycle diff must be **valid-gated** — a
  valid bit carried through the same pipeline gates false in both sims during warm-up (`'U'` in
  VHDL, `0` in native), so gated probes agree from the first meaningful cycle; an un-gated data
  print can never match during warm-up.
- **[HARD ERROR] A pipelined pure MAIN writing more than one separate global wire.** Mechanism
  B delays *all* of a pure MAIN's output wires by that MAIN's single total latency N. But the
  generated VHDL emerges each **separate** write-only global wire at *its own* "fully driven
  last" stage — its own cone depth — not at the module's total latency. So a pure pipelined MAIN
  that writes two separate wires of different depth (e.g. a deep `heavy(heavy(x))` result wire
  and a shallow passthrough wire) would **diverge** on the shallower wire: native over-delays it
  to N, VHDL emerges it earlier. Verified empirically — for a MAIN with a depth-10 deep wire and
  a ~0-depth shallow wire, at the cycle the deep wire's `seq=0` emerges, native reports `shallow
  seq=0` while VHDL reports `shallow seq=10` (a 10-cycle skew, exactly N − depth\_shallow). Since
  native sim has no per-wire stage information at sim time, it cannot tell a divergent pair from
  two coincidentally-equal-depth wires, so `SIM.CHECK_PIPELINED_NATIVE_SIM_SUPPORTED` **refuses
  the design** (`sys.exit`) whenever a pipelined pure MAIN writes more than one global wire —
  conservative, but never silently wrong. **Fields carried in one struct wire are fine and are
  the fix**: VHDL registers the whole struct together to its deepest field's stage, so all
  fields emerge aligned in both sims (this is exactly what the shipped
  `native_vs_vhdl_pipelined_main_test` does — data + seq + valid in one struct — and it matches
  cleanly). Bundle a pipelined MAIN's co-timed outputs into one struct wire (which also aligns
  them in hardware), or build with `--comb`. A precise (non-conservative) version would export
  each wire's end-stage from the pipeline map and give it its own delay line — left as future
  work. Mechanism A does not have this issue: an AUTOPIPELINE core is a single function whose
  whole return value, struct included, is delayed together.
- **[HARD ERROR] `sim_print(debug=True)` inside a pipelined comb region.** A `debug=True` print
  fires in native sim at the cycle its inputs arrive (stage 0), but in VHDL at whatever pipeline
  stage the retiming placed that logic — so it cannot be cycle-compared. If such a print executes
  inside a naturally-pipelined pure MAIN or an AUTOPIPELINE core, native sim raises a
  `RuntimeError` (`_sim_check_debug_probe_not_in_pipeline`) naming the call site, rather than
  emit a line that would silently mis-compare. **Cycle-accurate probes must live in stateful
  (0-latency) MAINs** reading the pipeline's output wires. (`sim_assert` inside pipelined comb is
  *not* an error — it checks content, which is correct in both sims, not cycle alignment; and
  plain `sim_print(...)` without `debug=True` is fine anywhere, since it is never cycle-compared.)
- **Stateful MAINs are not delayed.** A MAIN with `Reg[T]`/`Feedback[T]` is never sliced by the
  sweep (its state fixes its own cycle timing); if the build ever reports a nonzero latency for
  one, `run_sim` ignores it with a warning rather than stacking a write delay on top of the
  MAIN's explicit registers. `@sim_input`/`@sim_output` stimulus should likewise be driven from
  stateful MAINs — inside a pipelined MAIN it would be delayed with everything else.
- **Same source line, multiple AUTOPIPELINE instances.** Two calls of the *same* AUTOPIPELINE
  object on one physical source line share one delay line (identical `_sim_inst_stack` key)
  unless `SIM_TRACE_LOCATIONS=True` restores column-level call identity — the same pre-existing
  limitation multi-instance `Reg[T]` designs already carry.
- **`sim_finish` cycle prints are racy across sims.** GHDL gives no ordering guarantee between a
  write process and `std.env.finish` on the same clock edge, so a design must not emit
  `debug=True` prints on the cycle it calls `sim_finish()` — quiesce prints one cycle earlier
  (the shipped `native_vs_vhdl_*` test designs gate their final prints with a `done` register).
  This is a testbench-authoring rule, not a native-sim inaccuracy, but it governs whether a diff
  reads clean. Broken, it does not raise or warn — the print simply never appears in the VHDL log
  (present in native sim, absent in VHDL); see `src/tests/pypeline_tests/inst/
  sim_finish_debug_print_race_test.py` for a direct reproduction.
- **cocotb's own pass/fail verdict, not `make`'s exit code.** `std.env.finish` (from
  `sim_finish()`) terminates GHDL out from under cocotb's still-awaiting test coroutine; cocotb
  cannot distinguish that from a real crash on its own, and its makefile cannot set an exit code
  at all (`Makefile.inc`: *"since we can't set an exit code from cocotb"*). `src/COCOTB.py`
  generates the `--run all` testbench with `expect_error=SimFailure` so cocotb's regression
  manager scores a clean `sim_finish()` stop as a genuine PASS, then reads the verdict from
  cocotb's own `results.xml` rather than `make`'s exit code or any console-text heuristic. A real
  failure (e.g. a firing `sim_assert`) still fails the build — GHDL itself exits nonzero in that
  case, which `make` (and `COCOTB.DO_SIM`) propagates. See `COCOTB.CHECK_COCOTB_RESULTS`'s
  docstring and `src/tests/pypeline_tests/inst/cocotb_verdict_test.py`, the regression guard for
  both halves.
- **`VHDL_SOURCES` is a GHDL `@file` response file, not an inlined list.** `COCOTB.GET_MAKEFILE_TEXT`
  sets `VHDL_SOURCES += @$(PIPELINEC_VHDL_FILES_TXT)` rather than the more obvious
  `$(shell cat vhdl_files.txt)`. cocotb's `Makefile.ghdl` writes its `analyse` target as one
  backslash-continued logical recipe line, so `make` hands the whole thing to the shell as a
  *single* argv string; Linux caps any one argv/envp string at `MAX_ARG_STRLEN`
  (`PAGE_SIZE * 32` = 131072 bytes here), independent of the much larger overall `ARG_MAX` — a
  large design's own VHDL file list, once every absolute path is inlined, can exceed that on its
  own (`make[1]: execvp: bash: Argument list too long`, failing before GHDL even starts). GHDL's
  `@file` response-file syntax is whitespace-split like a normal argv, so the existing
  space-separated `vhdl_files.txt` works unmodified as one. The `@...` token names no real file,
  so it must be declared `.PHONY` (a phony target is never "missing") or `make` refuses it as an
  unbuildable prerequisite; real dependency tracking moves to `CUSTOM_COMPILE_DEPS`, which
  cocotb's `Makefile.inc` also wires into `analyse`. Every other GHDL/yosys call site with the
  same shape (`OPEN_TOOLS`/`CXXRTL`/`PYRTL`/`CC_TOOLS`/`DEVICE_MODELS` writing a
  `yosys -p '<huge ghdl file list>'` shell one-liner) hits the identical limit and is fixed the
  same way via `OPEN_TOOLS.WRITE_YOSYS_SCRIPT`, which writes the commands to a `.ys` script file
  and passes `-s <path>` instead of `-p '<commands>'` — a script file's contents are never one
  exec argv, regardless of length. See `src/tests/pypeline_tests/inst/long_file_list_arg_len_test.py`.

#### AUTOFSM call sites (non-`--comb` `--sim`)

`AUTOFSM(func)` produces a resource-shared state machine with initiation interval
N and a fixed N-cycle latency (see [`AUTOFSM_DESIGN.md`](AUTOFSM_DESIGN.md)),
which the output-delay model above cannot represent. It is emulated separately by
`AUTOFSM._sim_fsm` in `pypeline.py`.

Rather than modelling the FSM's *behaviour* abstractly, the emulation models the
generated hardware's **registers** — the same state register, input latch and
output registers the code generator declares — and steps them the same way:

```python
out = out_stream_t(data=st["out_data"], valid=st["out_valid"])   # committed regs
nxt = {"st": st["st"], "in": st["in"], "out_data": st["out_data"], "out_valid": 0}
if st["st"] == 0:
    if valid:                       # accept only while idle => II == latency
        nxt["in"] = deepcopy(data)
        nxt["st"] = 1
elif st["st"] >= n_states:          # last execution state: result lands in the regs
    nxt["out_data"] = deepcopy(self.func(st["in"]))
    nxt["out_valid"] = 1
    nxt["st"] = 0
else:
    nxt["st"] = st["st"] + 1
```

Cycle accuracy against the VHDL is therefore structural rather than an argument
to be checked separately. The commit discipline is the same as
`_sim_delay_line`'s and `_call_sim_model`'s: the returned value comes only from
state committed at the last clock edge (so repeated evaluation during
convergence cannot churn), the next state is written into the buffer (last write
wins, only the final pass lands at `_sim_reg_flush_buffer`), warm-up is typed
zeros from `sim_zero`, and both directions are deep-copied against aliasing.

The whole function is evaluated in one go in the last state rather than
per-state: the FSM's decomposition into states is a hardware implementation
detail, invisible at the call-site boundary this model has to match.

Schedules reach the simulator exactly the way AUTOPIPELINE latencies do —
`SIM.DO_OPTIONAL_SIM` → `run_sim(autofsm_schedules=...)` →
`SET_AUTOFSM_SCHEDULE_CACHE` **before** `_import_design`, because the tag
captures its schedule at construction and any `.latency`-derived Python sizing
must elaborate the same way it did for the build. With no schedule installed
(plain native sim, `--comb`) the call site is a zero-latency passthrough.

Nothing in this model changed when AUTOFSM gained its area search, latency cap
and finer decomposition, and that is by design: every one of those decides *what
hardware implements the function*, and this model deliberately does not describe
the hardware — it describes the boundary. The call site accepts while idle,
pulses `valid` `.latency` cycles later, and computes `func`. Which operations
share which unit, how many states that takes and how far down the operator
hierarchy the scheduler went are all invisible from here. The only thing the
simulator reads out of a schedule is `latency`, and a `max_latency=` cap changes
nothing except which number that is.

`self_check_autofsm_test.py` is run in both native and GHDL simulation, at
latency 0 and at real latency, which is what checks this model against the
hardware in practice.

#### `pypeline_sim_debug.py` under non-`--comb`

For non-`--comb` args the tool first does a single build-only pass (no `--sim`) into a
shared `out_dir` -- the full throughput sweep + AUTOPIPELINE pin-and-confirm, paid once
-- then points **both** the native and VHDL `--sim` invocations at that same now-warm
`out_dir` and runs them **concurrently**. Each re-runs `pypelinec`'s build path
internally, but with the sweep already warm (existing VHDL/log/timing-params results in
`out_dir`, plus the repo-level path-delay / pipeline-min-period caches) it converges
fast, and both are guaranteed to reach the same discovered latencies as the build phase
-- a prerequisite for a meaningful cycle diff -- with no concurrent cache-write race,
since the expensive discovery work already happened in the single build-only pass. It
detects non-`--comb` mode by scanning the forwarded args for
`--comb`/`--sim_comb`/`--no_synth`; comb runs skip the build-only pass and run both
sims concurrently in separate `--out_dir`s from the start.

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
  multi-file designs supported (`_discover_wire_names` recursively scans *every* imported
  sub-module transitively, including "pass-through" modules that declare no `Wire[T]` of their
  own but import ones that do — e.g. a module whose only job is cross-module wiring between
  other modules' globals). Wire sim-keys are bare names (no module prefix); unique wire names
  across sub-modules assumed.
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
- **`Input[T]` wires** — initialized to zero at `sim_reset()`; driving a per-cycle value is
  supported via `@sim_input` (see above).
- **Raw VHDL (`vhdl(...)`)** — simulable only with an attached `@sim_model`
  (see `sim_model` section above); without one, calling the function in simulation raises
  `NotImplementedError`. `make_fifo` attaches a `collections.deque`-based FWFT model (see
  `make_fifo` Simulation Model below), so it and, transitively, `make_stream_fifo`/
  `make_stream_pipeline` are now simulable.
- **`sim_model` class models and nested `Reg[T]` hw_funcs inside Layer-1 `Feedback[T]`
  loops** — commit once per outermost `sim_call`, not once per convergence iteration
  (fixed 2026-07-11: the outermost `sim_call` now opens a register-write buffer for its
  whole duration, the same machinery `pypeline_sim.py` uses per clock cycle; see
  `sim_call` above). Model side effects still multi-fire during convergence in both
  layers — keep model bodies side-effect-free or check `_sim_converging`.

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

The same fast-path-set gate now also covers `__lt__`/`__le__`/`__gt__`/`__ge__` (ops
`"LT"`/`"LTE"`/`"GT"`/`"GTE"`) and `__truediv__`/`__mod__` (ops `"DIV"`/`"MOD"`), added when
the soft-operator library made these dispatchable for the first time (see
`pypeline_DESIGN.md`'s Operator Registry / Soft Operator Library sections). Structural
fidelity was chosen over raw sim speed for these: when `PY_TO_LOGIC.PARSE_FILE` or
`pypeline_sim.py`'s `_import_design` runs (i.e. anywhere outside a bare unit test that
imports `pypeline` directly and never touches a design file), the default soft replacements
for int `NEGATE`/compare/`DIV`/`MOD`/variable-shift are registered globally before the
design is elaborated or simulated — so native sim for those ops now runs the same unrolled
per-bit Pypeline HDL hardware runs, not a single Python operator. Full `run_all.py -j 4`
wall time was re-measured after this change and showed no regression outside normal run
variance — the fast-path-set check keeps unregistered ops on the direct-computation branch,
and the categories most exercising these ops (`native_sim`, `elab`) stayed in the same few-
seconds-per-test range as before.

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

`src/tests/pypeline_tests/native_sim_tests.py` covers the simulation behaviors described in this
document directly — `Reg[T]`/`Feedback[T]`/`Wire[T]` simulation, bit-accurate arithmetic
(`SIM_STRICT_ARITH`), and `sim_call()` — by running the plain-`python3` test files under
`inst/` (e.g. `pypeline_test.py`, `bit_math_test.py`, `reg_init_test.py`), each of which
asserts on `sim_call()` results and exits non-zero on failure. It also covers the
multi-MAIN clock-cycle runner (`pypeline_sim.py` § above) via `global_wires_sim_test.py`,
invoked as `python3 src/pypeline_sim.py inst/global_wires_sim_test.py --run 10`.

`sim_model` is covered by `inst/sim_model_test.py`, registered twice: as a plain-`python3`
run (both model forms on vhdl-bodied accumulators, two-call-site instance independence,
return-width casting, `sim_reset()` re-instantiation, `copy_state=False`, model override
of a normal hw_func, attachment error cases, model-less `vhdl(...)` still raising) and as
`sim_model_convergence_test` under the multi-MAIN runner (`--run 20`), where a checker
MAIN asserts a numpy class model's state advances exactly once per cycle despite being
re-evaluated with mid-cycle-changing wire inputs from a later-queued driver MAIN.

`make_fifo`'s `_FifoFwftModel` is covered by `inst/fifo_test.py` (plain `sim_call`: empty
behavior, FWFT push/pop order, backpressure and overflow-drop at the rounded-up capacity,
same-cycle push+pop ordering, and a multi-cycle reference-model soak against an
independent plain-Python `deque`), `inst/stream_fifo_test.py` and
`inst/stream_pipeline_test.py` (integration through the `stream_t` wrappers — the latter
including a steady-drain and a stall-and-resume backpressure scenario, both checked
against `sim_call(div_inv, x)` as ground truth), and `fifo_sim_model_convergence_test`
(`inst/fifo_sim_model_test.py` under `--run 16`), which mirrors
`sim_model_convergence_test`'s pattern to prove the FIFO's deque state doesn't double-push
per cycle under wire convergence.

The `pipelinec --sim --run N` § above is covered by `pipelinec_native_sim_test`, which reruns
`global_wires_sim_test.py` through `pipelinec`'s CLI (`pipelinec inst/global_wires_sim_test.py
--sim --comb --run 10`) instead of invoking `pypeline_sim.py` directly — this isolates the
`SIM.SET_SIM_TOOL`/`DO_OPTIONAL_SIM` dispatch wiring from the simulator itself, which the other
`global_wires_sim_test` entry already covers. (Every native_sim-category `pipelinec` invocation
passes `--comb` — without it, `--sim` now triggers a full build first.) The pipelined native
sim § is covered by `native_pipelined_sim_test` (in `synth_tests.py`: non-`--comb` build +
latency-emulated native self-checks of `self_check_stream_pipeline_test.py`) and, in the
`native_vs_vhdl_sim` category, `pypeline_sim_debug.py` cycle-diff tests including
`native_vs_vhdl_ap_test` and `native_vs_vhdl_pipelined_main_test`, which MATCH-compare emulated
native sim against real pipelined GHDL for an AUTOPIPELINE call site and a naturally-pipelined
pure MAIN respectively.

The opt-in Divider QoR harness adds a different end-to-end check: it compiles the exact final
`vhdl_files.txt` after autopipelining and verifies stream ordering, bubbles, divide-by-zero,
valid latency, input readiness, and pipeline flush under continuous traffic. It deliberately
does not claim output-backpressure coverage because that fixture has no output-ready port.
See [pypeline_TESTS.md](pypeline_TESTS.md) for its commands and acceptance limits. This is a
generated-VHDL verification tier, not evidence about the native delay-line simulator. The
accepted gate and arithmetic artifacts pass 141 ordered vectors at 31- and 32-cycle latency,
respectively; their timing/cell claims come from immutable remaps of those same VHDL bytes.

```
python3 src/tests/pypeline_tests/native_sim_tests.py            # just the sim tests
python3 src/tests/pypeline_tests/native_sim_tests.py -j 4
python3 src/tests/pypeline_tests/run_all.py --category native_sim
```

Aside from `pipelinec_native_sim_test` above (which exits before elaboration even though it
invokes `pipelinec`), no `pipelinec` elaboration/synthesis happens in this script. See
[pypeline_TESTS.md](pypeline_TESTS.md) for the full category breakdown (`elab`,
`elab_introspect`, `unit`, `synth`, `build_report`, `native_vs_vhdl_sim`, `known_issues`), the
`run_all.py` CLI, and the `native_vs_vhdl_sim` probe-placement rules.
