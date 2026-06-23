# pypeline User Guide

pypeline is the Python front-end for PipelineC.
You write hardware designs in ordinary Python; the compiler translates them to VHDL and
synthesises them for an FPGA.

## Table of Contents

1. [What is pypeline?](#1-what-is-pypeline)
2. [Worked Example: VGA Test Pattern](#2-worked-example-vga-test-pattern)
3. [Digital Logic Basics](#3-digital-logic-basics)
4. [Simulation](#4-simulation)
5. [Top-Level Entry Points](#5-top-level-entry-points)
6. [Your First Hardware Function](#6-your-first-hardware-function)
7. [Calling Functions](#7-calling-functions)
8. [Registers: `Reg[T]`](#8-registers-regt)
9. [Feedback Wires: `Feedback[T]`](#9-feedback-wires-feedbackt)
10. [Bit Manipulation](#10-bit-manipulation)
11. [Types](#11-types)
12. [Parametric Hardware with Factory Functions](#12-parametric-hardware-with-factory-functions)
13. [Custom Operators](#13-custom-operators)
14. [Global Signals](#14-global-signals)
15. [Forcing Pipelining: `autopipeline()`](#15-forcing-pipelining-autopipeline)
16. [Multi-Cycle Paths: `MULTI_CYCLE[...]`](#16-multi-cycle-paths-multi_cycle)
17. [Raw VHDL Passthrough: `vhdl()`](#17-raw-vhdl-passthrough-vhdl)
18. [Just-Wires Synthesis Hint: `@wires`](#18-just-wires-synthesis-hint-wires)
19. [Keep-Tagged Lanes: `kept_data_bus_t`](#19-keep-tagged-lanes-kept_data_bus_t)
20. [N-Dimensional Stream Fragments: `ndarray_fragment_t`](#20-n-dimensional-stream-fragments-ndarray_fragment_t)
21. [Valid/Ready Streams: `stream_t`](#21-validready-streams-stream_t)
22. [AXI-Stream: `axis_t`](#22-axi-stream-axis_t)
23. [FIFOs: `make_stream_fifo`](#23-fifos-make_stream_fifo)
24. [Pipelined Stream Wrappers: `make_stream_pipeline`](#24-pipelined-stream-wrappers-make_stream_pipeline)

---

## 1 What is pypeline?

pypeline lets you describe digital hardware using Python syntax.
A design file is a regular Python module.
Module-level code (constants, type definitions, helper factories) runs as plain Python at
compile time.
Functions whose arguments and return value carry type annotations describe hardware
circuits; the compiler translates their bodies into logic and emits VHDL via the
PipelineC backend.

The mental model: **a hardware-annotated function is a circuit module**,
not a subroutine.
Its inputs and outputs are wires, its local variables are signals, and every line of its
body describes combinational or sequential logic.

Pure (combinational) functions are automatically pipelined by PipelineC to meet timing —
you write the dataflow, the tool inserts pipeline registers wherever needed to hit the
target clock frequency.

---

## 2 Worked Example: VGA Test Pattern

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
[Top-Level Entry Points](#5-top-level-entry-points).
`vga_timing_signals_t` and `vga_12bpp_t` are struct types — see [Types](#11-types).
`make_vga_timing` is a factory closure — see
[Parametric Hardware with Factory Functions](#12-parametric-hardware-with-factory-functions).
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
  [Bit Manipulation](#10-bit-manipulation).
- `sig.active` — hardware `if`, synthesised as a MUX: colour inside the image, black
  outside; see [Your First Hardware Function](#6-your-first-hardware-function).
- `vga_12bpp_t(...)` — compound struct initialiser; see [Types](#11-types).

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
[Top-Level Entry Points](#5-top-level-entry-points).
`vga_timing()` is a hardware function call (submodule instance) that contains
registers — see [Registers: `Reg[T]`](#8-registers-regt).
`board_vga.vga_pmod` is a `Wire[T]` declared in the imported board file; assigning to it
drives the FPGA pins — see [Global Signals](#14-global-signals).

### Simulation display

```python
@sim_output
def capture_pixel(sig, px):
    # accumulate pixels into a numpy array and refresh a matplotlib window
    ...
```

`@sim_output` marks this as simulation-only — see [Simulation](#4-simulation).
The hardware compiler skips it entirely; `pypeline_sim.py` calls it once per clock cycle
after convergence.

### Running the simulation

```
python3 src/pypeline_sim.py examples/pypeline/vga_test_pattern.py --run 420000
```

One frame of 640×480 video at 25 MHz = 800 × 525 = 420 000 cycles.
A matplotlib window appears and fills in as the simulation runs.

### Synthesising for the FPGA

Run pipelinec on the design file (see the main PipelineC documentation for build steps).
The `PART()` call and `@MAIN(mhz)` frequency constraint are forwarded to Vivado.

---

## 3 Digital Logic Basics

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

## 4 Simulation

pypeline designs can be simulated in Python before synthesising for an FPGA.
This is useful for unit-testing combinational functions and verifying register behaviour.

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

### `pypeline_sim.py` — multi-MAIN designs

Designs that use `Wire[T]` global signals (see [Global Signals](#14-global-signals))
require running multiple `@MAIN` functions together.
Use the `pypeline_sim.py` CLI:

```
python3 src/pypeline_sim.py my_design.py --run 1000
```

This runs 1000 simulated clock cycles, with delta-cycle convergence each cycle to resolve
global wires before committing register values.

A `--mode` flag trades simulation accuracy for speed:

| Mode | Description |
|---|---|
| `strict` (default) | Full hardware accuracy — integer widths masked at every typed operation |
| `loose` | SimVal objects preserved (bit-indexing works) but no bit-width masking on arithmetic |
| `raw` | Maximum speed (~9× faster than strict) — plain Python ints throughout; use for structural tests where precise overflow behaviour is not needed |

```
python3 src/pypeline_sim.py my_design.py --run 1000 --mode raw
```

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
they produce no gates or wires in the synthesised design.

---

## 5 Top-Level Entry Points

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

---

## 6 Your First Hardware Function

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
only via global signals (see [Global Signals](#14-global-signals)).

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

## 7 Calling Functions

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

**Recursive imports are not followed automatically.**
Only the top file's `import` statements are processed.
If `file_a.py` itself imports `file_b.py`, `file_b` must also be imported by the
top file if its hardware functions or wires are needed.

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

Module-level constants from sub-files are not directly accessible by name inside a
hardware function body.
Copy them at module level in the top file first:

```python
import my_lib
SHIFT = my_lib.SHIFT_AMOUNT   # now available as a plain Python int in this module
```

---

## 8 Registers: `Reg[T]`

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
This is required for simulation (see [Simulation](#4-simulation)) and is good practice
for documenting that the function has hardware-typed behaviour.
Plain combinational helpers do not need it.

---

## 9 Feedback Wires: `Feedback[T]`

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

## 10 Bit Manipulation

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

## 11 Types

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
Like any combinational logic, those mux trees can be autopipelined by PipelineC when a
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

### Floating-point types

`make_float_t(E, M)` builds a struct type with `sign` (1 bit), `exp` (E bits), and
`man` (M bits) fields, matching IEEE 754 layout for standard sizes:

```python
from pypeline import make_float_t

float32_t = make_float_t(8, 23)   # standard FP32

def bias_one(x: float32_t) -> float32_t:
    one: float32_t = float32_t.as_const(1.0)   # Python float → hardware constant
    ...
```

`float32_t.as_const(value)` converts a Python `float` to a `float32_t` instance at
elaboration time.

---

## 12 Parametric Hardware with Factory Functions

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
`@hw_func`-decorated: `make_autopipeline`, `make_valid_ready_mcp`, and
`make_stream_pipeline` all validate this with `is_hw_func(func)` and raise `TypeError`
otherwise (see [§15](#15-forcing-pipelining-autopipeline) /
[§16](#16-multi-cycle-paths-multi_cycle)). This matters because `_build_reg_sim_func`'s
AST rewriting — which makes `Reg[T]`/`Feedback[T]` and bare struct/array locals
simulate correctly under `sim_call` — only runs once, at `@hw_func` decoration time, on
the function actually being decorated; it does not propagate to plain functions called
from inside that body.

Prefer `hw_arg_types`/`hw_return_type` over reading `func.__annotations__` directly, or
having a factory stash a type as a custom attribute on the function it returns (e.g.
`my_func.out_t = out_t`) — the type is already recoverable generically from the
function's own annotations, so there's no need for either function authors or callers
to manage it by hand. See `include/pypeline/multi_cycle_path.py` for the full
`make_valid_ready_mcp` example.

---

## 13 Custom Operators

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

`op` strings: `"PLUS"`, `"MINUS"`, `"SL"` (`<<`), `"SR"` (`>>`), `"NEGATE"` (unary `-`).

```python
float32_t = make_float_t(8, 23)
float_add_32 = make_float_adder(float32_t)   # user-defined float adder function

register_operator("PLUS", float32_t, float32_t, float_add_32)

@MAIN
def fp_add(a: float32_t, b: float32_t) -> float32_t:
    return a + b    # dispatches to float_add_32
```

Registrations are global.
To limit a registration to a single function's elaboration, use the `scope=` keyword:

```python
register_unary_operator("NEGATE", my_t, negate_my_t, scope=my_function)
```

---

## 14 Global Signals

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
- Each `Wire[T]` must have **exactly one** writer function.
- Any number of functions may read it.
- A function cannot both read and write the same wire.
- `Wire[T]` is **not** a register — it carries no value across clock cycles.

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

### Wire declarations have no initialiser

```python
my_wire: Wire[uint32_t]       # correct
my_wire: Wire[uint32_t] = 0  # error — initialisers are not allowed on Wire/Input/Output
```

---

## 15 Forcing Pipelining: `autopipeline()`

By default, a function called from inside a register or feedback context must complete
**combinationally, in the same cycle** as its caller — the synthesiser is not free to
split its logic across multiple clock cycles. That's normally what you want for a small
state machine. But sometimes you want to call a large, otherwise-combinational pipeline
stage (a multiplier, a divider, a deep arithmetic chain) from inside such a context, and
you're fine with it taking several cycles internally as long as it still produces a
valid/ready style stream.

`autopipeline()` tells the synthesiser it's allowed to insert pipeline registers inside
one specific function call, overriding the normal "must stay combinational here" rule:

```python
rv = autopipeline(some_func(x))          # let the synthesiser pick how many stages
rv = autopipeline(some_func(x), 2)       # force exactly 2 pipeline stages
rv = autopipeline(some_func(x), depth=2) # same, as a keyword argument
```

Wrap a single, direct function call — not a larger expression
(`autopipeline(foo(x) + 1)` is not supported, only `autopipeline(foo(x))` is).
In simulation, `autopipeline(...)` is a no-op: it just returns its argument unchanged, so
`sim_call` behaves identically with or without it.

### Example

This mirrors the shape of `examples/autopipelined_submodules.c`: a free-running
combinational pipeline stage, instantiated from inside a function that also has a
register (so without `autopipeline()`, the call would have to be a single-cycle
combinational instance):

```python
@hw_func
def pipeline_stage(x: stream_t) -> stream_t:
    rv: stream_t
    rv.data = x.data / ~x.data   # some multi-cycle-worthy combinational logic
    rv.valid = x.valid
    return rv

@hw_func
def wrapper(pipeline_in: stream_t) -> stream_t:
    # `ready_reg` makes this a register/feedback context — normally `pipeline_stage`
    # would have to complete combinationally within this same cycle.
    ready_reg: Reg[uint1_t]
    ready_reg = ~ready_reg

    # autopipeline() overrides that: the synthesiser may slice pipeline_stage's
    # logic across multiple cycles.
    return autopipeline(pipeline_stage(pipeline_in))
```

`Reg[T]` and bare struct/array locals (like `rv` above) only simulate correctly under
`sim_call` when their own function carries `@hw_func` (or `@MAIN`) — see
[§8](#8-registers-regt) / [§12](#12-parametric-hardware-with-factory-functions).

See `src/tests/pypeline_tests/inst/autopipeline_test.py` for the full example.

### Ready-made wrapper: `make_autopipeline`

Wrapping a call in `autopipeline(...)` at every call site works, but it means every
caller has to know and repeat that detail. `make_autopipeline(func, has_input_reg,
has_output_reg)` builds a standalone wrapper function around `func` *once* — the
`autopipeline(...)` call lives inside the wrapper's own body, so callers just call the
returned function like any other hardware function, from a register/feedback context or
otherwise:

```python
from pypeline import hw_func, make_autopipeline

@hw_func
def pipeline_stage(x: stream_t) -> stream_t:
    rv: stream_t
    rv.data = x.data / ~x.data
    rv.valid = x.valid
    return rv

# Builds a new function with the same (stream_t) -> stream_t signature as pipeline_stage.
# pipeline_stage must already be @hw_func-decorated -- make_autopipeline calls it
# directly from inside its own hardware function body, so it needs its own decoration
# to simulate correctly under sim_call (see §12).
pipeline_stage_ap = make_autopipeline(pipeline_stage, has_input_reg=True, has_output_reg=True)

@hw_func
def wrapper(pipeline_in: stream_t) -> stream_t:
    ready_reg: Reg[uint1_t]
    ready_reg = ~ready_reg

    # No autopipeline(...) needed here — it's already inside pipeline_stage_ap.
    return pipeline_stage_ap(pipeline_in)
```

`has_input_reg` / `has_output_reg` each add a plain `Reg[T]`, updated unconditionally
every cycle, immediately before/after the `autopipeline(...)`-wrapped call — useful for
registering the pipeline's inputs/outputs at its boundary rather than leaving them
combinational. Pass `False` for either to omit that register entirely (not just disable
it — the `Reg[T]` declaration itself is left out).

`in_type`/`out_type` are inferred from `func`'s own annotations via `hw_arg_types`/
`hw_return_type` (see [§12](#12-parametric-hardware-with-factory-functions)), the same
way `make_valid_ready_mcp` infers its types — see
`src/tests/pypeline_tests/inst/autopipeline_test.py` for the full example, which uses
`make_autopipeline(test_pipeline, has_input_reg=True, has_output_reg=True)` in place of
the raw `autopipeline(test_pipeline(...))` call shown above.

---

## 16 Multi-Cycle Paths: `MULTI_CYCLE[...]`

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

### Ready-made valid/ready wrapper: `make_valid_ready_mcp`

Wiring up the launch/capture registers and a cycle counter by hand, as above, is the
right tool when a multi-cycle path sits between two registers you're already managing
yourself inside a larger function. For the common case of wrapping one slow
combinational function in its own standalone valid/ready stream interface,
`include/pypeline/multi_cycle_path.py`'s `make_valid_ready_mcp` builds exactly that FSM
for you — the pypeline equivalent of PipelineC's `DECL_VALID_READY_MCP_FUNC` macro:

```python
from pypeline import hw_func
from stream.stream import make_stream_t
from multi_cycle_path import make_valid_ready_mcp

@hw_func
def divider(i: my_struct_t) -> uint32_t:
    return i.x / i.y

divider_mcp, divider_mcp_t = make_valid_ready_mcp(divider, 16)   # 16-cycle MCP

my_struct_stream_t = make_stream_t(my_struct_t)

@MAIN(100.0)
def top(stream_in: my_struct_stream_t, ready_for_stream_out: uint1_t) -> divider_mcp_t:
    return divider_mcp(stream_in, ready_for_stream_out)
```

`make_valid_ready_mcp(func, ncycles)` infers `in_type`/`out_type` from `func`'s own
parameter/return type annotations (unlike the C macro, which takes them as separate
arguments) and returns `(func_mcp, func_mcp_t)`:

| | Type | Meaning |
|---|---|---|
| `func_mcp(stream_in, ready_for_stream_out)` | `(stream_t(in_type), uint1_t) -> func_mcp_t` | one MCP-wrapped instance of `func` |
| `func_mcp_t.stream_out` | `stream_t(out_type)` | `func`'s result, valid `ncycles + 1` cycles after launch |
| `func_mcp_t.ready_for_stream_in` | `uint1_t` | high while the FSM is idle and ready to accept a new `stream_in` |

Internally it's the same `MULTI_CYCLE[ncycles]` / `Reg[T, MC.start]` / `Reg[T, MC.end]`
pattern shown above, with `launch`/`capture` registers and a `cycles_since_launch`
counter driving the handshake. Like `MULTI_CYCLE[...]` itself, the relaxed timing only
matters during real FPGA synthesis (requires `PART()` + Vivado); simulation always sees
`func`'s result settle the same cycle it's computed. See
`src/tests/pypeline_tests/inst/valid_ready_mcp_test.py` (translated from
`examples/mcp/mcp_divider.c`) for the full example.

---

## 17 Raw VHDL Passthrough: `vhdl()`

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

`vhdl(...)` must be the **only statement** in the function body (an optional leading
docstring is fine). The function's signature is still used to generate the entity's
ports exactly as normal — `x` and `y` become `in` ports, the return value becomes the
`return_output` `out` port — but nothing inside the body is elaborated; the text is
inserted as-is into the architecture, which already supplies
`architecture arch of <name> is ... end arch;` around it. Your text should *not* include
its own `end;` — only the declarative part (optional), `begin`, and the statements.

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

**Cannot currently be simulated.** Calling a function containing `vhdl(...)` outside
hardware elaboration — directly, via `sim_call()`, or via `pypeline_sim.py` — raises
`NotImplementedError`. There is no general way to simulate arbitrary user-supplied VHDL
text in Python; a future hook may let you attach a Python model to a specific block.

---

## 18 Just-Wires Synthesis Hint: `@wires`

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

## 19 Keep-Tagged Lanes: `kept_data_bus_t`

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
[§22 AXI-Stream](#22-axi-stream-axis_t)).

This layer has no handshake (`valid`) and no end-of-transfer flag (`eod`/`tlast`) of its
own — those are added by the layers above it.

---

## 20 N-Dimensional Stream Fragments: `ndarray_fragment_t`

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
`ndarray_fragment_t` inside [`kept_data_bus_t`](#19-keep-tagged-lanes-kept_data_bus_t)
(which already has a `.data` array field) and inside
[`stream_t`](#21-validready-streams-stream_t) (which already has a `.data` payload field)
doesn't produce an ambiguous `.data.data.data` chain.

`frag_t` can be anything — a single struct (one whole element per transfer, as above) or a
[`kept_data_bus_t`](#19-keep-tagged-lanes-kept_data_bus_t) (multiple byte/element lanes per
transfer, the AXI-Stream case — see [§22](#22-axi-stream-axis_t)).

---

## 21 Valid/Ready Streams: `stream_t`

`stream_t`, from `include/pypeline/stream/stream.py`, adds the final piece needed for a
standard streaming interface: a `.valid` bit marking whether this cycle's payload is
actually being transferred. Pair it with a plain `uint1_t ready` signal at the call site
for a full valid/ready handshake (pypeline doesn't bundle `ready` into the struct itself,
since `ready` flows in the opposite direction along the stream).

```python
from stream.stream import make_stream_t

uint32_stream_t = make_stream_t(uint32_t)

def consume(s: uint32_stream_t, downstream_ready: uint1_t) -> uint1_t:
    accepted: uint1_t = s.valid & downstream_ready
    if accepted:
        ...  # use s.data
    return accepted   # this stage's ready_for_input, computed however is appropriate
```

`make_stream_t(data_t)` returns a struct with two fields:

| Field | Type | Meaning |
|---|---|---|
| `.data` | `data_t` | the payload |
| `.valid` | `uint1_t` | whether `.data` is valid this cycle |

`data_t` is typically an [`ndarray_fragment_t`](#20-n-dimensional-stream-fragments-ndarray_fragment_t)
(giving end-of-dimension flags) or a [`kept_data_bus_t`](#19-keep-tagged-lanes-kept_data_bus_t)
(giving per-lane keep flags), but it can be any type — `make_stream_t(uint32_t)` above is a
plain valid-only stream of integers with no `eod`/`keep` layer at all.

---

## 22 AXI-Stream: `axis_t`

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
[`ndarray_fragment_t`](#20-n-dimensional-stream-fragments-ndarray_fragment_t) does on its
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
[§6 for/while → loop unrolling](#6-your-first-hardware-function)), so there's no need for
the per-width duplication older, non-generic AXIS implementations require.

See `src/tests/pypeline_tests/inst/axis_test.py` for a complete worked example, including
synthesis through `pipelinec`.

---

## 23 FIFOs: `make_stream_fifo`

`include/pypeline/stream/stream_fifo.py`'s `make_stream_fifo` wraps a single-clock-domain FIFO
in pypeline's standard [`stream_t`](#21-validready-streams-stream_t) valid/ready shape, so you
don't have to unpack/repack `.data`/`.valid` by hand. (It's a thin layer over
`include/pypeline/fifo.py`'s lower-level `make_fifo` — most users should just use
`make_stream_fifo` directly and never need to touch `make_fifo` itself.)

```python
from pypeline import uint32_t, MAIN, uint1_t
from stream.stream import make_stream_t
from stream.stream_fifo import make_stream_fifo

uint32_stream_t = make_stream_t(uint32_t)
stream_fifo, stream_fifo_t = make_stream_fifo(uint32_t, 256)   # 256-deep FIFO of uint32_t

@MAIN
def buffered(out_ready: uint1_t, in_stream: uint32_stream_t) -> stream_fifo_t:
    return stream_fifo(out_ready, in_stream)
```

`make_stream_fifo(data_t, depth, mode="fwft")` returns `(stream_fifo_func, stream_fifo_t)`:

| | Type | Meaning |
|---|---|---|
| `stream_fifo_func(out_ready, in_stream)` | `(uint1_t, stream_t) -> stream_fifo_t` | one FIFO instance |
| `stream_fifo_t.out_stream` | `stream_t` | the FIFO's output: `.data`/`.valid` |
| `stream_fifo_t.in_ready` | `uint1_t` | backpressure for `in_stream` — high while the FIFO has room |

`in_stream` is built with `make_stream_t(data_t)` exactly as in [§21](#21-validready-streams-stream_t).
`out_ready` is the downstream consumer's readiness for `stream_fifo_t.out_stream`, following the
same convention `stream_t` itself uses — `ready` flows opposite to the stream and isn't bundled
into the struct, so you wire it in from whatever's downstream.

`depth` must be `>= 2`. `mode` only accepts `"fwft"` (first-word-fall-through) for now — the
only underlying FIFO implementation currently available.

**Cannot currently be simulated.** Like anything built on [`vhdl()`](#17-raw-vhdl-passthrough-vhdl)
(the FIFO is a raw VHDL entity instantiated under the hood), calling `stream_fifo_func` outside
hardware elaboration — directly, via `sim_call()`, or via `pypeline_sim.py` — raises
`NotImplementedError`. Synthesise/elaborate normally through `pipelinec` to use it.
See `src/tests/pypeline_tests/inst/stream_fifo_test.py`.

---

## 24 Pipelined Stream Wrappers: `make_stream_pipeline`

`include/pypeline/stream/stream_pipeline.py`'s `make_stream_pipeline` wraps a single
combinational hardware function in a free-running, fully-pipelined
[`stream_t`](#21-validready-streams-stream_t) interface: an
[AUTOPIPELINE'd](#15-forcing-pipelining-autopipeline) instance (with registered
input/output) feeding a [`make_fifo`](#23-fifos-make_stream_fifo)-backed output FIFO sized
`MAX_IN_FLIGHT`. It's the pypeline equivalent of PipelineC's
`GLOBAL_VALID_READY_PIPELINE_INST` macro — minus the global wires, since this is one
locally-instantiated function rather than two `MAIN`s joined by `Wire[T]`s.

```python
from pypeline import hw_func, uint8_t, MAIN, uint1_t
from stream.stream import make_stream_t
from stream.stream_pipeline import make_stream_pipeline

@hw_func
def div_inv(x: uint8_t) -> uint8_t:
    return x / ~x

uint8_stream_t = make_stream_t(uint8_t)
stream_pipeline, stream_pipeline_t = make_stream_pipeline(div_inv, MAX_IN_FLIGHT=4)

@MAIN(50.0)
def buffered_div_inv(
    stream_in: uint8_stream_t, ready_for_stream_out: uint1_t
) -> stream_pipeline_t:
    return stream_pipeline(stream_in, ready_for_stream_out)
```

`make_stream_pipeline(func, MAX_IN_FLIGHT)` returns `(stream_pipeline_func, stream_pipeline_t)`:

| | Type | Meaning |
|---|---|---|
| `stream_pipeline_func(stream_in, ready_for_stream_out)` | `(stream_t(in_type), uint1_t) -> stream_pipeline_t` | one pipelined instance of `func` |
| `stream_pipeline_t.stream_out` | `stream_t(out_type)` | `func`'s result, after AUTOPIPELINE retiming and the output FIFO |
| `stream_pipeline_t.ready_for_stream_in` | `uint1_t` | high while the pipeline can accept a new `stream_in` (tracks in-flight count against `MAX_IN_FLIGHT`) |

`in_type`/`out_type` are inferred from `func`'s own annotations via `hw_arg_types`/
`hw_return_type`, the same way `make_autopipeline` and `make_valid_ready_mcp` do (see
[§12](#12-parametric-hardware-with-factory-functions)). **`func` must already be
`@hw_func`-decorated** — `make_stream_pipeline` calls `is_hw_func(func)` and raises
`TypeError` immediately if it isn't, since `func` is called from inside an internal
AUTOPIPELINE'd wrapper and needs its own decoration for any `Reg[T]`/bare struct-array
locals in its body to simulate correctly (see [§15](#15-forcing-pipelining-autopipeline)).

**Cannot currently be simulated.** Same limitation as `make_stream_fifo` above — the
internal FIFO is built on `vhdl()`, so calling `stream_pipeline_func` via `sim_call()` or
`pypeline_sim.py` raises `NotImplementedError`. Synthesise/elaborate normally through
`pipelinec` to use it. See `src/tests/pypeline_tests/inst/stream_pipeline_test.py`.
