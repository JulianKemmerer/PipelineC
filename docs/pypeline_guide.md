# Pypeline HDL Language Guide

Pypeline is the Python front-end for PypelineC.

For getting started information see the [README](README.md).

## Table of Contents

**Part I — The language**

1. [What is Pypeline?](#what-is-pypeline)
2. [Worked Example: VGA Test Pattern](#worked-example-vga-test-pattern)
3. [Digital Logic Basics](#digital-logic-basics)
4. [Python vs Hardware Execution](#python-vs-hardware-execution)
5. [Simulation](#simulation)
6. [Top-Level Entry Points](#top-level-entry-points)
7. [Your First Hardware Function](#your-first-hardware-function)
8. [Calling Functions](#calling-functions)
9. [Registers: `Reg[T]`](#registers-regt)
10. [Feedback Wires: `Feedback[T]`](#feedback-wires-feedbackt)
11. [Bit Manipulation](#bit-manipulation)
12. [Basic Types](#basic-types)
13. [Parametric Hardware with Factory Functions](#parametric-hardware-with-factory-functions)
14. [Factory-Generated Types](#factory-generated-types)
15. [Custom Operators](#custom-operators)
16. [Global Signals](#global-signals)

**Part II — Temporal behavior**

17. [Tool-Chosen Implementation: `AUTOPIPELINE(...)` and `AUTOFSM(...)`](#tool-chosen-implementation-autopipeline-and-autofsm)
18. [Multi-Cycle Paths: `MULTI_CYCLE[...]`](#multi-cycle-paths-multi_cycle)

**Part III — Ports and streams**

19. [Keep-Tagged Lanes: `kept_data_bus_t`](#keep-tagged-lanes-kept_data_bus_t)
20. [N-Dimensional Stream Fragments: `ndarray_fragment_t`](#n-dimensional-stream-fragments-ndarray_fragment_t)
21. [Streams: `stream_t`](#streams-stream_t)
22. [Bidirectional Ports: `@interface`](#bidirectional-ports-interface)
23. [AXI-Stream: `axis_t`](#axi-stream-axis_t)
24. [FIFOs: `make_stream_fifo`](#fifos-make_stream_fifo)
25. [Pipelined Stream Wrappers: `make_stream_pipeline`](#pipelined-stream-wrappers-make_stream_pipeline)
26. [Multi-Cycle Stream Wrapper: `make_valid_ready_mcp`](#multi-cycle-stream-wrapper-make_valid_ready_mcp)

**Part IV — Escape hatches**

27. [Raw VHDL Passthrough: `vhdl()`](#raw-vhdl-passthrough-vhdl)
28. [Just-Wires Synthesis Hint: `@wires`](#just-wires-synthesis-hint-wires)

**Part V — Reference**

29. [Simulation Reference](#simulation-reference)
30. [DSP: Filters & Signal Conditioning](#dsp-filters--signal-conditioning)
31. [Limitations / Not Yet Supported](#limitations--not-yet-supported)

---

## What is Pypeline?

Pypeline lets you describe digital hardware using Python syntax.
A design file is a regular Python module.
Module-level code (constants, type definitions, helper factories) runs as plain Python at
compile time.
Functions whose arguments and return value carry type annotations describe hardware
circuits; the compiler translates their bodies into logic and emits VHDL via the
PypelineC backend.

The mental model: **a hardware-annotated function is a circuit module**,
not a subroutine.
Its inputs and outputs are wires, its local variables are signals, and every line of its
body describes combinational or sequential logic.

Pure (combinational) functions can be automatically pipelined by PypelineC to meet timing —
you write the dataflow, the tool inserts pipeline registers wherever needed to hit the
target clock frequency.

Pypeline is actively evolving; see [Limitations](#limitations--not-yet-supported) for known gaps before you dive in.

---

## Worked Example: VGA Test Pattern

This is a complete, real design example. Each piece used here (registers,
bit-slicing, structs, top-level entry points, global wires, simulation hooks, factory
functions) is explained in its own section later in this guide; this walkthrough links to
each of them at first use.

See the full design that generates a colour test pattern on a VGA monitor at `examples/pypeline/vga_test_pattern.py`.

### Imports

```python
from pypeline import *

import board.arty.part35t          # sets PART for the Arty A7-35T
import board.arty.vga_pmod_ja_jb as board_vga   # board-level output wires

from vga.types import vga_timing_signals_t, vga_12bpp_t
from vga.timing import make_vga_timing, VGA_640_480

vga_timing = make_vga_timing(VGA_640_480)  # factory: produces a timing generator function
```

`PART(...)` (called inside `board.arty.part35t`) sets the FPGA target device — see
[Top-Level Entry Points](#top-level-entry-points).
`vga_timing_signals_t` and `vga_12bpp_t` are struct types — see [Basic Types](#basic-types).
`make_vga_timing` is a factory closure — see
[Parametric Hardware with Factory Functions](#parametric-hardware-with-factory-functions).
Calling it with a resolution spec produces a hardware function (`vga_timing`) that
generates VGA sync signals and pixel coordinates.

### Combinational pixel function

```python
def test_pattern(sig: vga_timing_signals_t) -> vga_12bpp_t:
    r: uint4_t = sig.pos.x[7:4]          # upper 4 bits of X coordinate
    g: uint4_t = sig.pos.y[7:4]          # upper 4 bits of Y coordinate
    b: uint4_t = sig.pos.x[3:0] ^ sig.pos.y[3:0]   # XOR diagonal
    out_r: uint4_t = 0
    out_g: uint4_t = 0
    out_b: uint4_t = 0
    if sig.active:          # only output colour inside the visible region
        out_r = r
        out_g = g
        out_b = b
    return vga_12bpp_t(r=out_r, g=out_g, b=out_b, hs=sig.hsync, vs=sig.vsync)
```

- `sig.pos.x[7:4]` — bit-slice of the X pixel coordinate; see
  [Bit Manipulation](#bit-manipulation).
- `sig.active` — hardware `if`, synthesised as a MUX: colour inside the image, black
  outside; see [Your First Hardware Function](#your-first-hardware-function).
- `vga_12bpp_t(...)` — compound struct initialiser; see [Basic Types](#basic-types).

### Top-level entry point

```python
@MAIN(vga_timing.pixel_clk_mhz)   # frequency comes from the resolution spec
def vga_test_pattern():
    sig = vga_timing()             # call the timing generator (stateful — contains registers)
    px  = test_pattern(sig)        # compute pixel colour (combinational)
    board_vga.vga_pmod = px        # drive the board's output wire
    capture_pixel(sig, px)         # @sim_output — invisible to the hardware compiler
```

`@MAIN(mhz)` declares a top-level entry point with a frequency constraint — see
[Top-Level Entry Points](#top-level-entry-points).
`vga_timing()` is a hardware function call (submodule instance) that contains
registers — see [Registers: `Reg[T]`](#registers-regt).
`board_vga.vga_pmod` is a `Wire[T]` declared in the imported board file; assigning to it
drives the FPGA pins — see [Global Signals](#global-signals).

### Simulation display

```python
@sim_output
def capture_pixel(sig, px):
    # accumulate pixels into a numpy array and refresh a matplotlib window
    ...
```

`@sim_output` marks this as simulation-only — see [Simulation](#simulation).
The hardware compiler skips it entirely; `pypeline_sim.py` calls it once per clock cycle
after convergence.

### Running the simulation

```
pypelinec examples/pypeline/vga_test_pattern.py --sim --comb --run 420000
```

One frame of 640×480 video at 25 MHz = 800 × 525 = 420 000 cycles.
A matplotlib window appears and fills in as the simulation runs.

### Synthesising for the FPGA

Run `pypelinec` on the design file (see the main PypelineC documentation for build steps).
The `PART()` call and `@MAIN(mhz)` frequency constraint are forwarded to Vivado.

### Reference: HDL concept → Pypeline syntax

For readers coming from a traditional HDL (or the PipelineC C front end):

| HDL concept | Pypeline syntax |
|---|---|
| Flip-flop | `Reg[T]` |
| Wire | `Wire[T]`, or a plain local variable |
| Clock domain | `@MAIN` |
| Module | `@hw_func` (or any type-annotated function) |
| Input / output port | `Input[T]` / `Output[T]`, or a function argument / return value |
| Combinational logic | A plain function (no `Reg`/`Feedback`) |
| State machine | `AUTOFSM(...)`, or a hand-written `Reg[state_t]`-based FSM |

### Reference: Python construct → hardware meaning

This is the positive-space complement to [Limitations](#limitations--not-yet-supported)
(the negative space) — cross-reference the two rather than re-deriving restrictions here.

| Python construct | Meaning | Restriction |
|---|---|---|
| `if` / `else` | Multiplexer selecting between both elaborated branches | No early return from inside a branch |
| `for range(N)` | Unrolled N times at compile time | `N` must be a compile-time constant |
| `while` | Unrolled at compile time | Condition must be compile-time evaluable |
| Function call | Instantiates a hardware submodule | Each call site is a distinct instance |
| Assignment | Drives a wire/register | — |
| Ternary (`a if c else b`) | Same MUX as `if`/`else`, as an expression | — |
| `return` | Declares the module's output port(s) | At most one, as the final top-level statement |
| Augmented assignment (`+=`, etc.) | Sugar for `x = x <op> y` | — |
| `and` / `or` | Boolean combine, each operand normalised to `uint1_t` | Result is always `uint1_t` |

---

## Digital Logic Basics

This section is a brief primer for readers new to hardware description languages.
Skip ahead if you already know VHDL or Verilog.

### The clock

Digital circuits are driven by a periodic clock signal.
Every clock cycle — typically nanoseconds — all flip-flops sample their inputs and latch
new values simultaneously.
Everything that happens *between* two clock edges is **combinational logic**:
pure boolean/arithmetic computation with no memory.

### Combinational logic

A circuit that computes an output purely from its current inputs, with no stored state,
is called combinational.
It is the hardware equivalent of a pure function: same inputs always produce the same
output, instantaneously.

```python
def add(a: uint32_t, b: uint32_t) -> uint32_t:
    return a + b
```

### Registers (sequential logic)

A register is a flip-flop: it stores one value and updates it on every clock edge.
Functions that contain registers are **sequential** — their output depends on past history
as well as current inputs.

```python
@hw_func
def counter(increment: uint1_t) -> uint32_t:
    count: Reg[uint32_t]   # register, initialised to 0 at power-on
    if increment:
        count = count + 1
    return count
```

`count` reads its stored value at the start of each clock cycle and writes a new value
that will be latched at the next clock edge.

### Wires

Local variables inside a hardware function are **wires**: named signal paths that carry a
value from one point in the circuit to another within the same clock cycle.
They have no memory; they are recomputed fresh every cycle.

### The execution model

From a user's perspective:
- Each clock cycle the `@MAIN` function (and everything it calls) runs once.
- Registers hold their value from the *previous* cycle; their new value is committed at
  the *end* of the cycle.
- Everything else is combinational and happens "instantly" within the cycle.

---

## Python vs Hardware Execution

**Python executes the elaboration; hardware is what the annotated function describes.**
That single sentence is the whole mental model — every rule in this section is just that
idea worked out for a specific piece of syntax.

- **Module-level Python code runs once, at elaboration time.** Constants, type
  definitions, factory calls — none of it is hardware; it's the plain Python that
  *produces* hardware descriptions.
- **A hardware-annotated function is a circuit module, not a subroutine.** Calling it
  doesn't "run" it in the software sense — it instantiates hardware (see
  [Calling Functions](#calling-functions)).
- **`if`/`else` on a hardware value becomes a MUX**, not a branch. Both arms are
  elaborated into real logic; a multiplexer picks between their results every cycle (see
  [Control flow](#your-first-hardware-function)).
- **`for`/`while` loops are unrolled at compile time.** The loop variable is a plain
  Python integer; the compiler emits one copy of the loop body per iteration (see
  [`for`/`while` → loop unrolling](#your-first-hardware-function)).
- **Registers have cycle semantics, not variable semantics.** A `Reg[T]` read returns
  the value latched at the *previous* clock edge; a write schedules the value latched at
  the *next* one (see [Registers: `Reg[T]`](#registers-regt)).
- **Each call site instantiates a distinct piece of hardware.** Two calls to the same
  function are two separate circuits with independent state, not two invocations of
  shared code (see [Each call site is a separate instance](#calling-functions)).

### What compile-time Python may do

Because module-level code (and the Python surrounding a hardware function's elaboration)
runs before any hardware exists, it can do things a hardware function's body cannot:

- **Build specialised hardware with factories** — an ordinary Python closure that
  returns a hardware function, parameterised by type/width/count. See the
  [size-parametric factory example](#size-parametric-example) in
  [Parametric Hardware with Factory Functions](#parametric-hardware-with-factory-functions).
- **Use `range(N)` as a compile-time loop bound** — `N` must be a plain Python integer
  known at elaboration time, not a hardware signal.
- **Generate types and functions on demand** — `make_uint_t(N)`, `make_fixed_t(I, F)`,
  a factory-built `@struct`, and similar all run as ordinary Python producing a new type
  or function object.
- **Compute constants** — arithmetic on plain Python `int`/`float` values, list/dict
  comprehensions building lookup tables, anything that resolves to a fixed value before
  synthesis.
- **Introspect types** — `T.typeof(field)`, `hw_arg_types(func)`, `hw_return_type(func)`
  read a type's/function's structure at elaboration time to build code that adapts to it.

None of this produces hardware by itself — it produces the *Python objects* (functions,
types, constants) that, once called/used inside a hardware-annotated function, do.

### Glossary

**Software vocabulary, as used in this guide:**

| Term | Meaning here |
|---|---|
| Closure | A Python function that captures variables from an enclosing factory call — how parametric hardware is built |
| Factory | A plain Python function that *returns* a hardware function or type, specialised by its arguments |
| Decorator | `@hw_func`, `@MAIN`, `@struct`, etc. — Python syntax that tags a function/class for the elaborator |

**Hardware vocabulary, as used in this guide:**

| Term | Meaning here |
|---|---|
| Register | A flip-flop: stores one value, updates on the clock edge (`Reg[T]`) |
| Wire | A named signal path with no memory, recomputed every cycle (a local variable, or `Wire[T]`) |
| MUX | A multiplexer — the hardware an `if`/ternary compiles to |
| Port | An input/output of a hardware module (`Input[T]`/`Output[T]`, or a function argument/return value) |

**The four execution worlds this codebase has** — a given line of code or a given
"cycle" always belongs to exactly one of these, and mixing them up is the single most
common source of confusion:

| World | What's actually running |
|---|---|
| Elaboration time | Plain Python, at compile time — module-level code, factories, `for` loop unrolling |
| Hardware cycle time | Real clock edges on real (or synthesized) silicon |
| Native simulation time | Python `sim_call`/`pypelinec --sim` — hardware behaviour re-implemented in Python |
| VHDL simulation time | cocotb + GHDL simulating the actual generated VHDL |

This guide uses "elaboration time" and "compile time" interchangeably for the first row —
"elaboration time" when describing *when* code runs, "compile-time constant"/"compile-time
loop bound" as the idiomatic adjective form for a value known at that point. Both name the
same world.

Native and VHDL simulation *should* always agree — when they don't, that's a real bug,
and [`pypeline_sim_debug.py`](#sim_print-debugtrue--tagged-prints-for-pypeline_sim_debugpy)
exists specifically to localize where they diverge. Don't collapse these two into one
"simulation" world when a passage is distinguishing them.

Later sections use inline **Compile time:** / **Hardware:** / **Simulation:** labels
wherever a passage risks ambiguity about which of these worlds is being discussed.

---

## Simulation

pypeline designs can be simulated in Python before synthesising for an FPGA — no toolchain
required. This section covers the zero-toolchain basics: decorating functions for
simulation, calling them directly, and running a multi-`@MAIN` design. The rest of the
simulation feature set — `@sim_output`/`@sim_input`, `sim_print`/`sim_assert`/`sim_finish`,
`@sim_model`, and the native-vs-VHDL debug tool — is reference material covered in
[Simulation Reference](#simulation-reference) in Part V, once you've got the basics down.

### `@hw_func`

Decorate hardware helper functions with `@hw_func`.
This is required for register simulation and is harmless on combinational-only functions.

```python
from pypeline import hw_func, uint32_t, Reg

@hw_func
def accumulator(data: uint32_t) -> uint32_t:
    acc: Reg[uint32_t]
    acc = acc + data
    return acc
```

`@MAIN` implies `@hw_func`; you do not need both.

### `sim_call` — single-function simulation

```python
from pypeline import sim_call, sim_reset, uint32_t

sim_reset()                          # reset to power-on state (non-zero inits restored too)

r0 = sim_call(accumulator, 10)       # cycle 1: acc=0+10=10, returns 10
r1 = sim_call(accumulator, 5)        # cycle 2: acc=10+5=15, returns 15
assert r0 == 10
assert r1 == 15
```

Each call to `sim_call` advances the function by one clock cycle.
Call `sim_reset()` at the start of each independent test.

### Registers in simulation — multiple instances

When the same function is called from two different call sites in a `@MAIN`, each site
gets its own register state in simulation — matching hardware behaviour exactly.

```python
sim_reset()

@MAIN
def dual_accum(a: uint32_t, b: uint32_t) -> uint32_t:
    sum_a = accumulator(a)   # instance 1
    sum_b = accumulator(b)   # instance 2 — independent register
    return sum_a + sum_b

r = sim_call(dual_accum, 10, 5)   # sum_a: 0+10=10, sum_b: 0+5=5 → 15
r = sim_call(dual_accum, 10, 5)   # sum_a: 10+10=20, sum_b: 5+5=10 → 30
```

### `pypelinec --sim` — multi-MAIN designs

Designs that use `Wire[T]` global signals (see [Global Signals](#global-signals))
require running multiple `@MAIN` functions together.
Use the `pypelinec` CLI:

```
pypelinec my_design.py --sim --comb --run 1000
```

This runs 1000 simulated clock cycles, with delta-cycle convergence each cycle to resolve
global wires before committing register values. `pypelinec` detects the `.py` design and
defaults to the native simulator (implemented in `src/pypeline_sim.py`), skipping VHDL
elaboration/synthesis entirely, whenever no other simulator is explicitly selected (no
`--cocotb`, `--edaplay`, `--modelsim`, `--cxxrtl`, or `--verilator` flag). `--sim --comb` is
comb-only, no autopipelining pass first. Dropping `--comb` (just `--sim`)
instead builds the final (maybe autopipelined) version first and then native-sims that with
its discovered pipeline latencies emulated — see [Tool-Chosen Implementation: `AUTOPIPELINE(...)` and `AUTOFSM(...)`](#tool-chosen-implementation-autopipeline-and-autofsm).
Explicitly passing `--cocotb --ghdl` (etc.) still elaborates the design to VHDL and simulates
that instead.

For lower-level control — a `--mode` flag that trades simulation accuracy for speed — call
the native simulator's own script directly instead of through `pypelinec`:

```
python3 src/pypeline_sim.py my_design.py --run 1000 --mode raw
```

| Mode | Description |
|---|---|
| `strict` (default) | Full hardware accuracy — integer widths masked at every typed operation |
| `loose` | SimVal objects preserved (bit-indexing works) but no bit-width masking on arithmetic |
| `raw` | Maximum speed (~9× faster than strict) — plain Python ints throughout; use for structural tests where precise overflow behaviour is not needed |

There's no `--mode` passthrough from `pypelinec` yet, so the `pypelinec --sim`/`--sim --comb`
path above always runs at `strict` accuracy.

---

## Top-Level Entry Points

### `@MAIN`

`@MAIN` marks a function as a top-level entry point — a clock domain.
The compiler generates one VHDL process per `@MAIN` function.

```python
from pypeline import MAIN, uint8_t

@MAIN
def blink() -> uint8_t:
    cnt: Reg[uint32_t]
    cnt = cnt + 1
    return cnt[23]   # MSB of a 24-bit counter blinks an LED
```

### Frequency constraint

Pass the target clock frequency in MHz to constrain the synthesis tool:

```python
@MAIN(100.0)
def my_design(x: uint32_t) -> uint32_t:
    ...

# keyword form also works:
@MAIN(mhz=25.0)
def vga_pixel_gen():
    ...
```

### FPGA target device

Call `PART()` once at module level to tell the synthesiser which device to target:

```python
from pypeline import PART

PART("xc7a35ticsg324-1l")   # Arty A7-35T
```

Without `PART`, the tool chain uses a software timing estimator rather than real
synthesis.

### Naming a clock with `make_clock`

By default the clock for a given `@MAIN(mhz)` rate is a tool-named top-level
port, e.g. `clk_100p0`. `make_clock(mhz)` overrides this: it tags a global
`Input[uint1_t]` or `Wire[uint1_t]` as *being* that clock, so the wire's own
name becomes the real top-level port (or internal signal) instead. This is the
pypeline equivalent of PipelineC's `DECL_INPUT` + `CLK_MHZ` pragma pair.

```python
from pypeline import MAIN, Input, uint1_t, make_clock

# External clock on a fixed-name port (e.g. to match a board constraints file)
pll_clk: Input[uint1_t] = make_clock(85.0)

@MAIN(85.0)
def solution(x: uint1_t) -> uint1_t:
    ...
```

`make_clock`'s rate must equal some `@MAIN`'s rate in the design exactly — that
match is how the tool decides which `@MAIN`'s clock this wire is. Use it on an
`Input[uint1_t]` for an external clock, or a `Wire[uint1_t]` for an internally
generated one (driven by another `@MAIN`, mirroring PipelineC's
[internal_clocks.c](../examples/internal_clocks.c) example — note that pattern
needs two `@MAIN`s at different rates, i.e. multiple clock domains, which is not
yet supported end-to-end; see [Limitations / Not Yet Supported](#limitations--not-yet-supported)). It cannot be used on an `Output[T]` (a clock
net needs exactly one driver, which an `Output` doesn't model) or on a wire whose
rate collides with another `make_clock`-tagged wire at the same rate.

---

## Your First Hardware Function

### Functions as modules

A Python function with type annotations on its arguments and return value is a hardware
module.

```python
from pypeline import uint32_t

def add(a: uint32_t, b: uint32_t) -> uint32_t:
    return a + b
```

This describes a combinational adder: two 32-bit input ports, one 32-bit output port,
and the logic `output = a + b`.

### Void functions

A function with no return annotation and no `return` statement is void — it has outputs
only via global signals (see [Global Signals](#global-signals)).

```python
def drive_leds(val: uint8_t):   # no return type → void
    leds_out = val
```

### Local variables

Local variables that are assigned from hardware expressions become wires — they carry
a value within the current clock cycle:

```python
def saturate(x: uint8_t, limit: uint8_t) -> uint8_t:
    result: uint8_t = x
    if x > limit:
        result = limit
    return result
```

Annotating a local variable (`result: uint8_t`) declares it with an explicit type.
The annotation is optional if the type can be inferred from the right-hand side.

### Control flow

#### `if` / `else` → hardware MUX

An `if` statement with a runtime condition does **not** branch in the traditional sense.
Both branches are elaborated into hardware; a multiplexer selects the result based on the
condition each clock cycle.

```python
def abs_val(x: int32_t) -> int32_t:
    result: int32_t = x
    if x < 0:
        result = -x
    return result
```

> **Required:** a hardware function may have **at most one** `return` statement, and it
> must be the function's final top-level statement — there is no early return from
> inside an `if`/`else` branch. To make a value conditional, assign to a variable in
> each branch (as above) and return it once at the end.

#### Ternary expression

```python
out: uint8_t = a if condition else b    # equivalent to the if/else above
```

#### Augmented assignment

`+=`, `-=`, `*=`, `|=`, `&=`, `^=` are supported and expand to the equivalent binary operation:

```python
total: uint32_t = 0
total += arr[0]   # equivalent to: total = total + arr[0]
```

#### Boolean operators

Python's `and` / `or` keywords work in hardware conditions.
Each operand is normalised to `uint1_t` (non-zero → 1, zero → 0) before combining:

```python
if (x > 0) and (y < 100):   # both conditions must be true
    ...

if valid or overflow:         # either condition triggers the branch
    ...
```

This is equivalent to `(x > 0) & (y < 100)` with each side coerced to 1 bit.
The result type is always `uint1_t`.

#### `for` / `while` → loop unrolling

Loops are **fully unrolled at compile time**.
The loop variable is a Python integer (not a hardware signal); the compiler emits one
copy of the body for each iteration.

```python
def sum_array(arr: uint32_t[4]) -> uint32_t:
    total: uint32_t = 0
    for i in range(4):        # unrolled 4 times; i is 0, 1, 2, 3 at elaboration time
        total = total + arr[i]
    return total
```

`while` loops work the same way: the condition must be evaluable at compile time
(i.e. it must only reference plain Python values, not hardware signals).

The loop body may contain hardware expressions (reads from inputs, assignments to wires),
but the loop *control* itself (the range, the condition, the counter variable) is always
pure Python.

---

## Calling Functions

### Functions call functions

Calling a hardware function from another hardware function **instantiates** it as a
submodule.
Each call site in the source corresponds to a distinct hardware instance.

```python
def add(a: uint32_t, b: uint32_t) -> uint32_t:
    return a + b

@MAIN
def two_adders(x: uint32_t, y: uint32_t, z: uint32_t) -> uint32_t:
    partial = add(x, y)     # one adder instance
    return add(partial, z)  # a second, independent adder instance
```

### Feed-forward hierarchy

Functions can call other functions to any depth.
This is the primary way to build hierarchical designs — a top-level `@MAIN` calls
sub-functions which call sub-sub-functions, forming a tree of combinational logic and
registers.

```python
def compute_pixel(pos: vga_pos_t) -> rgb_t:
    r: uint8_t = pos.x[7:0]
    g: uint8_t = pos.y[7:0]
    b: uint8_t = pos.x[7:0] ^ pos.y[7:0]
    return rgb_t(r=r, g=g, b=b)

def vga_scan(timing: vga_timing_signals_t) -> rgb_t:
    px: rgb_t
    if timing.active:
        px = compute_pixel(timing.pos)
    return px

@MAIN(25.0)
def top():
    sig = vga_timing()
    px  = vga_scan(sig)
    video_out = px
```

### Each call site is a separate instance

Two calls to the same function produce two independent hardware instances.
If the function contains registers, each instance has its own independent register state.

```python
@hw_func
def accumulator(data: uint32_t) -> uint32_t:
    acc: Reg[uint32_t]
    acc = acc + data
    return acc

@MAIN
def dual_accum(a: uint32_t, b: uint32_t) -> uint32_t:
    sum_a = accumulator(a)   # instance 1 — its own flip-flop
    sum_b = accumulator(b)   # instance 2 — independent flip-flop
    return sum_a + sum_b
```

### Clock enable via `if` around a call

Wrapping a function call in an `if` block automatically gates the **clock enable** of
that instance's registers.
The registers inside the called function only update when the condition is true.

```python
@MAIN
def conditional_accum(update: uint1_t, data: uint32_t) -> uint32_t:
    rv: uint32_t
    if update:
        rv = accumulator(data)   # accumulator's register only latches when update=1
    return rv
```

When `update=0`, `accumulator`'s internal `acc` register holds its previous value
unchanged — no explicit clock-enable wiring is needed.

### Calling functions across files

Large designs can be split across multiple `.py` files.
Use a plain `import` at module level in the top file:

```python
# top.py
import file_a
import file_b
```

**Only `import file_a` (qualified attribute access) is supported.**
`from file_a import *` is intentionally not supported.

**Import aliases use the actual module name for hardware, not the alias.**
`import file_a as fa` lets you write `fa.func()` in Python, but the generated VHDL
wire and function names are prefixed with `file_a`, not `fa`.
Two aliases pointing at the same file both refer to the same hardware wires.

**Recursive (transitive) imports are followed automatically.**
If `file_a.py` itself imports `file_b.py`, `file_b` is discovered and elaborated
too — you don't need to also import it from the top file. Only plain top-level
`import module_name` statements are followed at each hop (still not
`from file_a import *`, and not an `import` written inside a function/`if`/`try`
body), so each file only needs to import what it directly uses, the same way
plain Python code is organized.

Call hardware functions from imported files using attribute syntax:

```python
# top.py
import my_lib

@MAIN
def top_level(x: uint32_t) -> uint32_t:
    result = my_lib.accumulator(x)   # instantiates my_lib's accumulator
    return result
```

Sub-files are always elaborated before the top file, so imported functions are always
available when the top file calls them.

Access or connect global wires declared in imported files using the same dotted notation:

```python
# top.py
import file_a
import file_b

@MAIN
def connector():
    file_b.input_wire = file_a.output_wire   # write file_b's wire, read file_a's wire
    file_a.input_wire = file_b.output_wire
```

The hardware wire names are automatically prefixed with the module name
(`file_a_output_wire`, etc.) to avoid collisions.

Nested field and array access on cross-module wires is also supported, to any depth:

```python
@MAIN
def connector():
    file_b.state.count = file_a.counters.total[0]
```

Module-level constants from sub-files are not directly accessible by name inside a
hardware function body.
Copy them at module level in the top file first:

```python
import my_lib
SHIFT = my_lib.SHIFT_AMOUNT   # now available as a plain Python int in this module
```

---

## Registers: `Reg[T]`

```text
        +----------+      +-----------------+      +-----------+
current |          |      |                 |      |           | next
--state>|  Reg[T]  |----->|  combinational  |----->| (assign   |---state
        |  (flop)  |      |     logic       |      |  to Reg)  |
        |          |      |                 |      |           |
        +----------+      +-----------------+      +-----+-----+
             ^                                            |
             |                clock edge                  |
             +--------------------------------------------+
```

A `Reg[T]` read returns the value latched at the *previous* clock edge; the value
assigned by the end of the cycle is what latches at the *next* one.

### Declaration

Annotate a local variable with `Reg[T]` inside a hardware function to declare a register
of type `T`.
The register is initialised to zero at power-on reset.

```python
from pypeline import Reg, uint32_t, uint1_t, hw_func

@hw_func
def counter(increment: uint1_t) -> uint32_t:
    count: Reg[uint32_t]
    if increment:
        count = count + 1
    return count
```

**`Reg[T]` may never use an `@interface`'s `.fwd_t`/`.fb_t` ([Bidirectional Ports: `@interface`](#bidirectional-ports-interface))** — a hard
`ElaborationError`, not a style preference. `.fwd_t`/`.fb_t` signal "this value is one
half of a genuine bidirectional port pairing"; a register is internal state, never a
port, so it never needs (or should imply) that. Use `.stream_t` instead — the plain
`{data, valid}` type with no pairing implication — and only wrap/unwrap via `.stream`
at the point the register's value actually meets a real port field:

```python
# Wrong -- ElaborationError: Reg[T] cannot use an @interface's .fwd_t/.fb_t
buf: Reg[chan_intrf.fwd_t]

# Right
buf: Reg[chan_intrf.stream_t]
...
o.stream_out_if.stream = buf   # wrap only where it meets the real port field
```

See [Where `.fwd_t`/`.fb_t` may appear — and where it may not](#where-fwd_tfb_t-may-appear--and-where-it-may-not) in the `@interface` section for the general rule (Reg[T] is one case of it).

### Read / write semantics

Registers use **blocking assignment** semantics, just like ordinary software variables.
Reading a register before any assignment gives the value stored from the previous clock
cycle.
After you assign to a register, subsequent reads within the same function call see the
new value.
The final value assigned is what gets latched into the flip-flop at the next clock edge.

```python
# Example: read old, then write new, then read new
acc: Reg[uint32_t]
old = acc         # old = value from previous cycle
acc = acc + 1     # register will latch acc+1 at next clock edge
new = acc         # new = acc+1  (the value just written, not the old one)
```

To return the value *before* an update, capture it first:

```python
prev = acc
acc  = acc + data
return prev        # returns the pre-update value
```

### Non-zero initial values

An optional initialiser sets the power-on reset value:

```python
cnt: Reg[uint32_t] = 10                  # scalar — starts at 10 after reset

buf: Reg[uint8_t[4]] = [10, 20, 30, 40] # array — each element initialised

pt:  Reg[point_t] = point_t(x=5, y=2)  # struct — NamedTuple constructor form
```

Without an initialiser the register resets to zero.

### Counter example

```python
@hw_func
def free_counter() -> uint32_t:
    cnt: Reg[uint32_t]
    cnt = cnt + 1       # increments every cycle
    return cnt          # returns the incremented value (cnt+1)
```

### Clock enable via `if`

Placing a register write inside an `if` block gates the update with that condition —
the register only changes when the condition is true.

```python
@hw_func
def latch(load: uint1_t, data: uint8_t) -> uint8_t:
    stored: Reg[uint8_t]
    if load:
        stored = data   # updates only when load=1
    return stored
```

When `load=0`, `stored` keeps its previous value.

### `@hw_func`

Any non-`@MAIN` function that contains `Reg[T]` (or `Feedback[T]`) must be decorated
with `@hw_func`.
This is required for simulation (see [Simulation](#simulation)) and is good practice
for documenting that the function has hardware-typed behaviour.
Plain combinational helpers do not need it.

---

## Feedback Wires: `Feedback[T]`

A `Feedback[T]` wire is a combinational signal whose **driver appears later in the
function body than its first use**.
This models reverse-propagating signals — a common pattern in hardware where a
downstream signal feeds back to a computation upstream.

```python
from pypeline import Feedback, hw_func, uint1_t

@hw_func
def feedback_nand(a: uint1_t, b: uint1_t) -> uint1_t:
    f: Feedback[uint1_t]   # declare before use
    result: uint1_t = f | a  # read f — it hasn't been assigned yet in Python order
    f = ~b                   # drive f here (appears after the read)
    return result
```

In the generated VHDL, all signals are concurrent — "source order" is irrelevant.
The compiler resolves the combinational loop correctly.

Like `Reg[T]`, `Feedback[T]` may never use an `@interface`'s `.fwd_t`/`.fb_t` port-pairing
type as `T` — see
[Where `.fwd_t`/`.fb_t` may appear — and where it may not](#where-fwd_tfb_t-may-appear--and-where-it-may-not).

**`Feedback[T]` vs `Reg[T]`:**

| | `Reg[T]` | `Feedback[T]` |
|---|---|---|
| Storage | flip-flop (persists across cycles) | none (combinational only) |
| Initial value | zero at reset | none |
| Clock edge | yes | no |

Do not initialise a `Feedback[T]` wire at its declaration:

```python
f: Feedback[uint1_t] = x   # error
```

---

## Bit Manipulation

Hardware frequently needs sub-word access that Python integers do not support natively.
pypeline adds the following syntax and built-in functions.

### Single-bit select

```python
bit: uint1_t = x[15]      # extract bit 15 of x
```

### Bit-slice read

```python
lo: uint16_t = x[15:0]    # bits 15 down to 0  (high index first, like hardware)
hi: uint4_t  = x[7:4]     # bits 7 down to 4
```

Slice bounds must be compile-time constants.

### Bit-slice assignment

```python
x[7:0] = y    # overwrite bits [7:0] of x with y; other bits unchanged
```

### Bit concatenation — `concat()`

`concat` packs multiple values end-to-end, **first argument in the most-significant
position**:

```python
from pypeline import concat

out: uint64_t = concat(hi_word, lo_word)   # uint32_t ++ uint32_t → uint64_t
packed: uint24_t = concat(r, g, b)         # three uint8_t values → uint24_t
```

### Built-in bit helpers

| Function | Description |
|---|---|
| `bit_dup(x, n)` | Replicate `x` exactly `n` times → `uintW*n_t` |
| `rotl(x, n)` | Rotate left by `n` bits |
| `rotr(x, n)` | Rotate right by `n` bits |
| `bswap(x)` | Reverse byte order (width must be a multiple of 8) |
| `bit_assign(base, val, offset)` | Overwrite bits `[offset+W-1:offset]` of `base` with `val` |
| `array_to_uint_be(arr)` | Concatenate array elements, big-endian (arr[0] = MSB) |
| `array_to_uint_le(arr)` | Concatenate array elements, little-endian (arr[0] = LSB) |
| `uint_to_array_be(x, n)` | Split integer into `n` equal elements, big-endian |
| `uint_to_array_le(x, n)` | Split integer into `n` equal elements, little-endian |

All size/count arguments must be compile-time constants.

---

## Basic Types

Pypeline has three categories of type: **built-in/predefined** (the integer types
below, `char_t`), **Python-defined structural** (`@struct`, `@enum` — you write the
shape, Pypeline derives the hardware), and **parameterized/factory-generated**
(built by calling a `make_*` function, covered in
[Parametric Hardware with Factory Functions](#parametric-hardware-with-factory-functions)
and [Factory-Generated Types](#factory-generated-types) right after it — e.g.
`float32_t`/`q4_12_t`). This section covers the first two categories.

### Integer types

pypeline provides fixed-width integer types matching C hardware-description convention.

| Type | Width | Range |
|---|---|---|
| `uint1_t` | 1 bit | 0 … 1 |
| `uint8_t` | 8 bits | 0 … 255 |
| `uint16_t` | 16 bits | 0 … 65535 |
| `uint32_t` | 32 bits | 0 … 2³²−1 |
| `uint64_t` | 64 bits | 0 … 2⁶⁴−1 |
| `int8_t` | 8 bits signed | −128 … 127 |
| `int32_t` | 32 bits signed | −2³¹ … 2³¹−1 |

Use `make_uint_t` / `make_int_t` for widths that are computed at module level:

```python
from pypeline import make_uint_t, make_int_t

N = 24
uint24_t = make_uint_t(N)
int33_t  = make_int_t(N + 9)
```

Integer literals in hardware function bodies are automatically given the minimum-width
unsigned type that fits the value (`0` → `uint1_t`, `255` → `uint8_t`, etc.).

### Casting — not yet supported

> **Not supported:** There is no explicit cast expression. Calling a type as a
> function — `uint32_t(x)`, `int16_t(133)` — anywhere inside a hardware function
> body fails at elaboration time, even when the argument is already a compile-time
> constant. Instead, assign the value to an **intermediate variable with an
> explicit type annotation**; the annotation itself triggers the same
> implicit width-truncating/reinterpreting assignment used everywhere else in the
> language for narrowing/widening, including signed/unsigned reinterpretation —
> no wrapping call needed:
>
> ```python
> def widen(x: uint16_t) -> uint32_t:
>     tmp: uint32_t = x       # correct — annotated intermediate variable
>     return tmp
> ```
>
> Calling a type with a plain Python value **at module level**, outside any
> hardware function (e.g. `ABSTOP12 = uint32_t(0x3f4)`), is unaffected — that's
> ordinary Python executed at import time, not hardware elaboration.

See [Limitations: Language](#limitations--not-yet-supported) for the full explanation of
why this fails (a confusing `inspect`/`OSError` rather than a clear error) and more
examples.

### Struct types

Use `@struct` + `NamedTuple` to declare compound record types.

```python
from typing import NamedTuple
from pypeline import struct, uint32_t

@struct
class point_t(NamedTuple):
    x: uint32_t
    y: uint32_t
```

The `@struct` decorator makes `point_t` usable as an array element type
(`point_t[10]`) and enables field-wise wrapping during simulation.

Access fields with the usual dot notation:

```python
def add_points(a: point_t, b: point_t) -> point_t:
    return point_t(x=a.x + b.x, y=a.y + b.y)
```

### Enum types

Use `@enum` on a Python `IntEnum` subclass to declare an integer-encoded enumeration type.
The bit width is computed automatically from the largest member value.

```python
from enum import IntEnum
from pypeline import enum, MAIN, Reg, uint1_t

@enum
class state_t(IntEnum):
    IDLE    = 0
    RUNNING = 1
    DONE    = 2
```

Members are accessed with dot notation and compare with `==`:

```python
@MAIN
def is_idle(s: state_t) -> uint1_t:
    rv: uint1_t = 0
    if s == state_t.IDLE:
        rv = 1
    return rv
```

Use `Reg[state_t]` for FSM state registers:

```python
@MAIN
def simple_fsm(trigger: uint1_t) -> state_t:
    st: Reg[state_t]
    if st == state_t.IDLE and trigger:
        st = state_t.RUNNING
    elif st == state_t.RUNNING:
        st = state_t.DONE
    return st
```

The `@enum` decorator also accepts a plain class (auto-converted to `IntEnum`):

```python
@enum
class direction_t:         # @enum detects int members and converts
    NORTH = 0; EAST = 1; SOUTH = 2; WEST = 3
```

#### `auto()` values (0-based)

PipelineC C enums start at 0. Use `auto()` so you don't have to write values
manually — pypeline guarantees the first member is 0, not Python's default of 1.

**Form 1 — plain class (no base class needed):**
```python
from enum import auto
from pypeline import enum

@enum
class state_t:
    IDLE    = auto()   # 0
    RUNNING = auto()   # 1
    DONE    = auto()   # 2
```

**Form 2 — `PypelineEnum` base class (IntEnum-subclass style):**
```python
from enum import auto
from pypeline import enum, PypelineEnum

@enum
class state_t(PypelineEnum):
    IDLE    = auto()   # 0
    RUNNING = auto()   # 1
    DONE    = auto()   # 2
```

Both forms produce identical enum types. You can also mix explicit int values with
`auto()` — an explicit value resets the counter for subsequent `auto()` members:
```python
@enum
class code_t:
    ALPHA = 10
    BETA  = auto()   # 11
    GAMMA = auto()   # 12
```

#### Parameterizable enums

Write a user factory that calls `enum(IntEnum(...))` — the same pattern as
parameterizable structs:

```python
def make_traffic_t(include_yellow=True):
    members = {"RED": 0, "GREEN": 2}
    if include_yellow:
        members["YELLOW"] = 1
    return enum(IntEnum("traffic_t", members))

traffic_t = make_traffic_t(include_yellow=True)
```

#### Introspection helpers

```python
from pypeline import enum_bit_width, enum_uint_type

enum_bit_width(state_t)   # → 2  (minimum bits to represent 0..2)
enum_uint_type(state_t)   # → uint2_t
```

Enum types can also be used as struct fields:

```python
@struct
class packet_t(NamedTuple):
    state: state_t
    data:  uint8_t
```

### Char arrays (strings)

`char_t` is a predefined 8-bit scalar type, exactly like `uint8_t` but with its own
C-type-string (`"char"`). Combine it with `[N]` array syntax to get a fixed-size string
type:

```python
from pypeline import char_t, strlen

def greet() -> char_t[16]:
    name: char_t[16] = "hello"    # Python string literal as a compile-time initializer
    return name
```

A shorter literal is zero-padded on the right; a literal longer than the declared array
raises an error at elaboration time. String literals also work as struct-field
initializers, function return values, and directly as call arguments:

```python
@struct
class packet_t(NamedTuple):
    name: char_t[16]
    value: uint32_t

@hw_func
def make_packet(v: uint32_t) -> packet_t:
    p: packet_t
    p.name = "sensor_1"
    p.value = v
    return p

@hw_func
def log_event(tag: char_t[16]) -> uint32_t:
    ...

@MAIN
def call_site() -> uint32_t:
    return log_event("startup")   # string literal passed directly as an argument
```

`strlen(arr)` returns the array's **declared capacity**, not the length of whatever text
happens to be stored in it — `strlen()` on the `name` field above always returns `16`,
even when it holds `"sensor_1"` (8 characters). This matches PipelineC's C-side `strlen()`
exactly: it's a compile-time constant (the array size), not a runtime scan for a
null terminator.

In simulation, a `char_t[N]` value is a `CharArray` (a list of `SimVal`s that also behaves
like the Python string it represents) — pass and compare plain Python `str` values
directly, with no conversion helpers needed:

```python
r = sim_call(greet)
assert r == "hello"

p = sim_call(make_packet, v=42)
assert p.name == "sensor_1"

r = sim_call(log_event, tag="custom_tag")
```

Char arrays support ordinary per-element arithmetic like any other array — each element
is just an 8-bit value:

```python
@MAIN
def increment_chars(s: char_t[16]) -> char_t[16]:
    out: char_t[16] = s
    for i in range(16):
        out[i] = s[i] + 1
    return out
```

Known limitation: `Reg[char_t[N]]` cannot have an explicit initializer (`Reg[char_t[16]] =
"hello"` raises an `ElaborationError`) — only zero-initialized char-array registers
(`Reg[char_t[16]]` with no `=`) are currently supported. See
[`pypeline_DESIGN.md`](pypeline_DESIGN.md#char-array-support) for why.

### Arrays

Append `[N]` to any type to get a fixed-length array of that type:

```python
uint32_t[4]       # 4-element array of 32-bit values
point_t[10]       # 10-element array of point_t structs
uint8_t[4][2]     # 4-element array where each element is a 2-byte array (like C)
```

Index arrays with a compile-time constant or with a hardware signal:

```python
def swap(arr: uint32_t[4], i: uint2_t, j: uint2_t) -> uint32_t[4]:
    tmp     = arr[i]
    arr[i]  = arr[j]
    arr[j]  = tmp
    return arr
```

Variable indexing (where `i` or `j` is a hardware signal) infers a multiplexer tree in
hardware.
Like any combinational logic, those mux trees can be autopipelined by PypelineC when a
frequency constraint is set.

### Compound initialisers

A struct or array variable can be initialised from a constructor call or list literal
in one go:

```python
def make_point(a: uint32_t, b: uint32_t) -> point_t:
    p: point_t = point_t(x=a, y=b)   # NamedTuple constructor (preferred)
    return p

def zero_pair() -> uint32_t[2]:
    v: uint32_t[2] = [0, 0]          # list literal
    return v

def make_point_dict(a: uint32_t, b: uint32_t) -> point_t:
    p: point_t = {"x": a, "y": b}    # dict form (also supported)
    return p
```

The NamedTuple form is preferred because it works in both hardware elaboration and
simulation.

Plain Python helper functions that return a `dict`, `list`, or NamedTuple instance
at elaboration time can also serve as compound initialisers — the result must contain
only compile-time integer values, not hardware wires:

```python
def zero_point():          # ordinary Python function
    return point_t(x=0, y=0)

def my_func(...) -> point_t:
    p: point_t = zero_point()   # elaboration-time call → compound init
    return p
```

### Struct/type ↔ bytes conversion

`byte_length(t)`, `make_type_to_bytes(t, endian="little")`, and
`make_type_from_bytes(t, endian="little")` give a generic, built-in way to pack any
pypeline type — scalar, array, struct, or any nesting thereof — into a fixed
`uint8_t[N]` array and back, instead of hand-writing per-type `concat()`/bit-slicing
code:

```python
from pypeline import struct, uint8_t, uint16_t, uint32_t, byte_length, make_type_to_bytes, make_type_from_bytes
from typing import NamedTuple

@struct
class header_t(NamedTuple):
    version: uint8_t
    length: uint16_t
    flags: uint32_t

header_to_bytes   = make_type_to_bytes(header_t)     # -> hardware function
header_from_bytes = make_type_from_bytes(header_t)   # exact inverse

def pack(h: header_t) -> uint8_t[byte_length(header_t)]:
    return header_to_bytes(h)
```

`byte_length(t)` is the companion "sizeof" — a plain Python function (no hardware
elaboration involved) that returns the byte size of `t`, for sizing the destination
array before calling `..._from_bytes` or after calling `..._to_bytes`.

The layout is a **packed, unpadded struct**, not C's natural alignment: each leaf
scalar field is rounded up to a whole number of bytes (`ceil(width / 8)` — so a
`uint3_t` field still takes 1 byte), and fields/array elements are packed back-to-back
in declaration order with no other padding. `endian` (`"little"` by default, or
`"big"`) controls the byte order within each multi-byte field.

The returned functions are tagged `@wires` (see [Just-Wires Synthesis Hint: `@wires`](#just-wires-synthesis-hint-wires))
since they are pure bit rewiring with no real combinational delay.

Works for any combination of arrays and structs, e.g.
`make_type_to_bytes(uint32_t[3])` or `make_type_to_bytes(my_struct_t[3])`.

**Enum types are not supported** by `byte_length`/`make_type_to_bytes`/
`make_type_from_bytes` in this version — including an enum nested inside a struct or
array field — and raise `NotImplementedError`.


---

## Parametric Hardware with Factory Functions

Because module-level Python code runs at elaboration time, you can generate specialised
hardware functions and types using ordinary Python factories (closures).

### Generic functions

```python
from pypeline import uint8_t, uint32_t

def make_adder(T):
    def add(a: T, b: T) -> T:
        return a + b
    return add

add_u32 = make_adder(uint32_t)   # specialise for 32-bit
add_u8  = make_adder(uint8_t)    # specialise for 8-bit

@MAIN
def top(x: uint32_t, y: uint8_t) -> uint32_t:
    big  = add_u32(x, x)         # 32-bit adder instance
    small = add_u8(y, y)         # 8-bit adder instance
    return big + small
```

Each specialised result (`add_u32`, `add_u8`) produces a separate VHDL entity with the
correct bit widths.
Calling the same specialisation multiple times reuses the same entity definition but
creates separate instances.

### Generic structs

```python
from typing import NamedTuple
from pypeline import struct

def make_pair_t(T):
    @struct
    class pair_t(NamedTuple):
        a: T
        b: T
    return pair_t

pair_u32_t = make_pair_t(uint32_t)
pair_u8_t  = make_pair_t(uint8_t)
```

### Size-parametric example

```python
def make_sum_array(T, N):
    def sum_array(arr: T[N]) -> T:
        total: T = 0
        for i in range(N):
            total = total + arr[i]
        return total
    return sum_array

sum4_u32 = make_sum_array(uint32_t, 4)
sum8_u8  = make_sum_array(uint8_t, 8)
```

The factory body (`for i in range(N)`) is pure Python and runs at elaboration time.
Only the inner function's body becomes hardware.

### Introspecting a function's types: `hw_arg_types` / `hw_return_type`

Sometimes a factory wraps a function *supplied by the caller* rather than one it builds
itself, and needs that function's parameter/return types to build the rest of its
hardware (a stream type around the payload type, a result struct sized to match, etc.):

```python
def make_valid_ready_mcp(func, ncycles):
    """func must already be @hw_func-decorated, with one annotated parameter and an
    annotated return type, e.g.:
        @hw_func
        def divider(i: my_struct_t) -> uint32_t: ..."""
    ...
```

There's no factory call site to ask for these types — `func` is just an ordinary
annotated Python function. `hw_arg_types(func)` and `hw_return_type(func)` recover them:

```python
from pypeline import hw_arg_types, hw_return_type

(in_type,) = hw_arg_types(func)   # tuple of parameter types, in declaration order
out_type = hw_return_type(func)   # the declared return type
```

Both work whether `func` is undecorated or already `@hw_func`-decorated — but for
factories that go on to *call* `func` from inside their own hardware function body
(rather than just introspecting its annotations), `func` itself must already be
`@hw_func`-decorated: `AUTOPIPELINE`, `make_valid_ready_mcp`, and
`make_stream_pipeline` all enforce this and raise `TypeError`
otherwise (see [Tool-Chosen Implementation: `AUTOPIPELINE(...)` and `AUTOFSM(...)`](#tool-chosen-implementation-autopipeline-and-autofsm) /
[Multi-Cycle Paths: `MULTI_CYCLE[...]`](#multi-cycle-paths-multi_cycle)). `@hw_func`
decoration does not propagate into plain functions called from inside that body — a
factory that calls an undecorated `func` won't simulate `Reg[T]`/`Feedback[T]` or bare
struct/array locals correctly under `sim_call`, which is why the check exists (see
`docs/pypeline_sim_DESIGN.md` for how `@hw_func` decoration makes simulation work).

Prefer `hw_arg_types`/`hw_return_type` over reading `func.__annotations__` directly, or
having a factory stash a type as a custom attribute on the function it returns (e.g.
`my_func.out_t = out_t`) — the type is already recoverable generically from the
function's own annotations, so there's no need for either function authors or callers
to manage it by hand. See `include/pypeline/multi_cycle_path.py` for the full
`make_valid_ready_mcp` example.

---

## Factory-Generated Types

These are examples of the third category from the [Basic Types](#basic-types) roadmap above: `float32_t` isn't a builtin — it's `make_float_t(8, 23)`; `float64_t` is `make_float_t(11, 52)`. Fixed-point types work the same way, built by `make_fixed_t`.

### Floating-point types

`from floating_point import float32_t, float64_t` (an import or two, from the
`include/pypeline/floating_point.py` library) gets you IEEE 754-like struct types
with `sign` (1 bit), `exp` (E bits), and `man` (M bits) fields, matching IEEE 754
layout for standard sizes — with `+`, `-`, `*`, `/` already overloaded, ready to use:

```python
from floating_point import float32_t, float64_t

def bias_one(x: float32_t) -> float32_t:
    one: float32_t = float32_t.as_const(1.0)   # Python float → hardware constant
    return x + one                              # dispatches to the library's adder
```

`float32_t.as_const(value)` converts a Python `float` to a `float32_t` instance at
elaboration time; `float(x)` (on any value returned from a `float32_t`/`float64_t`
computation) converts back to a Python `float`, for printing/debugging/comparing
against a reference implementation.

Need a non-standard precision, or just the building blocks? `make_float_t(E, M)`
(also from `floating_point`) builds the struct type itself, and
`register_float_ops(float_t)` builds and globally registers `+`/`-`/`*`/`/` for it
— this is exactly how the library builds `float16_t`/`float32_t`/`float64_t`
themselves. The individual factories (`make_float_adder`, `make_float_subtractor`,
`make_float_multiplier`, `make_float_divider`) are available too if you want to
register just one operator, or reuse an existing adder (`make_float_subtractor`'s
`adder=` argument) instead of building a second copy.

#### Converting between float precisions, or to/from an int

`make_float_converter(src_t, dst_t)` builds a widening or narrowing conversion
function between any two `make_float_t` types — this is what to reach for in place
of a cast (structs can't be cast; see [Casting](#casting--not-yet-supported)):

```python
from floating_point import float32_t, float64_t, make_float_converter

float32_to_float64 = make_float_converter(float32_t, float64_t)
float64_to_float32 = make_float_converter(float64_t, float32_t)
```

The library already builds these two for you (`from floating_point import
float32_to_float64, float64_to_float32`). For converting to/from a plain integer
type, `make_float_to_int(float_t, int_t)` (truncating, toward zero, like C's
`(int)f`) and `make_int_to_float(int_t, float_t)` (value-preserving) do the same
job — the library also ships `float64_to_int32`/`int32_to_float64` pre-built.
None of these handle subnormals, `inf`/`NaN`, or overflow specially — they match
the common-case-only rigor of the adder they're built alongside.

#### Converting to/from a raw bit pattern (e.g. `uint32_t`)

A float type is a **struct**, not a distinct bit-reinterpretation of an integer, so
there is no cast between `float32_t` and `uint32_t` (see
[Casting](#casting--not-yet-supported) above — this is exactly the case that section
warns about). To move a float value across a boundary declared as a plain unsigned
integer — a top-level port, a stream payload, anything typed `uintN_t` — unpack/pack
the struct fields by hand with bit-slicing and `concat()` instead:

```python
from pypeline import concat

E_LEN = len(float32_t.typeof("exp"))   # 8  -- generic: works for any make_float_t result
M_LEN = len(float32_t.typeof("man"))   # 23
S_BIT = E_LEN + M_LEN                  # 31 -- sign is the top bit

def uint32_to_float32(bits: uint32_t) -> float32_t:
    return float32_t(
        sign=bits[S_BIT],
        exp=bits[S_BIT - 1 : M_LEN],
        man=bits[M_LEN - 1 : 0],
    )

def float32_to_uint32(f: float32_t) -> uint32_t:
    return concat(f.sign, f.exp, f.man)   # first arg = MSB, matching IEEE 754 layout
```

`T.typeof(field_name)` is available on any `@struct` type (not just floats) and
returns the declared ctype of that field; `len(...)` on the result gives its bit
width. Computing `E_LEN`/`M_LEN`/`S_BIT` this way — rather than hardcoding `8`/`23` —
keeps the same unpack/pack code working unchanged for `float64_t = make_float_t(11,
52)` or any other exponent/mantissa width.

See `src/tests/pypeline_tests/inst/float32_add_test.py`'s `float_add_32_main` for a
complete worked example: it receives two `uint32_t` ports, unpacks each into a
`float32_t`, adds them, and repacks the `float32_t` result back into a `uint32_t`.

### Fixed-point types

`from fixed_point import make_fixed_t` (from `include/pypeline/fixed_point.py`) builds a
struct type wrapping a single raw integer field — a fixed-point number is just an
`intN_t`/`uintN_t` with an implied binary point `frac_bits` positions up from the LSB:

```python
from fixed_point import make_fixed_t, register_fixed_ops

q4_12_t = make_fixed_t(4, 12)          # signed Q4.12: 4 integer bits, 12 fraction bits
add, sub, mul, neg = register_fixed_ops(q4_12_t)   # registers +, -, *, unary - globally

def bias_one(x: q4_12_t):
    one: q4_12_t = q4_12_t.as_const(1.0)   # Python float -> hardware constant
    return x + one                          # dispatches to the registered adder
```

`q4_12_t.as_const(value)` converts a Python `float` to a `q4_12_t` instance at elaboration
time (round-half-even, matching Python's own `round()`); `float(x)` (on any `q4_12_t` value)
converts back to a Python `float` for printing/debugging/comparing against a reference
implementation. `t.int_bits`/`t.frac_bits`/`t.signed` are plain attributes on any type
returned by `make_fixed_t`, for introspection by generic code (e.g. a FIR filter library
choosing accumulator widths).

#### `+`, `-`, `*` always grow — they never truncate

Unlike native `intN_t`/`uintN_t` arithmetic (which you assign into an explicitly-sized
local to narrow), `register_fixed_ops`/`make_fixed_adder`/`make_fixed_subtractor`/
`make_fixed_multiplier` deliberately return a **wider** type than either operand, sized to
hold the exact mathematical result with **zero bit truncation** — this is why `a + b` for
two `q4_12_t` values does not itself produce a `q4_12_t` (it produces a 5-integer-bit
result); bind it to its own type (or let Python infer it) rather than assuming the sum has
the same type as its operands:

```python
sum_t = add.__annotations__["return"]   # the actual (wider) result type
```

`+`/`-` require both operands to share the same `frac_bits` (mismatched `frac_bits` raises
`TypeError` at the point you build the adder/subtractor — resize one operand first via
`make_fixed_resize`, below); `*` has no such constraint and returns a full-precision, exact
product (no rounding) with `frac_bits` equal to the sum of both operands' `frac_bits`.
Growth accounts for **mismatched signedness** too: adding/multiplying a signed and an
unsigned `fixed_t` grows the output 1 bit more than the naive `max(int_bits)+1` /
`int_bits_a+int_bits_b` textbook formula would suggest, matching exactly the same
sign-promotion rule Pypeline's native `intN_t`/`uintN_t` arithmetic already uses for any
plain mismatched-signedness expression (`int8_t + uint10_t` promotes to `int12_t`, not
`int11_t`) — this rule is literally the same shared code on both the native-simulation
path and real hardware elaboration, so there's no risk of it behaving differently in
`sim_call` versus synthesized hardware. **Narrowing is never an implicit side effect of
arithmetic** — if you want a smaller result, resize explicitly (next section).

Need the individual pieces instead of `register_fixed_ops`'s all-at-once self-pair
registration? `make_fixed_adder(a_t, b_t)`/`make_fixed_subtractor(a_t, b_t)`/
`make_fixed_multiplier(a_t, b_t)` build a single operator for any pair of `fixed_t` types
(not just `a_t` with itself) — useful for e.g. an accumulator of one width absorbing
products of another, without registering a global operator for every combination.
`make_fixed_negate(a_t)` (requires `a_t.signed`) builds unary `-` at the same width as its
input; like plain two's-complement negation elsewhere in this codebase, negating the
most-negative representable value wraps back to itself rather than growing a bit.

#### Resizing (rounding + saturation)

`make_fixed_resize(src_t, dst_t, rounding="truncate", overflow="wrap")` is the explicit,
opt-in narrowing/rounding operation — the only place bits are intentionally dropped. It
changes `int_bits`/`frac_bits`/signedness between any two `fixed_t` types, vendor-FIR-IP
"output precision control" style — e.g. rounding a wide accumulator down to a narrow
output sample:

```python
from fixed_point import make_fixed_t, make_fixed_resize

acc_t = make_fixed_t(12, 20)      # wide accumulator
sample_t = make_fixed_t(4, 12)    # narrow output sample
round_to_sample = make_fixed_resize(acc_t, sample_t, rounding="round_half_even", overflow="saturate")
```

`rounding` (only meaningful when narrowing the fraction, i.e. `src_t.frac_bits >
dst_t.frac_bits` — a no-op when widening or unchanged):
- `"truncate"` — drop the low bits (an arithmetic right shift, i.e. floor, not
  round-toward-zero — `-1.5` truncates to `-2`, not `-1`).
- `"round_half_up"` — ties always round toward `+∞`.
- `"round_half_even"` — banker's/convergent rounding: ties round to whichever neighbor is
  even.
- `"round_half_away"` — symmetric rounding: ties round away from zero.

`overflow` (applies regardless of whether the fraction narrowed): `"wrap"` (plain
two's-complement truncation) or `"saturate"` (clamp to `dst_t`'s representable
`[min, max]`, computed from `dst_t.int_bits`/`dst_t.signed`).

`quantize_coeffs(taps, coeff_t, rounding="round_half_even")` is the plain-Python (no
hardware) counterpart, for quantizing a list of floating-point filter taps into
`coeff_t`'s raw integer representation ahead of time (e.g. baking FIR coefficients into
`as_const`-initialized `Reg[T]`s) — each tap is quantized independently, with no
symmetry-preservation logic.

---

## Custom Operators

You can overload Python's binary and unary operators for specific pypeline types using
the registration functions:

```python
from pypeline import register_operator, register_left_operator, register_unary_operator
```

| Function | Matches | Use case |
|---|---|---|
| `register_operator(op, lhs_t, rhs_t, impl)` | exact `(lhs, rhs)` pair | custom addition on a struct type |
| `register_left_operator(op, lhs_t, impl)` | left type only | variable-width shift where rhs type is inferred |
| `register_unary_operator(op, operand_t, impl)` | operand type | custom negation |

`op` strings: `"PLUS"` (`+`), `"MINUS"` (`-`), `"INFERRED_MULT"` (`*` — not
`"MULT"`/`"TIMES"`), `"DIV"` (`/` — not `"DIVIDE"`), `"SL"` (`<<`), `"SR"` (`>>`),
`"NEGATE"` (unary `-`), `"GT"`/`"GTE"`/`"LT"`/`"LTE"` (`>`/`>=`/`<`/`<=`), `"EQ"`/`"NEQ"`
(`==`/`!=`).

`lhs_t`/`rhs_t`/`operand_t` can also be a **type matcher** — `any_uint_t`, `any_int_t`,
`any_integer_t`, `uint_upto(n)`, `int_upto(n)` — instead of one concrete type, letting a
single registration cover every width. In that case `impl` must be a **factory**
`func(lhs_t[, rhs_t]) -> hw_func`, called once per concrete type (pair) actually used and
memoized afterward:

```python
from pypeline import register_operator, any_integer_t

register_operator("PLUS", any_integer_t, any_integer_t, make_soft_add)
```

A shipped library of such factories lives in `include/pypeline/operators/` — soft
(bitwise-primitive) implementations for every integer operator that doesn't already have a
built-in lowering, plus alternate flavors (ripple vs. carry-select add, shift-add vs.
Karatsuba multiply, subtract vs. bitwise-magnitude compare):

```python
from operators.soft import register_soft_ops
register_soft_ops()                  # whole design, soft all the way to bitwise leaves
register_soft_ops(scope=my_func)     # only my_func's own body

from operators.soft import register_soft_mult_karatsuba
register_soft_mult_karatsuba()       # swap in a different flavor; last registration wins
```

Five operator families — int unary negate, int `>`/`>=`/`<`/`<=`, `/`, `%`, and
variable-amount shift — are registered soft **by default** (before your design file is even
imported), since they have no other inferred/raw-VHDL lowering. Register something more
specific in your own design and it overrides the default, same as any other registration.

The `floating_point` library (see [Factory-Generated Types: Floating-point types](#floating-point-types))
already does this registration for you for its predefined types:

```python
from floating_point import float32_t   # +, -, *, / already registered

@MAIN
def fp_add(a: float32_t, b: float32_t) -> float32_t:
    return a + b    # dispatches to the library's float32_add
```

Registering your own follows the same shape — `register_float_ops` (also in
`floating_point`) is a convenience wrapper around exactly this pattern:

```python
from floating_point import make_float_t, make_float_adder, register_operator

my_float_t = make_float_t(6, 9)             # a non-standard precision
my_adder = make_float_adder(my_float_t)
register_operator("PLUS", my_float_t, my_float_t, my_adder)
```

Registrations are global. To limit a registration to a single function's
elaboration, use the `scope=` keyword:

```python
register_unary_operator("NEGATE", my_t, negate_my_t, scope=my_function)
```

Registered operators dispatch both during hardware elaboration and during plain
Python/native simulation (`a + b` on two registered struct instances works the
same whether or not you're inside `sim_call`) — `@struct` types get `__add__` /
`__sub__` / `__mul__` / `__truediv__` / `__neg__` that consult these same
registries, raising a clear `TypeError` if nothing is registered for the pair
rather than falling through to `NamedTuple`'s default tuple concatenation/repeat.

---

## Global Signals

Global signals are module-level wires shared between `@MAIN` functions.
They are declared at module scope (outside any function) using a type annotation.

### `Wire[T]` — shared combinational signal

```python
main_a_in: Wire[uint1_t]  # input into main_a
main_a_out: Wire[uint1_t]  # output from main_a
@MAIN
def main_a():
    main_a_out = ~main_a_in

main_b_in: Wire[uint1_t]  # input into main_b
main_b_out: Wire[uint1_t]  # output from main_b
@MAIN
def main_b():
    main_b_out = ~main_b_in

# Connect output of A into B
# and output of B into A
# (nevermind this is bad combinatorial loop in synthesis)
@MAIN
def a_b_connect():
    main_b_in = main_a_out
    main_a_in = main_b_out
```

Rules:
- Each `Wire[T]` must have **exactly one** writer function (with exactly one instance
  in the design hierarchy).
- Any number of functions may read it.
- `Wire[T]` is **not** a register — it carries no value across clock cycles.

### Reading and writing the same wire in its writer function

A function may both read and write the same wire it drives — it behaves exactly like
a normal local variable: writes and reads interleave in program order, and the value
every *other* function sees that cycle is whatever this function's value is at the end
of its body.

```python
w: Wire[uint8_t]

@MAIN
def writer():
    w = 0
    w += 1   # read-after-write: normal local semantics — w is now 1
```

Reading a leaf **before** this function has written it (even earlier in the very same
statement list) returns **zero** — the implicit "driven with zeros" default every
writer function starts with, the same default an undriven struct/array field gets
(see below). It is not an elaboration error.

```python
point_out: Wire[point_t]   # point_t has fields .x, .y

@MAIN
def writer():
    # point_out.x has not been written yet this function -- reads as 0.
    point_out.x = point_out.x + 1   # writes 0 + 1 = 1
```

Only the sole writer function of a wire may read it this way. A function that merely
*reads* a wire it does not also write still cannot write to it (and a different
function may not write a wire another function already writes — see the exactly-one-
writer rule above).

### Partially-driven compound wires read undriven fields as zero

If a `Wire[T]`'s single writer function only assigns some fields of a struct (or some
elements of an array), the untouched fields/elements read as zero everywhere the wire
is read — exactly as if the writer had first assigned the whole wire to a zero value,
then overwritten the fields it actually drives.

```python
point_out: Wire[point_t]   # point_t has fields .x, .y

@MAIN
def writer():
    point_out.x = 5   # .y is never assigned

@MAIN
def reader():
    v = point_out   # v.x == 5, v.y == 0
```

### Splitting a compound wire across multiple writer functions

A `Wire[T]`/`Output[T]` of compound type (struct or array, nested arbitrarily) may be
driven by **more than one** writer function, as long as the set of scalar leaves each
writer drives is disjoint from every other writer's. Conceptually the wire behaves
**as if flattened into one independent global wire per scalar leaf**: each leaf is
driven by whichever function writes it, leaves nobody drives read as zero, and every
reader (including the writers themselves) sees each leaf's live value.

```python
main_ab_in:  Wire[uint1_t]   # input into main_a and into main_b
main_ab_out: Wire[point_t]   # output .x from main_a and .y from main_b

@MAIN
def main_a():
    main_ab_out.x = ~main_ab_in

@MAIN
def main_b():
    main_ab_out.y = ~main_ab_in

@MAIN
def a_b_connect():
    main_ab_in = main_ab_out.x ^ main_ab_out.y
```

What a writer may claim:
- **Any static path**, at any nesting depth: a top-level field (`w.x = ...`), a nested
  leaf (`w.a.x = ...`), a whole subtree (`w.a = some_point`), or a constant-indexed
  array element (`w.arr[2] = ...`, including indices from unrolled `for i in range(...)`
  loops — constant indices stay precise, so one writer covering `arr[0..1]` leaves
  `arr[2..3]` free for another).
- Writes may be **conditional** (`if en: w.x = v`): on cycles the write doesn't
  execute, that leaf reads zero — the clock-enable idiom.
- The writer may sit **anywhere in the hierarchy** — a helper function called (even
  several levels deep) from a `@MAIN`, not just a `@MAIN` body itself.
- A writer may also **read** the wire: leaves it drives itself follow normal
  local-variable semantics (read-before-write is zero, write-then-read is the new
  value), and leaves ANOTHER function drives read that function's live value.

Restrictions:
- Two writers claiming overlapping territory — the same leaf, or one claiming a
  subtree enclosing another's claim, or one whole-wire write plus any other writer —
  is an `ElaborationError` naming both functions and paths.
- Writes through a **variable** (non-constant) array index are not supported when the
  wire has more than one writer function.
- Each writer function must still have exactly one instance in the design hierarchy.
- Leaves no writer claims read as zero, exactly like the single-writer partial-write
  case above.
- All writers (and readers) of a split wire must share the same clock domain, exactly
  like any other shared global wire.

### `Input[T]` / `Output[T]` — top-level FPGA ports

`Input[T]` and `Output[T]` work like `Wire[T]` but also appear as ports in the generated
VHDL entity, matching FPGA pin constraint files.

```python
from pypeline import Input, Output, uint1_t

button: Input[uint1_t]    # physical FPGA input pin
led:    Output[uint1_t]   # physical FPGA output pin

@MAIN
def blinker():
    led = ~button          # invert the button to drive the LED
```

Port names match the pin names in your constraint (XDC/PCF) file exactly.

In simulation, drive an `Input[T]`'s per-cycle value with `@sim_input` — see
[Simulation](#simulation).

### Wire declarations have no initialiser

```python
my_wire: Wire[uint32_t]       # correct
my_wire: Wire[uint32_t] = 0  # error — initialisers are not allowed on Wire/Input/Output
```

---

### Part II — Temporal behavior

The four mechanisms below all let a hardware function's result take more than one clock
cycle to appear, but each trades area/throughput/complexity differently: an **ordinary
call** is same-cycle combinational (Part I). `AUTOPIPELINE` is multi-cycle and
**pipelined** — throughput-oriented: one full copy of your logic, sliced into stages,
accepting a new input every cycle. `AUTOFSM` is multi-cycle and **folded onto shared
hardware** — area-oriented: one copy of each distinct operation, reused across states.
`MULTI_CYCLE` is multi-cycle and **low-throughput**: a single slow combinational path
given more than one cycle to settle, with no new input accepted until it's done. And a
**stream wrapper** (`make_stream_pipeline`, `make_valid_ready_mcp`, covered later
alongside the other stream material in Part III since they're built on `stream_t` and
`@interface`) layers a valid/ready handshake protocol around any of the above so
neighboring hardware doesn't need to know which one it's talking to.

## Tool-Chosen Implementation: `AUTOPIPELINE(...)` and `AUTOFSM(...)`

```text
AUTOPIPELINE -- spread across SPACE (throughput):

  in -->[stage 1]--|Reg|-->[stage 2]--|Reg|-->[stage 3]--> out
         (one full copy of the logic, sliced into pipeline stages;
          a new input can be accepted every cycle)

AUTOFSM -- spread across TIME (area):

           +-----------------+
  in ----->|  ONE shared op  |<-----+
           +--------+--------+      |
                    |         state/cycle
                    v          counter
              (result used a few    |
               cycles later) -------+
         (one copy of each distinct operation, reused across states)
```

By default, a function called from inside a register or feedback context must complete
**combinationally, in the same cycle** as its caller — the synthesiser is not free to
split its logic across multiple clock cycles. That's normally what you want for a small
state machine. But sometimes you want to call a large, otherwise-combinational pipeline
stage (a multiplier, a divider, a deep arithmetic chain) from inside such a context, and
you're fine with it taking several cycles internally — its result simply appears a fixed
number of cycles later.

`AUTOPIPELINE(func)` produces a callable tag object (the same all-caps factory style as
`MULTI_CYCLE[...]`) that tells the synthesiser it's allowed to insert pipeline registers
inside calls made through it, overriding the normal "must stay combinational here" rule —
and, unlike a plain pragma, it exposes the **discovered stage count** back to your
Python as `.latency`:

The function does not need to be pre-divided into helpers that each happen to fit one
clock. Elaboration exposes the primitive operations and their dependency wiring even
when the body is one flat sequence, and the planner may register legal operation outputs
or genuinely split supported wide arithmetic leaves. Helper boundaries are optional
structure and a placement tie-break, not a prerequisite for autopipelining. See
[`SYN_DESIGN.md`](SYN_DESIGN.md) and
[`RAW_VHDL_DESIGN.md`](RAW_VHDL_DESIGN.md) for the lowering rules.

```python
MY_AP = AUTOPIPELINE(some_func)           # tool picks how many stages
MY_AP = AUTOPIPELINE(some_func, depth=2)  # force 2 clocks / register slices

@hw_func
def my_pipeline(i: my_struct_t) -> my_struct_t:
    return MY_AP(i)                       # some_func(i), autopipelined

MY_AP.latency    # int: the pipeline depth the tool chose; 0 until known
```

Build reports distinguish inserted register **slices** from combinational pipeline
**stages**: zero slices is one stage, and `N` serial slices separate `N + 1` stages.
The explicit `depth` and discovered `.latency` are the core's clock delay in inserted
register slices, not the number of combinational regions. Thus `depth=2` separates
three combinational regions and reports two clocks of core latency. Any explicit
input/output registers around the call add their own cycles.

`func` must already be `@hw_func`-decorated. In simulation, `MY_AP(x)` is an identity
passthrough (it just runs `func(x)`), so `sim_call` behaves identically with or without
it.

### `.latency`: reading back the discovered pipeline depth

`.latency` is an ordinary Python `int` you can use for elaboration-time sizing — most
usefully to size FIFOs/counters that sit next to the free-running pipeline (this is
exactly how `make_stream_pipeline` sizes its output FIFO automatically, see
[Pipelined Stream Wrappers: `make_stream_pipeline`](#pipelined-stream-wrappers-make_stream_pipeline)). It reads **0**:

- always in plain native Pypeline sim (`pypeline_sim.py` run directly, or
  `pypelinec --sim --comb` — no synthesis ever runs),
- always in `--comb` / `--no_synth` / `--yosys_json` builds (no throughput sweep runs),
- during the bootstrap elaboration pass of a real synthesizing build.

On a real build, the `pypelinec` driver's **pin-and-confirm** loop makes the value real:
the design is first elaborated with `.latency` reading 0 and swept as usual; the
discovered stage counts are then installed and the design re-elaborated, with the
previous sweep's pipelining carried over as pinned seeds so only a **seeded confirmation
synthesis** runs per pass (not a fresh sweep). The loop repeats until the stage counts
harvested from the built result equal the values the design's Python consumed — an extra
pass is normal when realizing the seeded slices hierarchically (e.g. into pipelined
built-in div entities with their own stage granularity) changes the total — so on exit
the `.latency` your Python consumed is guaranteed equal to the stage count of the
hardware actually built. Designs that never read `.latency` pay nothing: the loop exits
after the ordinary single sweep. (See `docs/SYN_DESIGN.md` for the loop's details and
failure modes.) A non-`--comb` `pypelinec --sim` run then launches native simulation
with those same latencies installed **and emulated** — `.latency` reads the real value
during the sim's design import too, and every AUTOPIPELINE call site behaves as an
N-stage pipeline (see the "Pipelined native sim" section in `docs/pypeline_sim_DESIGN.md`).

**Construction timing matters**: construct `AUTOPIPELINE(...)` once, eagerly, as plain
Python — typically at a factory function's own top level — and capture the object by
closure into whatever `@hw_func` body calls it. That's what makes `.latency` readable
by the surrounding Python. Constructing it inline inside a `@hw_func` body still
pipelines correctly, but nothing outside that body can read its `.latency`.

### Example

This mirrors the shape of `examples/autopipelined_submodules.c`: a free-running
combinational pipeline stage, instantiated from inside a function that also has a
register (so without `AUTOPIPELINE`, the call would have to be a single-cycle
combinational instance):

```python
@hw_func
def pipeline_stage(x: uint32_t) -> uint32_t:
    return x / ~x   # some deep/slow, multi-cycle-worthy combinational logic

PIPELINE_STAGE_AP = AUTOPIPELINE(pipeline_stage)

@hw_func
def wrapper(pipeline_in: uint32_t) -> uint32_t:
    # `phase` is just some placeholder state — a stand-in for any small FSM
    # running alongside the pipeline. It is what makes this a register/feedback
    # context, so that without AUTOPIPELINE the `pipeline_stage` call would be
    # forced to complete combinationally within this same cycle.
    phase: Reg[uint2_t]
    phase = phase + 1

    # AUTOPIPELINE overrides that: the synthesiser may slice pipeline_stage's
    # logic across multiple cycles.
    return PIPELINE_STAGE_AP(pipeline_in)
```

`Reg[T]` and bare struct/array locals (like `rv` above) only simulate correctly under
`sim_call` when their own function carries `@hw_func` (or `@MAIN`) — see
[Registers: `Reg[T]`](#registers-regt) / [Parametric Hardware with Factory Functions](#parametric-hardware-with-factory-functions).

See `src/tests/pypeline_tests/inst/autopipeline_test.py` for the full example.

### Boundary registers around an AUTOPIPELINE'd call

To register the pipeline's inputs/outputs at its boundary rather than leaving them
combinational, wrap the call with plain unconditional `Reg[T]`s (the same pattern
`make_stream_pipeline` uses internally):

```python
@hw_func
def pipeline_stage_registered(x: uint32_t) -> uint32_t:
    in_reg: Reg[uint32_t]
    out_reg: Reg[uint32_t]
    rv: uint32_t = out_reg
    out_reg = PIPELINE_STAGE_AP(in_reg)
    in_reg = x
    return rv
```

Note `.latency` reports the AUTOPIPELINE'd core's own depth only — boundary registers
you add around the call are yours to count (e.g. total latency here is
`1 + PIPELINE_STAGE_AP.latency + 1`).

### `AUTOFSM(...)`: the opposite trade-off

`AUTOPIPELINE` spends area to get throughput: one full copy of your function's
hardware, sliced into stages, accepting a new input every cycle. `AUTOFSM` spends
time to get area: **one copy of each distinct operation**, reused across several
cycles.

```python
@hw_func
def next_state(s: state_t) -> state_t:    # pure: no Reg, no Feedback, no globals
    ...

UPDATE = AUTOFSM(next_state)              # tool picks how many states

@MAIN(40.0)
def top() -> state_t:
    state: Reg[state_t]
    req: UPDATE.in_stream_t               # auto-generated {data, valid} struct
    req.data = state
    req.valid = start_pulse
    resp = UPDATE(req)                    # resp: {data, valid}
    if resp.valid:
        state = resp.data
    return state

UPDATE.latency                            # fixed in→out cycle count; 0 until known
```

Twelve identical adds in `next_state` — whether written as a Python loop that
elaborates unrolled, or as twelve separate lines — become **one** adder used in
twelve different states. Nothing in your source says how many states to use or
what shares what: the build measures your operations' delays, schedules them
against the clock goal, and prints what it did:

```
AUTOFSM pypeline_design_next_state: 28 ops -> 9 shared unit(s), 8 states,
        latency 9 clks, budget 22.50 ns/state (scale 0.900), worst state 13.10 ns
  BIN_OP_PLUS_int16_t_int16_t x12 -> 1 unit
  ...
```

This is the right tool when a computation has a lot of *slack* — something that
runs once per video frame, or once per packet, while a million cycles go by.
Parallel combinational logic for such a thing is hardware sitting idle almost
all of the time.

**The contract**

- `func` must be `@hw_func`, **pure** (no `Reg`/`Feedback`/global wires anywhere
  in its call subtree), and take exactly **one** annotated argument with an
  annotated return type. Bundle several inputs into an `@struct` — the same rule
  `make_stream_pipeline` and `make_valid_ready_mcp` follow.
- The argument is a `{data, valid}` struct: use `MY_FSM.in_stream_t`, or any
  structurally identical type (`make_stream_t(in_t)` works).
- An input is accepted **only while the FSM is idle**. A `valid` pulse asserted
  while it is busy is IGNORED — there is no `ready` signal in this version.
  Space requests at least `.latency` cycles apart; that is what `.latency` is
  for.
- The result arrives with a one-cycle `valid` pulse exactly `.latency` cycles
  after the accepted input. `.data` holds the last result in between. Initiation
  interval == `.latency`.
- Construct `AUTOFSM(...)` once, eagerly, at module or factory level and capture
  it by closure — same rule and same reason as `AUTOPIPELINE`.

**Write the caller to react to `valid`, not to count cycles.** `.latency` is 0
in plain native sim and in `--comb`/`--no_synth` builds (where the call site is
a zero-latency passthrough) and a real number in a full build. Code that waits
for `resp.valid` is correct in both, and stays correct when the tool changes its
mind about the state count:

```python
busy: Reg[uint1_t]
req.valid = 0
if busy == 0:
    req.valid = 1
    busy = 1
resp = MY_FSM(req)
if resp.valid:
    result = resp.data
    busy = 0
```

**If the FSM misses timing**, the build says so, shrinks its per-state budget,
reschedules into smaller states and tries again — the same iteration you get
from the sweep adding pipeline stages. `--autofsm_budget_scale` sets the
starting point (default `0.9` of the clock period) if you want to begin tighter
or looser. One thing it cannot fix: a single indivisible operation slower than
your clock (a float64 multiply, say). That is reported as `AT FLOOR`, because no
number of extra states makes one multiplier faster.

**Capping the latency.** `AUTOFSM(func, max_latency=N)` says the result must
arrive within N cycles. Sharing everything onto one unit of each kind is the
smallest design and the slowest, so a cap is met the only way it can be — by
building a second copy of whatever is forcing the states:

```python
UPDATE = AUTOFSM(next_state, max_latency=8)
```

It is a hard constraint. If no schedule meeting your clock goal fits in N
cycles, the build fails and tells you the latency it actually needs, rather than
handing back something slower than you asked for.

**The build also looks for the smallest FSM it can find**, and prints what it
decided:

```
AUTOFSM pypeline_design_next_state: 28 ops -> 9 shared unit(s), 8 states, ...
  area search: -7.8% area vs sharing everything (estimated 260 against 282),
               3 kind(s) opened up, 1 kind(s) given extra unit(s),
               110 candidate schedule(s) tried
```

Sharing is not free: every shared unit needs a multiplexer picking its operands
per state, and more states means more registers holding values in between. For
an expensive unit — a multiplier, a wide adder — sharing wins easily. For a
cheap one, the multiplexer can cost more than a second copy of the unit would,
and the search will decline to share it. It also goes the other way, breaking an
operation down into smaller pieces when several different operations turn out to
be built from the same ones and can then share those instead. If soft-operator
implementations are available (`include/pypeline/operators/`) it can follow that
all the way down to logic gates — and will normally decide, correctly, that
gates are far too small a thing to share.

The search never returns something bigger or slower than plain share-everything,
so there is nothing to turn on. `--autofsm_no_area_sweep` turns it *off*, which
is useful mainly for comparing the two.

**How much the search can do depends on your clock goal**, and not in the
direction people expect. A high goal FORCES decomposition — an operation that
cannot fit one state is split whether or not that saves area — but leaves the
pieces shared. A LOW goal is what gives the search room to decompose *by
choice*: with a budget big enough for the whole operation, keeping it atomic is
the starting point and opening it up is a decision made on area grounds. So if
you want the smallest design and do not care about speed, ask for a low clock
and let the search work; asking for a high one takes the choice away from it.
See [`docs/AUTOFSM_DESIGN.md`](AUTOFSM_DESIGN.md) for what is and is not
openable (signed multiplies and floating point are not).

`--autofsm_sweep_debug` prints one line per candidate the search considers —
the move, its estimated area, and why it was accepted or rejected. Without it
the build log reports only the final choice, which makes "the search declined
to move" indistinguishable from "the search never looked".

`--autofsm_open SUBSTR` and `--autofsm_unshare SUBSTR=N` skip the search and
build one explicitly chosen point instead: open up the unit whose entity name
contains `SUBSTR`, or give it `N` copies. These exist for measurement — the
tool cannot read area back from a synthesis tool, so the only way to check that
the search's answer really is the smallest is to build the alternatives it
passed over and count cells, which is what
`src/tests/pypeline_tests/inst/autofsm_min_area_verify_test.py` does. An
ambiguous or unmatched `SUBSTR` is an error rather than a silent no-op.

### Control path — `--autofsm_ctl`

Something has to decode the state into "which operand does this unit take",
"which registers are written now" and "what is the next state". `--autofsm_ctl`
picks how, and the default is normally right:

| value | how state is decoded | comparators per FSM |
|---|---|---|
| `v3` (default) | constant lookup tables indexed by the state | one (the accept) |
| `v2` | an equality comparator per state per unit, in priority chains | O(states × units) |
| `onehot` | one bit per state; every control signal is a bit read | zero |

`v2` exists for A/B comparison — it is what the tool used to emit, and it is
measurably both bigger and slower. `onehot` is smaller and faster still on every
design measured so far, but spends a flip-flop per state where the others spend
`log2(states)`, so it is not the default; try it on FSMs with few states and a
tight clock. The choice is part of the schedule's identity, so switching it
re-measures rather than reusing timing from the other one.

Working examples: `examples/pypeline/autofsm_donut_update.py` (per-frame
rotation math) and `examples/pypeline/float_sine_autofsm.py` (a float64
polynomial onto one multiplier). Full design notes in
[`docs/AUTOFSM_DESIGN.md`](AUTOFSM_DESIGN.md).

---

## Multi-Cycle Paths: `MULTI_CYCLE[...]`

Combinational logic normally has to finish settling within a single clock period — that's
what the synthesiser's timing analysis assumes by default. Sometimes that's overly
strict: a slow operation (integer division, a deep arithmetic chain) sits between two
registers, and you know it's fine for it to take several clock periods to settle because
the surrounding logic only samples the result every `N` cycles anyway (e.g. inside a small
FSM that only advances every `N` cycles). `MULTI_CYCLE[...]` tells the synthesiser to
relax its setup-timing check between two specific registers by `N` cycles instead of one.

```python
from pypeline import Reg, MULTI_CYCLE

def my_fsm(i: my_struct_t) -> my_struct_t:
    o: my_struct_t
    MC = MULTI_CYCLE[32]                      # allow up to 32 cycles between these two regs
    data0: Reg[my_struct_t, MC.start]
    data1: Reg[my_struct_t, MC.end]
    o = data1
    data1 = big_comb_multi_cycle_func(data0)  # slow combinational logic — gets up to 32 cycles
    data0 = i
    return o
```

`MULTI_CYCLE[ncycles]` produces a tag; `.start` and `.end` mark which of the two `Reg[T]`
declarations is the source and which is the destination of the relaxed timing path —
`.start` is where the path begins (the register whose output feeds the slow logic),
`.end` is where it's captured (the register that's allowed to take longer to settle).
Each tag must be used exactly twice: once as `.start`, once as `.end`, on two different
`Reg[T]` declarations in the same function.

This is purely a synthesis timing constraint — it has no effect on simulation, and no
effect on what value ends up in the registers, only on how much time the tool is allowed
to assume is available for the logic between them to settle.

**Requires Vivado.** Like `PART()`, this only does something during real FPGA synthesis;
without a `PART()` target it has no effect. See
`src/tests/pypeline_tests/inst/multi_cycle_test.py` (translated from
`examples/mcp/mcp_test.c`) for the full example, including the `PART(...)` call needed to
target a real device.

### Wrapping a whole slow function

The launch/capture pattern above is the right tool when a multi-cycle path sits between
two registers you are already managing yourself inside a larger function. When the slow
logic is instead a whole standalone function, `make_valid_ready_mcp` wraps it in exactly
this FSM for you and presents the result as a valid/ready stream. Its ports are stream
[interfaces](#bidirectional-ports-interface), so it is covered later alongside the
other function-to-stream wrapper — see
[`make_valid_ready_mcp`](#multi-cycle-stream-wrapper-make_valid_ready_mcp).

---

### Part III — Ports and streams

The next six sections build a single layered stack, each one on top of the last:
`kept_data_bus_t` (a lane of data plus a per-lane "keep" bit) underlies
`ndarray_fragment_t` (a partially-filled N-dimensional chunk), which underlies
`stream_t` (the generic `{data, valid}` payload type), which underlies `@interface`
(a full bidirectional valid/ready port pairing), which AXI-Stream specializes into an
industry-standard bus, with FIFOs and the two stream wrappers as the connective tissue
between them. As `include/pypeline/axi/axis.py`'s own docstring puts it, AXI-Stream
"composes the three layers above into a single factory."

## Keep-Tagged Lanes: `kept_data_bus_t`

A common streaming pattern is N parallel lanes of data, each with its own "is this lane
actually valid this transfer" bit — AXI-Stream's `tdata`/`tkeep` is the best-known example,
but the same shape shows up any time you transport a partially-filled chunk of a larger
array one beat at a time. `kept_data_bus_t`, from `include/pypeline/kept_data_bus.py`,
captures exactly that shape, generic over both the lane count and the element type:

```python
from pypeline import uint8_t
from kept_data_bus import make_kept_data_bus_t

bus4_t = make_kept_data_bus_t(uint8_t, 4)   # 4 lanes of uint8_t + a 4-bit keep mask

def make_lane(b: bus4_t, i: int) -> uint8_t:
    return b.data[i] if b.keep[i] else 0
```

`make_kept_data_bus_t(data_t, n)` returns a struct with two fields:

| Field | Type | Meaning |
|---|---|---|
| `.data` | `data_t[n]` | the N lanes of payload |
| `.keep` | `uint1_t[n]` | per-lane "this lane is valid" flag |

`data_t` doesn't have to be a byte — it can be any pypeline type, including a struct. The
result is only literally AXI-Stream-shaped when `data_t` is `uint8_t`; with another element
type it's the same per-lane keep-masking generalized to a stream of structs (see
[AXI-Stream](#axi-stream-axis_t)).

This layer has no `valid` bit and no end-of-transfer flag (`eod`/`tlast`) of its
own — those are added by the layers above it.

---

## N-Dimensional Stream Fragments: `ndarray_fragment_t`

AXI-Stream's `tlast` marks the end of one dimension — the end of a packet. Many real
streams have more than one nested boundary: a video stream has an end-of-line *and* an
end-of-frame, for instance. `ndarray_fragment_t`, from `include/pypeline/ndarray.py`,
generalizes a single `tlast` bit into one end-of-dimension flag per dimension of whatever
N-dimensional array the stream is serializing:

```python
from pixel import pixel_t   # whatever your pixel struct is
from ndarray import make_ndarray_fragment_t

video_frag_t = make_ndarray_fragment_t(pixel_t, 2)   # eod[0]=end of row, eod[1]=end of frame

def track_position(frag: video_frag_t, x: uint16_t, y: uint16_t) -> ...:
    next_x: uint16_t = x + 1
    next_y: uint16_t = y
    if frag.eod[0]:           # end of row
        next_x = 0
        next_y = y + 1
    if frag.eod[1]:           # end of frame
        next_y = 0
    ...
```

`make_ndarray_fragment_t(frag_t, ndims)` returns a struct with two fields:

| Field | Type | Meaning |
|---|---|---|
| `.frag` | `frag_t` | the payload for this one transfer |
| `.eod` | `uint1_t[ndims]` | per-dimension "end of dimension k" flags; `eod[0]` is the innermost dimension (AXIS `tlast`'s direct equivalent) |

The field is named `.frag` rather than `.data` specifically so that nesting
`ndarray_fragment_t` inside [`kept_data_bus_t`](#keep-tagged-lanes-kept_data_bus_t)
(which already has a `.data` array field) and inside
[`stream_t`](#streams-stream_t) (which already has a `.data` payload field)
doesn't produce an ambiguous `.data.data.data` chain.

`frag_t` can be anything — a single struct (one whole element per transfer, as above) or a
[`kept_data_bus_t`](#keep-tagged-lanes-kept_data_bus_t) (multiple byte/element lanes per
transfer, the AXI-Stream case — see [AXI-Stream: `axis_t`](#axi-stream-axis_t)).

---

## Streams: `stream_t`

A stream carries a payload forward, one beat per clock, tagged with a **valid** bit that says
whether this cycle's payload is really there. `stream_t`, from
`include/pypeline/stream/stream.py`, is exactly that pair — data flowing **forward only**, with
nothing travelling back:

```text
   upstream                                   downstream
      |----data, valid (forward)------------------>|
      |<---ready (reverse, from @interface)---------|

   A transfer happens on any cycle where valid=1 AND ready=1 (once paired
   with a ready signal via @interface -- stream_t alone carries no ready).
```

```python
from stream.stream import make_stream_t

uint32_stream_t = make_stream_t(uint32_t)

@hw_func
def scale_by_two(s: uint32_stream_t) -> uint32_stream_t:
    o: uint32_stream_t
    o.data = s.data * 2
    o.valid = s.valid      # a valid input this cycle produces a valid output
    return o
```

`make_stream_t(data_t)` returns a `@struct` with two fields — so `make_stream_t(uint32_t)` is
the struct `{data: uint32_t, valid: uint1_t}`:

| Field | Type | Meaning |
|---|---|---|
| `.data` | `data_t` | the payload |
| `.valid` | `uint1_t` | whether `.data` is valid this cycle |

`data_t` is typically an [`ndarray_fragment_t`](#n-dimensional-stream-fragments-ndarray_fragment_t)
(giving end-of-dimension flags) or a [`kept_data_bus_t`](#keep-tagged-lanes-kept_data_bus_t)
(giving per-lane keep flags), but it can be any type — `make_stream_t(uint32_t)` above is a
plain stream of integers with no `eod`/`keep` layer at all.

Use `stream_t` on its own wherever data only flows forward: a free-running pipeline stage, or a
value built and passed along whose consumer can always accept it. When a consumer must instead
be able to say "not this cycle" — apply **backpressure** — the payload needs a companion signal
travelling the *opposite* way. A signal flowing the other direction does not belong in the same
struct as the data, so the next section introduces the general way pypeline bundles
opposite-direction signals into one port — the **`@interface`** — out of which the valid/ready
stream falls as the feedforward `stream_t` plus a reverse `ready`.

**See also:** [Bidirectional Ports: `@interface`](#bidirectional-ports-interface) ·
[Keep-Tagged Lanes: `kept_data_bus_t`](#keep-tagged-lanes-kept_data_bus_t) ·
[N-Dimensional Stream Fragments: `ndarray_fragment_t`](#n-dimensional-stream-fragments-ndarray_fragment_t) ·
[FIFOs: `make_stream_fifo`](#fifos-make_stream_fifo)

---

## Bidirectional Ports: `@interface`

Real interfaces are rarely one-directional. A valid/ready stream sends `data`/`valid`
downstream but takes `ready` back; a credit-based bus sends a payload and receives credits; a
request/acknowledge pair goes both ways. An **`@interface`** bundles the signals of one port
that travel together, *regardless of direction*: plain fields are **feedforward** (out along the
port), and fields wrapped in `Feedback[T]` are **reverse** (back along it). Nothing about the
mechanism is stream-specific — the reverse channel can be any number of fields of any type:

```python
from interface.interface import interface

@interface
class bus_intrf(NamedTuple):
    payload: uint32_t
    go:      uint1_t
    credit:  Feedback[uint4_t]   # reverse — any width, not just a ready bit
    halt:    Feedback[uint1_t]
```

```text
   upstream                                     downstream
      |----- payload, go (forward, .fwd_t) --------->|
      |<---- credit, halt (reverse, .fb_t) -----------|
```

### The two halves

An interface is not itself a hardware type — a hardware function never takes a whole `bus_intrf` as
a port. Instead, `@interface` attaches two (or three) ordinary `@struct`s directly onto the class:

```python
bus_intrf.fwd_t     # feedforward half: {payload, go}
bus_intrf.fb_t      # reverse half:     {credit, halt}
bus_intrf.stream_t  # the plain {data, valid} half nested at .fwd_t.stream,
                     # only for stream-shaped interfaces (None otherwise -- see below)
```

- `.fwd_t` gathers the plain fields into the **feedforward** struct.
- `.fb_t` gathers the `Feedback[T]` fields — *unwrapped* to their inner type (`Feedback[uint4_t]`
  → `uint4_t`) — into the **reverse** struct.

There is no separate `make_interface_type`/`make_interface_feedback_type` to call, and no local
alias to invent either: always write `bus_intrf.fwd_t` (etc.) directly at each use site rather than
binding it to a shorter name first. A bound alias (`bus_t = bus_intrf.fwd_t`) throws away exactly
the information `.fwd_t`/`.fb_t` exist to preserve — a reader can no longer tell from the name
alone whether a type is a paired port half or a standalone struct (see
`docs/PY_TO_LOGIC_DESIGN.md` for why this also matters to the elaborator itself in
factory-closure contexts). This is also why the interface-holding variable
itself gets a distinct suffix, so the two kinds of name are never visually interchangeable:

- **`_intrf`**: a variable holding the `@interface` class itself (`bus_intrf`) — always accessed
  directly (`bus_intrf.fwd_t`), never re-aliased.
- **`_if`**: an argument/field name holding an *instance* of one port half (see the naming
  convention below) — unrelated to `_intrf`, and never confused with it since the suffixes differ.

### Port types vs ordinary signal types

Two related but separate questions come up constantly with interfaces: *what kind of value
is this* (plain value, stream, or interface half), and *what kind of place is this value
stored* (local, register, feedback, global wire). Neither tree implies the other — any
storage kind on the right can hold any value kind on the left, **except** that `.fwd_t`/
`.fb_t` may only ever sit at a real port boundary (see
[Where `.fwd_t`/`.fb_t` may appear — and where it may not](#where-fwd_tfb_t-may-appear--and-where-it-may-not)
below):

```text
value kind:                          storage kind:

ordinary value (T)                   T
    |                                 ├── local variable
    ├── stream_t                      ├── Reg[T]
    |     {data, valid}               ├── Feedback[T]
    |                                 ├── Wire[T]
    └── interface (@interface)        ├── Input[T]
          ├── .fwd_t  (forward half)  └── Output[T]
          └── .fb_t   (reverse half)
```

`.stream_t` is a plain value like any other — it can sit in a local, a `Reg[T]`, a global
`Wire[T]`, anywhere. `.fwd_t`/`.fb_t` are the exception: they mark "this value is one half
of a real port pairing", so they're restricted to exactly the places a real port boundary
can occur.

### Ports: two halves under one name

Because the two halves travel opposite ways, a module carries a port as **both** halves — one as
an argument, one as a return field — paired only by sharing the **same name**. There is no
required naming convention (no `ready_for_`/`_ready`/`_rdy` affix); the port name is whatever you
choose. Direction follows from which side holds the feedforward half:

- an **input** port takes the feedforward half as an argument and returns the reverse half;
- an **output** port does the opposite.

**Convention (enforced by a lint): suffix the port variable with `_if`.** A lint warns if a
paired port name doesn't end in `_if` (see `docs/PY_TO_LOGIC_DESIGN.md` for the check itself)
— not a hard error (it's a style convention, not a correctness rule), but every port name
in this codebase follows it. Because one name legitimately means two
different types depending on which side you're reading (an argument of the feedforward type, a
return field of the reverse type — or vice versa for an output port), a bare port name like
`axis_in` or `poly_key_out` reads as if it were two different same-named signals instead of one
bidirectional port. Suffixing the *variable* with `_if` (`axis_in_if`, `key_if`, `to_pipeline_if`)
marks it as one port, and — since it's a different suffix from the `_intrf` on the `@interface`
*type* itself — the two never collide. When a module has two same-shaped ports going opposite
ways, name them accordingly: `data_in_if`/`data_out_if`, `axis_in_if`/`axis_out_if`.

```python
@struct
class x_to_y_t(NamedTuple):
    x_if: bus_fb_t   # input port x_if: its reverse half (credit/halt) travels out
    y_if: bus_t      # output port y_if: its feedforward half (payload/go) travels out

@hw_func
def x_to_y(x_if: bus_t, y_if: bus_fb_t) -> x_to_y_t:
    o: x_to_y_t
    o.y_if = x_if    # feedforward: pass x_if's payload/go out on y_if
    o.x_if = y_if    # feedback:    pass y_if's credit/halt back on x_if
    return o
```

### The stream interface: valid/ready handshaking

A valid/ready stream is the most common interface, and the one the whole streaming library is
built on. Its forward field **nests** a plain `make_stream_t(data_t)` rather than re-declaring
`data`/`valid` itself, so the with-ready interface's forward half and a standalone valid-only
stream are never two independently-shaped twins requiring a field-by-field conversion — the
with-ready side's data+valid *is* a `make_stream_t(data_t)` value, reached through `.stream`:

```python
from stream.stream import make_stream_interface, make_stream_t

# make_stream_interface(uint32_t) is literally this interface:
@interface
class uint32_stream_intrf(NamedTuple):
    stream: make_stream_t(uint32_t)   # nested plain {data, valid} struct
    ready:  Feedback[uint1_t]         # the one reverse field
```

so its halves are, always accessed directly off `uint32_stream_intrf` (never re-aliased):

```python
uint32_stream_intrf = make_stream_interface(uint32_t)
uint32_stream_intrf.fwd_t     # {stream: {data, valid}}
uint32_stream_intrf.fb_t      # {ready}
uint32_stream_intrf.stream_t  # the plain {data, valid} nested at .fwd_t.stream
```

A standalone `make_stream_t(uint32_t)` ([Streams: `stream_t`](#streams-stream_t)) is a plain `{data, valid}` struct with no `@interface`
involved at all — it never needed one to define itself. `uint32_stream_intrf.stream_t` is exactly
that type (replacing the older `<fwd_t>.typeof("stream")` idiom — the shortcut belongs on the
interface, not on a forward-half value), so crossing between "a valid-only value" and "the
data+valid half of a real backpressured port" is a single `.stream` field access/assignment, never
a per-field copy:

```python
plain: make_stream_t(uint32_t) = uint32_stream_intrf.stream_t(data=5, valid=1)
port_val: uint32_stream_intrf.fwd_t = uint32_stream_intrf.fwd_t(stream=plain)  # wrap into a port value
plain_again = port_val.stream                                                  # unwrap back out
```

A module gives a stream port the same two-halves-one-name treatment as any interface — an
**input** stream returns its `ready`, an **output** stream takes one. Field access on a real port
goes through `.stream`; `.ready` is unaffected (the reverse half was never nested):

```python
@struct
class relay_t(NamedTuple):
    stream_in_if:  uint32_stream_intrf.fb_t   # input port: ready travels back out
    stream_out_if: uint32_stream_intrf.fwd_t  # output port: data+valid travel out

@hw_func
def relay(
    stream_in_if: uint32_stream_intrf.fwd_t, stream_out_if: uint32_stream_intrf.fb_t
) -> relay_t:
    o: relay_t
    o.stream_out_if = stream_in_if               # forward the data+valid downstream
    o.stream_in_if.ready = stream_out_if.ready   # forward the backpressure upstream
    return o

@hw_func
def show_fields(stream_in_if: uint32_stream_intrf.fwd_t) -> uint1_t:
    return stream_in_if.stream.valid   # .stream. reaches the nested data+valid
```

**Naming convention.** Two distinct suffixes, never interchangeable:

| Suffix | Is | Accessed as | Example |
|---|---|---|---|
| `_intrf` | the whole interface, both directions | `some_intrf.fwd_t`/`.fb_t`/`.stream_t`, always direct | `uint32_stream_intrf` |
| `_if` | an argument/field holding *one instance* of a port half | the value itself, typed `some_intrf.fwd_t`/`.fb_t` | `stream_in_if`, `stream_out_if` |

`.fwd_t`, `.fb_t`, and `.stream_t` are attributes on the `_intrf` — there is no third kind of
bound-alias name (`uint32_stream_t`, `uint32_stream_fb_t`, ...) to introduce; write the attribute
access out at each use site instead, even where it repeats.

A genuinely valid-only stream (no `@interface`, no reverse half at all) is built directly with
`make_stream_t(T)`/`axi.make_axis_t(...)` — see [Streams: `stream_t`](#streams-stream_t) — not by taking the `.fwd_t` half of a
with-ready interface and ignoring its `.fb_t`; the latter still declares a real reverse half that
the def-site check (`InterfacePortError`) will demand a caller pair.

The reverse channel is not limited to a one-bit `ready`: `make_stream_interface(data_t,
feedback_t=...)` widens it to a credit count or a struct of flags, just as `bus_intrf` above
carries `credit`/`halt`. Every streaming building block that follows —
[AXI-Stream](#axi-stream-axis_t), [FIFOs](#fifos-make_stream_fifo),
[pipelined wrappers](#pipelined-stream-wrappers-make_stream_pipeline), and the
[DSP blocks](#dsp-filters--signal-conditioning) — declares its ports as these two interface halves.

### Interface functions: write feedforward, get the reverse wired

Wiring handshake modules together normally means hand-threading the reverse signal back
through a `Feedback[T]` while the forward data flows on. A function whose annotations use a
whole `@interface` is an **interface function**: you write only the feedforward connections
and the reverse direction is generated. No decorator is needed — a whole interface is not a
valid hardware type, so annotating with one is unambiguous.

```python
from interface.interface_func import make_hw_func_from_interface_func

def two_in_series(stream_in: chan) -> chan:
    a = inc2(stream_in)
    b = inc5(a.stream_out)
    return b.stream_out

two_series, two_series_t = make_hw_func_from_interface_func(two_in_series)
```

Instantiation stays explicit, so the boundary where real hardware enters a design is always
visible. The generated pair is an ordinary `(hw_func, struct_t)`, identical in shape to what a
hand-written module declares — which is why the two compose freely in either direction.

```text
hand-written module          two_series (interface func)
+----------------+           +--------------------------+
| calls          |--fwd_t--->| a = inc2(stream_in)       |
| two_series(x)  |<--fb_t----| b = inc5(a.stream_out)    |  <-- reverse (ready)
|                |           | return b.stream_out       |     wired back for you
+----------------+           +--------------------------+
```

**The wiring rule, in full:** calls are emitted in source order, and an edge gets a
`Feedback[T]` whenever the value's source is emitted *after* the destination that consumes
it. This is direction-agnostic. It inserts a feedback on a reverse edge (ordinary
backpressure) and equally on a *feedforward* edge — which is what lets an FSM consume a value
produced by a pipeline called after it:

```python
def merge(axis_in: chan) -> chan:
    f = fsm(axis_in, p.stream_out)   # consumes a value produced by a later call
    p = pipe(f.to_pipe)
    return f.axis_out
```

That loop is the shape of an FSM+datapath merge (see wireguard's `chacha20_instance`), and it
generates both feedbacks — one carrying the feedforward value backward, one the reverse value.

**Plain values pass through.** Non-interface args and return fields (config, keys, flags) are
ordinary feedforward wires: they appear verbatim with no reverse companion. Statements that
touch no interface value are copied through as-is, so plain computation between calls is fine —
including reading a *non-interface* field off a call result (a status flag, a count). Unlike an
interface, a plain value may fan out freely.

**Multiple ports.** Return an `@interface` bundle whose fields are interfaces to expose more
than one output port; a bare interface return becomes a single port named `out_port`. Bundles
may mix interface fields and plain fields; every field must be assigned in the return.

**Limitations.** An interface function body is straight-line wiring only. `if`/`for`/`while`
and conditional expressions are rejected — steer interfaces with an explicit mux/demux module
instead. Each interface is point-to-point: fan-out of one interface is rejected (use an explicit
duplicator — see array ports below), as is a dangling output or passing an input straight
through to an output. Modules whose reverse signal is *computed* from state (a FIFO's ready
from occupancy, an FSM's from state) are written by hand as ordinary `@hw_func`s — the sugar
wires such modules together, it does not replace them.

### Crossing between the two styles

Designs mix the two: hand-written modules for anything stateful, generated wiring between them.
Both directions of that boundary are ordinary, and neither reinvents a naming convention.

**Manual → implied: a hand-written `@hw_func` (or a `@MAIN`) instantiates an interface function.**
No name matching is involved at all — the generated pair is an ordinary `(hw_func, struct_t)`,
so you call it like any module: reverse halves go in as arguments, and come back out as named
return fields. The shape follows from the interface function's own signature:

| | contents | order |
|---|---|---|
| **args** | plain params verbatim; interface params as their feedforward half; then one feedback-half arg per **output** port | declaration order, then return-bundle order |
| **return fields** | feedforward half per **output** port; then plain return-bundle fields; then feedback half per **input** port | bundle order, then param order |

Every port keeps the name you gave it, and a half is omitted when that direction is empty.
Reverse halves are whole structs — construct them inline, directly in the call arguments, at
the exact point they cross into the real port (never as their own local variable first; see
[Registers: `Reg[T]`](#registers-regt)'s `.fwd_t`/`.fb_t` restriction):

```python
@MAIN(80.0)
def encrypt_dataflow():
    r = encrypt_dataflow_core(
        axis_in_if=axis128_intrf.fwd_t(stream=ports.axis_in),  # forward half, inline
        key=ports.key, nonce=ports.nonce, aad=ports.aad, aad_len=ports.aad_len,
        axis_out_if=axis128_intrf.fb_t(ready=ports.axis_out_ready),  # reverse half, inline
    )
    ports.axis_in_ready = r.axis_in_if.ready      # implied feedback -> explicit
    ports.axis_out = r.axis_out_if.stream         # ports.axis_out is a plain Wire[.stream_t]
```

**Implied → manual: an interface function instantiates a hand-written module.** Here names *do*
matter, in one narrow structural sense: **the two halves of a port share the port's name**, one
on the argument side and one on the return side. The name itself is yours (by convention,
suffixed `_if`); there is no `_ready` or `ready_for_` affix anywhere in the mechanism. Direction
comes from whichever side holds the feedforward half. Declaring only one half is a hard error
*when such a module is instantiated by an interface function*, naming the port and the missing
side — that shape used to mis-wire silently. `@hw_func` also raises `InterfacePortError` at
decoration time whenever a signature declares one half of a port without the other, so the
mistake surfaces even for a module no interface function has composed yet. The one legitimate
lone half is an intentional [valid-only stream](#streams-stream_t) (data + valid,
no backpressure) — build it with `make_stream_t`/`axi.make_axis_t` (genuinely no reverse half,
so the check never applies), not by taking the `.fwd_t` of a with-ready interface and ignoring
its `.fb_t`:

```python
@struct
class gate_t(NamedTuple):
    stream_in_if: chan_intrf.fb_t      # input port's reverse half travels out
    stream_out_if: chan_intrf.fwd_t    # output port's feedforward half travels out
    passed: uint8_t                    # plain status, no reverse companion

@hw_func
def gate(
    stream_in_if: chan_intrf.fwd_t, limit: uint8_t, stream_out_if: chan_intrf.fb_t
) -> gate_t:
    o: gate_t
    count: Reg[uint8_t]
    open_: uint1_t = count < limit          # backpressure computed from state
    o.stream_in_if.ready = stream_out_if.ready & open_
    ...
```

That is the *only* change a stateful module needs to become callable from an interface function —
its body keeps using `.ready` explicitly. `src/tests/pypeline_tests/inst/interface_boundary_test.py`
exercises both crossings against a hand-written twin, plain signals included.

### Where `.fwd_t`/`.fb_t` may appear — and where it may not

> **Not supported:** Nothing except a hw_func signature arg/return-struct field, or an
> inline constructor-call *expression* at the exact point a value crosses into a real
> port, may ever hold an `@interface`'s `.fwd_t`/`.fb_t` type.

That means not a plain local variable (even one built up over several statements, or
assigned via a bare `x = intrf.fwd_t(...)` with no type annotation at all), not
`Feedback[T]`, not `Reg[T]` (see [Registers: `Reg[T]`](#registers-regt)), and not a
global `Wire[T]`/`Input[T]`/`Output[T]`. None of these are themselves a port — a local
is scratch space, `Feedback[T]` is a same-cycle forward reference to a value that meets
a port *elsewhere*, `Reg[T]` is internal state, and a global `Wire`/`Input`/`Output` is
plain wiring between `@MAIN`s or a flattened top-level chip signal — so none of them
ever need (or should imply) the `.fwd_t`/`.fb_t` pairing signal. Use `.stream_t` (or a
bare `uint1_t` for a lone ready/valid signal) everywhere one of these needs to carry the
value, and construct `.fwd_t`/`.fb_t` inline only at the point it meets a real port:

```python
# Wrong -- ElaborationError: a local variable cannot be declared with .fwd_t/.fb_t
dwidth_conv_data_in: axis128_intrf.fwd_t = axis128_null()
...
in_to_block = axis128_to_axis512(narrow_in_if=dwidth_conv_data_in, wide_out_if=...)

# Also wrong -- same error, just without the type annotation
dwidth_conv_data_in = axis128_intrf.fwd_t(stream=axis128_stream_null())

# Also wrong -- Feedback[T] and global Wire[T] are restricted the same way
block_in_ready: Feedback[axis512_intrf.fb_t]
encrypt_pipeline_in: Wire[chacha20_loop_body_stream_intrf.fwd_t]

# Right -- build up the plain .stream_t/uint1_t locally, wrap only at the call site
dwidth_conv_data_in: axis128_intrf.stream_t = axis128_stream_null()
block_in_ready: Feedback[uint1_t]
encrypt_pipeline_in: Wire[chacha20_loop_body_stream_intrf.stream_t]
...
in_to_block = axis128_to_axis512(
    narrow_in_if=axis128_intrf.fwd_t(stream=dwidth_conv_data_in),
    wide_out_if=axis512_intrf.fb_t(ready=block_in_ready),
)
```

**A global stream+ready pair doesn't need to be two separate Wires at all** —
`Wire[SomeInterface]` (the bare `@interface` class, not `.fwd_t`/`.fb_t`/`.stream_t`) is
sugar for one compound Wire holding both halves, with `.stream` and `.ready`
independently driven/read from different functions exactly like any other flattened
multi-writer struct Wire:

```python
# Also fine, and usually clearer than two separate Wires -- one compound Wire
# instead of an independently-named stream Wire + ready Wire for the same port
encrypt_pipeline_in_if: Wire[chacha20_loop_body_stream_intrf]

@hw_func
def drive_in():
    encrypt_pipeline_in_if.stream = ...   # written by one function

@hw_func
def drive_ready():
    encrypt_pipeline_in_if.ready = ...    # written by another

...
x = encrypt_pipeline_in_if.stream.data    # read by a third
```

`Wire[SomeInterface.fwd_t]`/`Wire[SomeInterface.fb_t]` remain banned exactly as above —
only the bare interface class gets this sugar.

An `intrf.fwd_t(...)`/`intrf.fb_t(...)` constructor call is also valid directly as a call
argument (not just as a whole assignment's right-hand side) — no local variable is
needed at all when there's nothing to build up over multiple statements:

```python
r = gated(chan_intrf.fwd_t(data=in_data, valid=in_valid), limit, chan_intrf.fb_t(ready=downstream_ready))
```

**A plain (non-hw_func) Python function may not return a `.fwd_t`/`.fb_t` value either**
— that just hides the same construction behind a call boundary instead of at a real port
crossing, indistinguishable from any of the banned patterns above once the caller uses
the result:

```python
# Wrong -- ElaborationError: a plain function cannot return .fwd_t/.fb_t
def axis128_null():
    return axis128_intrf.fwd_t(stream=axis128_stream_null())

# Right -- return the plain stream_t; wrap inline at each call site that needs it
def axis128_stream_null():
    return axis128_intrf.stream_t(data=axis128_frag_null(), valid=0)
...
o.axis_out_if.stream = axis128_stream_null()  # port field already fwd_t-typed
```

### Array ports: fan-out

An interface is point-to-point, so forking a stream needs a module that owns the fork. Its output
is an **array port**: `axis_out_if: axis_intrf.fwd_t[n]` on the return side paired with `axis_out_if: axis_intrf.fb_t[n]`
on the argument side. Each element is an independent interface with its own backpressure, so
handing `bcast.axis_out_if[i]` to each sink is the whole wiring — the reverse array is assembled and
fed back for you. `make_axis_broadcast_interlock` ([AXI-Stream: `axis_t`](#axi-stream-axis_t)) is the ready-made one:

```python
def fork_wiring(axis_in_if: axis_intrf) -> fork_ports:
    d = bcast(axis_in_if)                    # no sink_ready array to build by hand
    f = hold_fast(d.axis_out_if[0])
    s = hold_slow(d.axis_out_if[1])
    return fork_ports(fast_if=f.axis_out_if, slow_if=s.axis_out_if)
```

Array ports are an output-side feature; an array *input* port is rejected with a clear error.

### Common patterns

Short answers to the interface questions that come up most often — each is a direct
application of the rules above, collected here as a quick reference:

**Store a stream value in a register.** Use `.stream_t`, never `.fwd_t`:
```python
buf: Reg[chan_intrf.stream_t]
```

**Delay a ready (reverse) signal by a cycle.** A bare `uint1_t` register — `.fb_t`'s
unwrapped field type, not `.fb_t` itself:
```python
ready_d1: Reg[uint1_t]
ready_d1 = downstream_if.ready
```

**Route an interface through a local variable.** Build up the plain `.stream_t`/`uint1_t`
locally, and wrap into `.fwd_t`/`.fb_t` only at the call site that needs it:
```python
data_in: chan_intrf.stream_t = chan_stream_null()
...
r = gated(chan_intrf.fwd_t(stream=data_in), limit)
```

**Fan out one interface to several sinks.** Use an array port (see
[Array ports: fan-out](#array-ports-fan-out) above) — never hand the same interface to
two different call sites directly, which would be two independent point-to-point ports
silently sharing one name.

**Convert between a port half and a plain stream.** `.stream_t` is the standalone type;
`.fwd_t.stream` is the same shape nested inside a port half. Moving between them is a
single field access/assignment, never a per-field copy:
```python
o.axis_out_if.stream = my_stream_value      # plain -> port half
my_stream_value = axis_in_if.stream         # port half -> plain
```

**See also:** [Streams: `stream_t`](#streams-stream_t) ·
[AXI-Stream: `axis_t`](#axi-stream-axis_t) ·
[Registers: `Reg[T]`](#registers-regt) ·
[Feedback Wires: `Feedback[T]`](#feedback-wires-feedbackt)

---

## AXI-Stream: `axis_t`

`include/pypeline/axi/axis.py` composes the three layers above into a single factory for
the common case — a complete AXI-Stream-equivalent type:

```python
from pypeline import uint8_t, sim_call
from kept_data_bus import make_kept_data_bus_t
from axi.axis import make_axis_t, make_keep_count, make_count_to_keep

axis32_t = make_axis_t(4)   # 4 lanes of uint8_t: stream(ndarray_fragment(1, kept_data_bus(uint8_t, 4)))

def axis32_passthrough(x: axis32_t) -> axis32_t:
    return x
```

`make_axis_t(n, elem_t=uint8_t, ndims=1)` is exactly:

```python
bus_t = make_kept_data_bus_t(elem_t, n)
fragment_t = make_ndarray_fragment_t(bus_t, ndims)
return make_stream_t(fragment_t)
```

i.e. a genuinely one-directional, plain `{data, valid}` struct — no `@interface`, no reverse half,
ever ([Streams: `stream_t`](#streams-stream_t)). A module that needs backpressure takes both halves of the *with-ready* interface as
ports instead, built from `make_axis_interface(n, elem_t=uint8_t, ndims=1)` — the same three
layers, stopping at the interface:

```python
from axi.axis import make_axis_interface

axis32_intrf = make_axis_interface(4)
axis32_intrf.fwd_t     # {stream: {data, valid}} -- real port, needs .stream.
axis32_intrf.fb_t      # {ready}
axis32_intrf.stream_t  # the plain {data, valid} nested at .fwd_t.stream
```

`axis32_intrf.fwd_t` here is *not* the same type as the standalone `make_axis_t(4)` above: one is a
real with-ready port (`.stream.data`/`.stream.valid`, must pair with `axis32_intrf.fb_t`), the other
is a plain valid-only value (`.data`/`.valid` directly, never paired) — see the naming table in [Bidirectional Ports: `@interface`](#bidirectional-ports-interface).

`make_axis_broadcast_interlock(axis_intrf, n)`, `make_dwidth_widen` and `make_dwidth_narrow` all
declare their ports this way — see [Crossing between the two
styles](#crossing-between-the-two-styles).

so for an `axis32_t` value `x`:

| Old AXIS field | pypeline equivalent |
|---|---|
| `tdata[i]` | `x.data.frag.data[i]` |
| `tkeep[i]` | `x.data.frag.keep[i]` |
| `tlast` | `x.data.eod[0]` |
| `valid` | `x.valid` |

`elem_t` only needs to be `uint8_t` (the default) for this to be literally AXI-Stream —
with any other `elem_t`, `make_axis_t` produces the same `tdata`/`tkeep`-shaped struct
generalized to a stream of per-lane elements instead of bytes. `ndims` only needs to be `1`
(the default, a single `tlast`-equivalent flag) — pass a larger value for streams with
nested end-of-dimension boundaries, the same way
[`ndarray_fragment_t`](#n-dimensional-stream-fragments-ndarray_fragment_t) does on its
own.

Two small helpers cover the `tkeep`↔lane-count conversions that AXIS-handling logic
typically needs:

```python
bus4_t = make_kept_data_bus_t(uint8_t, 4)
keep_count_4 = make_keep_count(bus4_t, 4)        # .keep[4] -> count of asserted lanes
count_to_keep_4 = make_count_to_keep(4)          # count -> thermometer-coded .keep[4]

assert sim_call(count_to_keep_4, 3) == [1, 1, 1, 0]
assert sim_call(keep_count_4, bus4_t(data=[0, 0, 0, 0], keep=[1, 1, 1, 0])) == 3
```

`make_keep_count(bus_t, n)` returns a hardware function summing `.keep` over `n` lanes
(a popcount). `make_count_to_keep(n)` returns the inverse: given a lane count, produces a
thermometer-coded `.keep[n]` array with lanes `[0, count)` asserted. Both fully unroll
their internal `for i in range(n)` loop at elaboration time (see
[for/while → loop unrolling](#your-first-hardware-function)), so there's no need for
the per-width duplication older, non-generic AXIS implementations require.

See `src/tests/pypeline_tests/inst/axis_test.py` for a complete worked example, including
synthesis through `pypelinec`.

### Testbench byte-stream generator/checker

Every hand-written axis testbench ends up rebuilding the same shape: a fixed-width byte
buffer + "bytes remaining" counter, `keep[i] = remaining > i` per lane, `eod` set on the
last beat, and — once a transfer actually fires (`stream.valid & <reverse ready>`) —
shifting the buffer down by the lane width (generating) or appending the kept lanes into
an accumulating buffer (checking). `make_axis_byte_source`/`make_axis_byte_sink` factor
that out into reusable, synthesizable `@hw_func`s:

```python
from axi.axis import make_axis_interface, make_axis_byte_source, make_axis_byte_sink

axis128_intrf = make_axis_interface(16)
byte_source, byte_source_t = make_axis_byte_source(axis128_intrf, 16, MAX_FRAME_BYTES)
byte_sink, byte_sink_t = make_axis_byte_sink(axis128_intrf, 16, MAX_FRAME_BYTES)

# byte_source(load, load_data, load_len, stream_out_if) -> byte_source_t
#   .stream_out_if (fwd_t) - the generated stream; .idle - safe to `load` a new frame
# byte_sink(stream_in_if) -> byte_sink_t
#   .stream_in_if (fb_t) - reverse half; .frame_valid/.frame_data/.frame_len - one
#   pulse per completed frame, ready for a single sim_assert/compare
```

Neither factory generates or checks backpressure — both drive their own
`ready`/consume-every-beat behavior unconditionally, the same as every hand-written
testbench in this codebase. A caller wanting stalls drives the interface's reverse half
itself.

`make_axis_byte_source(..., use_keep_mask=True)` adds a `load_keep_mask` input
overriding the default `keep[i] = remaining > i` derivation with an explicit per-byte
mask — needed whenever a frame is really *multiple concatenated sub-messages* with a
hard beat boundary between them (e.g. a protocol where a fixed-size trailer must always
start on a fresh beat, so a non-block-aligned leading segment needs its last beat padded
with not-kept bytes rather than letting the trailer merge into the leftover lanes).
`AxisSimSource.send(frame, keep_mask=...)` is the same idea for native sim.

For native (non-synthesizable) `--sim` testbenches driven via `@sim_input`/`@sim_output`,
`include/pypeline/axi/axis_sim.py`'s `AxisSimSource`/`AxisSimSink` cover the same ground in
plain Python — API-inspired by cocotb's `cocotbext-axi` (queue-backed `send()`/`recv()`, a
`set_pause_generator()` backpressure hook) but not that library itself: Pypeline's native
sim is a synchronous, non-async, delta-cycle-converging function-call model, incompatible
with cocotbext-axi's `async def`/cocotb-scheduler-based classes.

```python
from axi.axis_sim import AxisSimSource, AxisSimSink

src = AxisSimSource(axis128_intrf, 16)
snk = AxisSimSink(axis128_intrf, 16)
src.send(b"...")                       # queue a frame

@sim_input
def drive_in_word():
    return src.step(some_ports.axis_in_ready)

@sim_output
def check_out():
    snk.step(some_ports.axis_out)
    frame = snk.recv_nowait()          # None until a full frame has arrived
    if frame is not None:
        ...
```

`axis_sim.py` also has `Scoreboard` — not AXIS-specific, just factored out because every
testbench in this codebase reinvented the same "dict of expected packets + a manually-
incremented index" bookkeeping around its own checker. `expect(value, **meta)` queues an
expected value plus arbitrary caller metadata (packet index, a tamper flag, whatever);
`check(got)` pops the oldest expectation and compares, returning
`{"passed": bool, "expected": ..., "got": ..., **meta}`. `AxisSimSink` takes one directly
(`AxisSimSink(axis_intrf, n, scoreboard=sb)`), so `check_nowait()` combines "pop a
completed frame" and "check it" in one call:

```python
from axi.axis_sim import AxisSimSource, AxisSimSink, Scoreboard

sb = Scoreboard()
src = AxisSimSource(axis128_intrf, 16)
snk = AxisSimSink(axis128_intrf, 16, scoreboard=sb)

@sim_input
def drive_in_word():
    if src.idle():
        frame, meta = generate_next_frame()   # whatever's genuinely testbench-specific
        sb.expect(frame, **meta)
        src.send(frame)
    return src.step(some_ports.axis_in_ready)

@sim_output
def check_out():
    snk.step(some_ports.axis_out)
    result = snk.check_nowait()            # None until a full frame has arrived
    if result is not None and not result["passed"]:
        sim_print(f"ERROR: mismatch, packet {result['idx']}")
```

See `src/tests/pypeline_tests/inst/axis_byte_stream_test.py` for a complete worked
example of both, including a partial-final-beat (non-multiple-of-lane-width) frame length
and `set_pause_generator`.

**See also:** [Bidirectional Ports: `@interface`](#bidirectional-ports-interface) ·
[Keep-Tagged Lanes: `kept_data_bus_t`](#keep-tagged-lanes-kept_data_bus_t) ·
[FIFOs: `make_stream_fifo`](#fifos-make_stream_fifo)

---

## FIFOs: `make_stream_fifo`

`include/pypeline/stream/stream_fifo.py`'s `make_stream_fifo` wraps a single-clock-domain FIFO
in pypeline's standard valid/ready
[stream interface](#the-stream-interface-validready-handshaking), so you
don't have to unpack/repack `.data`/`.valid` by hand. (It's a thin layer over
`include/pypeline/fifo.py`'s lower-level `make_fifo` — most users should just use
`make_stream_fifo` directly and never need to touch `make_fifo` itself.)

```python
from pypeline import uint32_t, MAIN
from stream.stream_fifo import make_stream_fifo

stream_fifo, stream_fifo_t = make_stream_fifo(uint32_t, 256)   # 256-deep FIFO of uint32_t
uint32_stream_t = stream_fifo.stream_t
uint32_stream_fb_t = stream_fifo.stream_fb_t

@MAIN
def buffered(in_stream: uint32_stream_t, out_stream: uint32_stream_fb_t) -> stream_fifo_t:
    return stream_fifo(in_stream, out_stream)
```

`make_stream_fifo(data_t, depth, mode="fwft")` returns `(stream_fifo_func, stream_fifo_t)`. It
has one input port `in_stream` and one output port `out_stream`, each declared as the two
halves of the same [interface](#bidirectional-ports-interface):

| | Type | Meaning |
|---|---|---|
| `stream_fifo_func(in_stream, out_stream)` | `(stream_t, stream_fb_t) -> stream_fifo_t` | one FIFO instance |
| `stream_fifo_t.out_stream` | `stream_t` | the FIFO's output: `.data`/`.valid` |
| `stream_fifo_t.in_stream` | `stream_fb_t` | backpressure for `in_stream` — `.ready` high while the FIFO has room |

The interface and both halves hang off the returned function as `.stream_intrf` / `.stream_t` /
`.stream_fb_t`, so callers don't rebuild them. Because the ports are interfaces, an
[interface function](#interface-functions-write-feedforward-get-the-reverse-wired) can drop a
FIFO into a chain with `f = stream_fifo(upstream.out_stream)` and no ready wiring at all.

`make_fifo` itself is deliberately **not** migrated: its `data_in`/`data_in_valid`/
`data_in_ready` signals are literally the wrapped VHDL entity's ports, and `make_stream_fifo`
is its interface face.

`depth` must be `>= 2`. `mode` only accepts `"fwft"` (first-word-fall-through) for now — the
only underlying FIFO implementation currently available.

**Simulates via a functional model.** Even though the FIFO is a raw VHDL entity under the
hood, `make_fifo` attaches a `collections.deque`-based FWFT [`@sim_model`](#sim_model--python-simulation-models-for-hardware-functions)
to it, so `stream_fifo_func` works under `sim_call()`/`pypeline_sim.py` too — same data,
same valid/ready handshake, and the same rounded-up-to-a-power-of-two capacity as real
hardware, just not cycle-accurate internally. See `pypeline_sim_DESIGN.md`'s
"`make_fifo` Simulation Model" section for the exact contract, and
`src/tests/pypeline_tests/inst/stream_fifo_test.py`.

**See also:** [Streams: `stream_t`](#streams-stream_t) ·
[Pipelined Stream Wrappers: `make_stream_pipeline`](#pipelined-stream-wrappers-make_stream_pipeline) ·
[Multi-Cycle Stream Wrapper: `make_valid_ready_mcp`](#multi-cycle-stream-wrapper-make_valid_ready_mcp)

---

## Pipelined Stream Wrappers: `make_stream_pipeline`

```text
in_if -->|Reg|--> [ AUTOPIPELINE'd func ] -->|Reg|--> [ output FIFO ] --> out_if
        (input reg)   (free-running,             (output reg)   (sized from
                        N-stage pipeline)                        .latency)
```

`include/pypeline/stream/stream_pipeline.py`'s `make_stream_pipeline` wraps a single
combinational hardware function in a free-running, fully-pipelined
[stream interface](#the-stream-interface-validready-handshaking): an
[AUTOPIPELINE'd](#tool-chosen-implementation-autopipeline-and-autofsm) instance (with registered
input/output) feeding a [`make_fifo`](#fifos-make_stream_fifo)-backed output FIFO.
The FIFO and in-flight counter are **sized automatically** from the AUTOPIPELINE
instance's `.latency` — the tool-discovered pipeline depth — so there is no
`MAX_IN_FLIGHT` parameter to guess and hand-tune against synthesis results. It's the
pypeline equivalent of PipelineC's `GLOBAL_VALID_READY_PIPELINE_INST` macro — minus the
global wires, since this is one locally-instantiated function rather than two `MAIN`s
joined by `Wire[T]`s.

```python
from pypeline import hw_func, uint8_t, MAIN, uint1_t
from stream.stream import make_stream_t
from stream.stream_pipeline import make_stream_pipeline

@hw_func
def div_inv(x: uint8_t) -> uint8_t:
    return x / ~x

uint8_stream_t = make_stream_t(uint8_t)
stream_pipeline, stream_pipeline_t = make_stream_pipeline(div_inv)

@MAIN(50.0)
def buffered_div_inv(
    stream_in: stream_pipeline.in_stream_t, stream_out: stream_pipeline.out_fb_t
) -> stream_pipeline_t:
    return stream_pipeline(stream_in, stream_out)
```

`make_stream_pipeline(func)` returns `(stream_pipeline_func, stream_pipeline_t)`:

| | Type | Meaning |
|---|---|---|
| `stream_pipeline_func(stream_in, stream_out)` | `(in_stream_t, out_fb_t) -> stream_pipeline_t` | one pipelined instance of `func`; ports are the two halves of a stream `@interface` |
| `stream_pipeline_t.stream_out` | `stream_t(out_type)` | `func`'s result, after AUTOPIPELINE retiming and the output FIFO |
| `stream_pipeline_t.stream_in.ready` | `uint1_t` | high while the pipeline can accept a new `stream_in` (tracks in-flight count against the FIFO depth) |

The FIFO depth is `max(2, 1 + AUTOPIPELINE latency + 1)` — input reg + discovered core
stages + output reg, i.e. every word that can be in flight at once, so downstream
stalls can never overflow the FIFO and full 1-word/cycle throughput is sustained. On
the bootstrap pass (and in plain native sim / `--comb` builds, where `.latency` stays
0) the depth floors at 2 — which in those contexts is exact, since the effective
pipeline latency really is just the two boundary registers; on a real build the
pin-and-confirm loop re-elaborates with the discovered latency (see
[Tool-Chosen Implementation: `AUTOPIPELINE(...)` and `AUTOFSM(...)`](#tool-chosen-implementation-autopipeline-and-autofsm)), and a non-`--comb` `pypelinec --sim` run's
native simulation imports the design with the same latency installed — so the FIFO is
sized identically and the AUTOPIPELINE call site is emulated at the same depth.

`in_type`/`out_type` are inferred from `func`'s own annotations via `hw_arg_types`/
`hw_return_type`, the same way
[`make_valid_ready_mcp`](#multi-cycle-stream-wrapper-make_valid_ready_mcp) does (see
[Parametric Hardware with Factory Functions](#parametric-hardware-with-factory-functions)). **`func` must already be
`@hw_func`-decorated** — `make_stream_pipeline` calls `is_hw_func(func)` and raises
`TypeError` immediately if it isn't, since `func` is called from inside an internal
AUTOPIPELINE'd wrapper and needs its own decoration for any `Reg[T]`/bare struct-array
locals in its body to simulate correctly (see [Tool-Chosen Implementation: `AUTOPIPELINE(...)` and `AUTOFSM(...)`](#tool-chosen-implementation-autopipeline-and-autofsm)).

**Simulates end-to-end.** Since `make_fifo`'s internal FIFO now carries a
[`@sim_model`](#sim_model--python-simulation-models-for-hardware-functions), the whole
pipeline — AUTOPIPELINE retiming plus the output FIFO — simulates via `sim_call()` or
`pypeline_sim.py`, including realistic backpressure when the consumer stalls. See
`src/tests/pypeline_tests/inst/stream_pipeline_test.py`.

**See also:** [Tool-Chosen Implementation: `AUTOPIPELINE(...)` and `AUTOFSM(...)`](#tool-chosen-implementation-autopipeline-and-autofsm) ·
[FIFOs: `make_stream_fifo`](#fifos-make_stream_fifo) ·
[Multi-Cycle Stream Wrapper: `make_valid_ready_mcp`](#multi-cycle-stream-wrapper-make_valid_ready_mcp)

---

## Multi-Cycle Stream Wrapper: `make_valid_ready_mcp`

[`make_stream_pipeline`](#pipelined-stream-wrappers-make_stream_pipeline) above trades
area for throughput: a free-running pipeline that accepts a new word every cycle.
`make_valid_ready_mcp`, from `include/pypeline/multi_cycle_path.py`, is the other
function-to-stream wrapper. It takes a single slow combinational function and gives it a
[`MULTI_CYCLE[...]`](#multi-cycle-paths-multi_cycle) launch/capture FSM, presenting the
result as a valid/ready [stream interface](#the-stream-interface-validready-handshaking) — one
result every `ncycles + 1` cycles rather than one per cycle. It is the pypeline equivalent of
PipelineC's `DECL_VALID_READY_MCP_FUNC` macro:

```python
from pypeline import hw_func, MAIN
from multi_cycle_path import make_valid_ready_mcp

@hw_func
def divider(i: my_struct_t) -> uint32_t:
    return i.x / i.y

divider_mcp, divider_mcp_t = make_valid_ready_mcp(divider, 16)   # 16-cycle MCP

@MAIN(100.0)
def top(stream_in: divider_mcp.in_stream_t, stream_out: divider_mcp.out_fb_t) -> divider_mcp_t:
    return divider_mcp(stream_in, stream_out)
```

`make_valid_ready_mcp(func, ncycles)` infers `in_type`/`out_type` from `func`'s own
parameter/return type annotations (unlike the C macro, which takes them as separate
arguments) and returns `(func_mcp, func_mcp_t)`. Its ports are the two halves of a stream
`@interface`, exactly like `make_stream_pipeline`'s:

| | Type | Meaning |
|---|---|---|
| `func_mcp(stream_in, stream_out)` | `(in_stream_t, out_fb_t) -> func_mcp_t` | one MCP-wrapped instance of `func` |
| `func_mcp_t.stream_out` | `stream_t(out_type)` | `func`'s result, valid `ncycles + 1` cycles after launch |
| `func_mcp_t.stream_in.ready` | `uint1_t` | high while the FSM is idle and ready to accept a new `stream_in` |

Internally it is the same `MULTI_CYCLE[ncycles]` / `Reg[T, MC.start]` / `Reg[T, MC.end]`
pattern from [Multi-Cycle Paths: `MULTI_CYCLE[...]`](#multi-cycle-paths-multi_cycle), with `launch`/`capture` registers and a
`cycles_since_launch` counter driving the handshake. Like `MULTI_CYCLE[...]` itself, the
relaxed timing only matters during real FPGA synthesis (requires `PART()` + Vivado);
simulation always sees `func`'s result settle the same cycle it is computed. See
`src/tests/pypeline_tests/inst/valid_ready_mcp_test.py` (translated from
`examples/mcp/mcp_divider.c`) for the full example.

---

### Part IV — Escape hatches

When Pypeline's normal abstraction isn't enough, these two hatches let you drop to a
lower level without leaving the language: `vhdl()` for literal VHDL text, and `@wires`
for telling the synthesiser a function is pure bit-rewiring with no real logic delay.
(`kept_data_bus_t`/`ndarray_fragment_t` from Part III are not escape hatches — they're
ordinary structured types.)

## Raw VHDL Passthrough: `vhdl()`

Sometimes you need an escape hatch — a primitive your target FPGA vendor provides, a
trick that's awkward to express in pypeline, or an existing VHDL block you want to drop
in unchanged. `vhdl(text)` replaces a function's entire body with literal VHDL text,
spliced directly into the generated entity's architecture. It's the pypeline equivalent
of C's `__vhdl__("...")`.

```python
from pypeline import vhdl, uint64_t

@MAIN
def main(x: uint64_t, y: uint64_t) -> uint64_t:
    vhdl(f"""
        begin
        return_output <= x + y;
    """)
```

> **Required:** `vhdl(...)` must be the **only statement** in the function body (an
> optional leading docstring is fine). The function's signature is still used to
> generate the entity's ports exactly as normal — `x` and `y` become `in` ports, the
> return value becomes the `return_output` `out` port — but nothing inside the body is
> elaborated; the text is inserted as-is into the architecture, which already supplies
> `architecture arch of <name> is ... end arch;` around it. Your text should *not*
> include its own `end;` — only the declarative part (optional), `begin`, and the
> statements.

Inside the text, reference ports by their literal VHDL signal names: the function's
parameter names, `return_output` for the return value, and `CLOCK_ENABLE`/`clk` if your
logic needs them. (Parameter names with leading/trailing/double underscores, or that
collide with a VHDL reserved word, get sanitised into a different port name — keep
parameter names simple to avoid surprises.)

The argument to `vhdl(...)` can be **any compile-time-computed Python string** — an
f-string, concatenation, or a call to a plain Python helper function — as long as it only
references plain Python/elaboration-time values. It cannot reference hardware wire
values (there's no way to "interpolate" a signal's runtime value into VHDL text; if you
need to refer to a port, write its VHDL name literally in the string, as in the example
above).

```python
def make_adder_vhdl(width):
    return f"""
        begin
        return_output <= std_logic_vector(unsigned(x) + unsigned(y))({width-1} downto 0);
    """

@MAIN
def sized_add(x: uint32_t, y: uint32_t) -> uint32_t:
    vhdl(make_adder_vhdl(32))
```

**No timing information.** The compiler has no idea what's inside a `vhdl(...)` block,
so it's always treated as an opaque, zero-cycle-delay black box — same as C's
`__vhdl__`. If your raw VHDL needs registers, manage them yourself within the text.

**Simulating raw VHDL requires a model.** There is no general way to simulate arbitrary
user-supplied VHDL text in Python, so calling a `vhdl(...)`-bodied function in simulation
— directly, via `sim_call()`, or via `pypeline_sim.py` — raises `NotImplementedError`
unless you attach a Python simulation model to it with `@sim_model(target)` (see
[`@sim_model`](#sim_model--python-simulation-models-for-hardware-functions)): either a
synthesizable `@hw_func` written in pypeline, or an arbitrary Python class with
`__init__`-held state and a `__call__` matching the function's signature.

---

## Just-Wires Synthesis Hint: `@wires`

Some functions don't synthesise to any real logic — they just rearrange bits: packing a
struct into a byte array, splitting an integer into its individual bits and wiring them
out to separate ports, casting one same-width type to another. There's no gate delay to
estimate for logic like that, but by default the synthesiser doesn't know that, and will
spend time measuring or estimating a path delay through it anyway. `@wires` tells it not
to bother — equivalent to PipelineC's `#pragma FUNC_WIRES <func_name>`.

```python
from pypeline import wires, struct, uint8_t
from typing import NamedTuple

@struct
class pair_t(NamedTuple):
    a: uint8_t
    b: uint8_t

@wires
def pair_to_bytes(p: pair_t) -> uint8_t[2]:
    return [p.a, p.b]
```

**`@wires` implies `@hw_func`** — you don't need to add `@hw_func` separately. That means
a `@wires` function can be called directly with `sim_call()` (or from inside another
`@hw_func`/`@MAIN` body) just like any other hardware helper:

```python
assert sim_call(pair_to_bytes, pair_t(a=1, b=2)) == [1, 2]
```

It also stacks with `@MAIN` in either order, for the case where an entire top-level entry
point is just wires — mirroring `include/leds/leds_port.c`, which independently tags its
`leds_module` function with both `#pragma MAIN` and `#pragma FUNC_WIRES`:

```python
@MAIN
@wires
def leds_module(): ...
```

**This is purely a synthesis-time hint** — it has no effect on simulation behaviour (the
function still runs as ordinary Python/hardware logic), and the compiler does not check
that the function is actually wires-only. Tagging logic that has real delay (arithmetic,
comparisons, anything beyond rewiring/casting) with `@wires` will make the synthesiser
underestimate timing through it — use it only for genuinely free rewiring.

See `src/tests/pypeline_tests/inst/func_wires_test.py` for the full example.

See `src/tests/pypeline_tests/inst/vhdl_text_test.py` for a complete example.

---

### Part V — Reference

## Simulation Reference

The rest of the simulation feature set, beyond the [Simulation](#simulation) basics in
Part I: side-effect hooks, console output and simulation control, the native-vs-VHDL
cycle-diff debug tool, and Python simulation models for hand-written VHDL.

### `@sim_output` — side effects once per cycle

Functions decorated with `@sim_output` are called normally in simulation's final pass
but are skipped during intermediate convergence iterations.
Use this for `print`, plotting, file writes, etc.

```python
from pypeline import sim_output

@sim_output
def display_result(data):
    print(f"output: {data}")
```

`@sim_output` calls inside `@MAIN` bodies are **invisible to the hardware compiler** —
they produce no gates or wires in the synthesised design. This holds no matter where in
the design the call happens — a top-level `@MAIN` body or a nested non-MAIN helper.

A `@sim_output` function's body can also read a `Wire[T]`/`Input[T]`/`Output[T]` directly
by bare name, instead of only receiving values as passed-in arguments:

```python
out0: Wire[uint32_t]

@sim_output
def check_out():
    print(int(out0))   # direct read, not passed in as an argument
```

### `@sim_input` — driving simulation inputs

`@sim_input` is the reverse of `@sim_output`: it runs once near the *start* of each
simulated clock cycle (before everything else needs a stable value) instead of the end,
and is used to drive `Input[T]` wires rather than observe outputs. Two forms:

```python
from pypeline import sim_input

in0: Input[uint32_t]

@sim_input
def in_global():
    in0 = python_stuff()          # direct-write form: body drives the wire itself

@sim_input
def in_return() -> uint32_t:
    return python_stuff()          # return-value form: caller assigns the return value

in1: Input[uint32_t]

@MAIN
def tb_inputs():
    in_global()
    in1 = in_return()
```

Like `@sim_output`, `@sim_input` calls are invisible to the hardware compiler no matter
where they appear. The real body runs at most once per simulated cycle — a per-cycle
result cache, not a fixed call location, is what guarantees this — so a non-idempotent
driving value (a counter, a random sample, a queue pop) advances exactly once per cycle
even though a `@MAIN` body actually runs at least twice per cycle internally.

### `sim_print` — printf-style console output

`sim_print(...)` looks like `@sim_output` (fires once per cycle, in the final pass) but is
**not** invisible to the hardware compiler — it also elaborates to a real VHDL console
`write(output, ...)` statement, PipelineC's equivalent of C's `printf(...)`.

```python
from pypeline import sim_print

n: Reg[uint8_t]
sim_print(f"n={n} hex={hex(n)}")
```

Write it like ordinary Python `print()`-style code: an f-string (or a plain string with no
interpolation), one argument, no separate `%`-style format-string-plus-args form. A trailing
newline is appended automatically, like real `print()`. Bare `{expr}` interpolation works for
plain integers (decimal, sign-aware) and for `char_t[N]` arrays (`%s`); `hex(expr)` gives hex.
A single `char_t` still needs `chr(expr)` — a bare `{ch}` is ambiguous between a number and a
character, so it's a compile error instead of a silent mismatch:

```python
from pypeline import char_t, strlen

def print_name(name: char_t[16]):
    sim_print(f"name={name} len={strlen(name)}")
```

See `docs/pypeline_sim_DESIGN.md` and `docs/PY_TO_LOGIC_DESIGN.md` for the simulation and
elaboration mechanics.

### `sim_assert` / `sim_finish` — simulation control

Two more `sim_print`-style builtins for controlling simulation itself, elaborating to real
hardware just like `sim_print` does:

```python
from pypeline import sim_assert, sim_finish

n: Reg[uint8_t]
sim_assert(n < 100, f"n grew too large: {n}")   # msg is optional
sim_assert(n != 0)                               # bare condition -> default message

if n >= 3:
    sim_finish()
```

`sim_assert(cond, msg=None)` checks `cond` every cycle it executes while enabled — a failing
condition raises `AssertionError` in native Python simulation and elaborates to a VHDL `assert
... report ... severity failure;` that halts a real GHDL simulation immediately. `msg` follows
the same f-string interpolation rules as `sim_print`'s argument.

`sim_finish()` takes no arguments and signals "stop simulating now": it raises a `SimFinish`
exception in native simulation (caught by `pypeline_sim.py`'s `--run` CLI loop to end the run
cleanly) and elaborates to VHDL's `std.env.finish;`, halting a real GHDL simulation.

See `docs/pypeline_sim_DESIGN.md` and `docs/PY_TO_LOGIC_DESIGN.md` for the simulation and
elaboration mechanics.

### `sim_print(..., debug=True)` — tagged prints for `pypeline_sim_debug.py`

`sim_print(s, debug=True)` behaves identically to plain `sim_print(s)`, except the printed
message is prefixed with a `[SIM DEBUG PRINT: <abs path>:<N>]` tag identifying the call site.
`debug` must be a compile-time-constant `True`/`False` literal. The tag uses an absolute path
(not just a filename), formatted as `path:line` — most terminals and editors recognize that
shape and let you click straight to the call site:

```python
from pypeline import sim_print, hex

n: Reg[uint8_t]
sim_print(f"n={n} hex={hex(n)}", debug=True)
# prints: [SIM DEBUG PRINT: /home/me/proj/my_design.py:42]: n=3 hex=03
```

Use `debug=True` for prints you want compared cycle-by-cycle between a native Python sim and a
VHDL (cocotb+GHDL) sim by the `pypeline_sim_debug.py` tool — see below. Plain `sim_print(...)`
(`debug=False`, the default) output is deliberately ignored by that tool: not every console line
is useful for cycle-accuracy debugging, and tagging only the ones that are keeps the diff signal
clean. In a `--comb` compare (zero pipeline latency) any `debug=True` print is fair game; in a
**pipelined** (non-`--comb`) compare there are extra rules on *where* such prints may live — see
the three constraints in the `pypeline_sim_debug.py` section below. `hex(...)`/`chr(...)`/plain `{expr}` interpolation rules are unaffected by `debug`; using
`from pypeline import hex` (not Python's builtin) matters here more than usual, since only
Pypeline's `hex()` is guaranteed to render identically in both native and VHDL sim (see its
docstring in `pypeline.py`).

#### `pypeline_sim_debug.py` — native-vs-VHDL cycle diff tool

`src/pypeline_sim_debug.py` runs a testbench both ways — native sim, and `--cocotb --ghdl` VHDL
sim — and diffs their `sim_print(..., debug=True)` output cycle by cycle. It exists to localize
*cycle-timing* mismatches (data correct, but arriving on the wrong clock cycle) that ordinary
`sim_assert`s don't catch.

Invocation, the `--comb`/pipelined-compare distinction, the three constraints on a pipelined
compare, and the `--context`/log-file behavior have moved to
[`docs/README.md`'s Tools & CLI section](README.md#pypeline_sim_debugpy--native-vs-vhdl-cycle-diff-tool)
— see there for the full how-to-invoke reference. The deeper "why" (warm `out_dir` build
orchestration, convergence guarantees) is in `docs/pypeline_sim_DESIGN.md`'s "Pipelined native
sim" section.

To narrow down *where* in a design a cycle-timing bug originates, add `debug=True` at successive
points along the suspect data path and re-run — the tool reports the first point at which native
and VHDL disagree.

Any hardware function that pairs a hand-written [`@sim_model`](#sim_model--python-simulation-models-for-hardware-functions)
with raw `vhdl(...)` text (rather than letting the elaborator derive both from one
description) is exactly where native sim and real VHDL can silently diverge in cycle
timing — the two implementations are maintained independently, and nothing checks they
agree. `debug=True` + `pypeline_sim_debug.py` is the tool for finding and localizing that
class of bug: add debug prints at successive points along a suspect data path (bisecting
the hierarchy, narrowest first at the two ends of a call, then walking inward) and re-run;
the first cycle where native and VHDL disagree pinpoints the boundary responsible.

### `@sim_model` — Python simulation models for hardware functions

`sim_model(target)` attaches a Python model to any `@hw_func`/`@MAIN` function: whenever
`target` is called in simulation, the model runs instead of the function's own body.
Hardware elaboration is completely unaffected — models are invisible to the compiler.
This is how raw-VHDL functions become simulable (see
[Raw VHDL Passthrough: `vhdl()`](#raw-vhdl-passthrough-vhdl)), and it can equally swap a slow bit-accurate
function for a fast high-level model.

The model can take **either** of two forms — attach exactly one per target (a second
`@sim_model(target)` raises `ValueError`):

**Form 1 — a synthesizable `@hw_func` delegate** with the same signature:

```python
from pypeline import hw_func, sim_model, vhdl, Reg, uint32_t

@hw_func
def accum(din: uint32_t) -> uint32_t:   # the hardware: raw VHDL
    vhdl(ACCUM_VHDL_TEXT)

@sim_model(accum)
@hw_func
def accum_model(din: uint32_t) -> uint32_t:
    total: Reg[uint32_t]
    total = total + din
    return total
```

**Form 2 — an arbitrary Python class** (sim-only, never synthesizable): `__init__` holds
any state you like — numpy arrays, deques, open files — and `__call__` takes the target's
arguments and returns its output:

```python
import numpy as np

@sim_model(accum)
class AccumModel:
    def __init__(self):
        self.samples = np.array([], dtype=np.uint64)
    def __call__(self, din):
        self.samples = np.append(self.samples, int(din))
        return int(self.samples.sum())
```

One class instance is created lazily **per hardware instance** — per call site, the same
keying as `Reg[T]` state — so two call sites of `accum` accumulate independently.
`sim_reset()` discards the instances (fresh power-on state), and model outputs are cast
to the target's declared return type at the boundary like any other hw_func result.

State timing is Reg-like: each evaluation runs on a `copy.deepcopy` of the instance
committed at the last clock edge, and the mutated copy commits at the edge. Outputs are
therefore a pure function of (cycle-start state, current inputs), so under
`pypeline_sim.py` a model can be safely re-evaluated during wire convergence — even with
a combinational input→output path through it — and its state still advances exactly once
per cycle. Because `__call__` may run several times per cycle during convergence, keep
model bodies side-effect-free (or gate side effects the way `@sim_output` does). For
heavy state you can opt out of the deepcopy with `@sim_model(accum, copy_state=False)`:
the instance is then created once and mutated in place — faster, but only sound when
inputs are already final the first time the model runs each cycle (e.g. plain
single-call `sim_call()` use).

---

The DSP library reference and the categorized list of known limitations close out the
guide.

## DSP: Filters & Signal Conditioning

The DSP filter library (`make_fir`, `make_fir_decim`/`make_fir_interp`, `make_magnitude`,
`make_dc_block`, `make_moving_avg`, and their testbench helpers) has moved to
[`include/pypeline/dsp/pypeline_dsp_guide.md`](../include/pypeline/dsp/pypeline_dsp_guide.md),
next to the library source it documents. See that file for the full reference.

---

## Limitations / Not Yet Supported

The table below consolidates all known limitations and unsupported features, grouped by
category so unrelated kinds of restriction don't read as equivalent — a language
restriction you must design around is a different kind of fact than "this hasn't been
built yet."

| Category | Feature | Status | Notes |
|---|---|---|---|
| Language | **Multiple/early `return` statements** | Not supported | A function may have at most one `return`, and it must be the function's final top-level statement; assign to a variable inside `if`/`else` branches and return it once at the end (see [Control flow](#your-first-hardware-function)) |
| Language | **Explicit casts (`uint32_t(x)`, etc.)** | Not supported | Calling a type as a function around a wire/parameter inside a hardware function body fails at elaboration time; assign to an intermediate variable with an explicit type annotation instead (see [Basic Types](#basic-types)) |
| Language | **Hardware signals as loop conditions** | Not supported | `for`/`while` loop bounds must be compile-time Python integers (fully unrollable) |
| Language | **`from module import *`** | Not supported | Only qualified imports (`import module`) are supported |
| Language | **Initializers on `Wire[T]` / `Input[T]` / `Output[T]`** | Not allowed | Assign inside `@MAIN` instead |
| Language | **Control flow inside an interface function** | Rejected | `if`/`for`/`while` and conditional expressions in an interface-function body raise an `InterfaceError`; route conditional steering through an explicit handshake mux/demux module instead (see [`@interface`](#bidirectional-ports-interface)). Interfaces are also point-to-point: fan-out of a single interface, dangling outputs and input-to-output bypass are rejected — fan out through a module with an [array port](#array-ports-fan-out) instead. Array *input* ports are not supported. Compile-time `for`/`while` unrolling in ordinary `@hw_func`s is unaffected |
| Synthesis | **Named/generated clocks (single domain)** | Supported | `make_clock(mhz)` on a global `Input[uint1_t]`/`Wire[uint1_t]` — pypeline equivalent of `CLK_MHZ`, see [Top-Level Entry Points](#top-level-entry-points) |
| Synthesis | **Multiple clock domains** | Not supported | `MAIN_MHZ_GROUP` (clock groups) and `#pragma ASYNC_WIRE` have no pypeline equivalent; `make_clock`'s rate must match some single `@MAIN`'s rate exactly |
| Synthesis | **Async clock-crossing FIFOs** | Not supported | `GLOBAL_STREAM_FIFO` across clock boundaries cannot yet be expressed |
| Synthesis | **Dual-port stream RAM** | Not built-in | `DECL_STREAM_RAM_DP_W_R_1` — use `vhdl()` passthrough |
| Synthesis | **`MULTI_CYCLE[...]`** | Synthesis only | No effect without `PART()` / Vivado; ignored in simulation |
| Synthesis | **`AUTOPIPELINE(...).latency` before synthesis** | Reads `0` | Real value only exists after a synthesizing build's pin-and-confirm pass; plain native sim and `--comb`/`--no_synth`/`--yosys_json` builds always read 0 (a non-`--comb` `pypelinec --sim` run's native sim reads the built value) |
| Simulation | **Simulation of `vhdl()`** | Not supported | `vhdl()`-based functions raise `NotImplementedError` in simulation unless a [`@sim_model`](#sim_model--python-simulation-models-for-hardware-functions) is attached (as `make_fifo` now does, covering `make_stream_fifo`/`make_stream_pipeline` too); this still includes `make_valid_ready_mcp` |
| Library | **Enum types in `byte_length`/`make_type_to_bytes`/`make_type_from_bytes`** | Not supported | Raises `NotImplementedError`, including for an enum nested inside a struct or array field (see [Basic Types](#basic-types)) |

Coming from PipelineC? See also [docs/pipelinec_to_pypeline.md](pipelinec_to_pypeline.md)
for a pattern-by-pattern translation reference.
