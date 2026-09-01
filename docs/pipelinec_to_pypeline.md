# PipelineC → pypeline Translation Guide

This guide helps you translate existing PipelineC (C-based HDL) designs to
[pypeline](pypeline_guide.md) (the Python front-end for PipelineC).
It is organised around common PipelineC patterns, showing the equivalent pypeline Python
side-by-side. For the full pypeline API reference see [pypeline_guide.md](pypeline_guide.md).

PipelineC documentation: [GitHub wiki](https://github.com/JulianKemmerer/PipelineC/wiki)

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section, if it
> has one, rather than appending a new one. See
> [documentation conventions](README.md#documentation-conventions).

## Table of Contents

1. [Files and Includes](#1-files-and-includes)
2. [FPGA Part Declaration](#2-fpga-part-declaration)
3. [Types](#3-types)
4. [Top-Level Entry Points](#4-top-level-entry-points)
5. [External Ports: DECL_INPUT / DECL_OUTPUT](#5-external-ports-decl_input--decl_output)
6. [Registers: Static Local Variables](#6-registers-static-local-variables)
7. [Feedback Signals](#7-feedback-signals)
8. [Global Instances (GLOBAL_ Macros)](#8-global-instances-global_-macros)
9. [Bit Manipulation](#9-bit-manipulation)
10. [Streams and Handshakes](#10-streams-and-handshakes)
11. [Synthesis Pragmas](#11-synthesis-pragmas)
12. [Parametric / Generic Hardware](#12-parametric--generic-hardware)
13. [Not Yet Supported](#13-not-yet-supported)
14. [Debug Output: printf / sim_print](#14-debug-output-printf--sim_print)

---

## 1. Files and Includes

PipelineC uses `#include` to pull in type definitions, macros, and auto-generated
clock-crossing headers. pypeline uses ordinary Python imports.

| PipelineC | pypeline |
|---|---|
| `#include "uintN_t.h"` | not needed — integer types are built-in |
| `#include "axi/axis.h"` | `from stream.axis import make_axis_t` |
| `#include "stream/stream.h"` | `from stream.stream import make_stream_t` |
| `#include "global_func_inst.h"` | not needed — use Python directly (see §8) |
| `#include "dsp/fir.h"` (macro-config FIR) | `from dsp.fir import make_fir` (see guide §25 "DSP: FIR Filters") |
| `#include "dsp/fir_decim.h"` / `"dsp/fir_interp.h"` | `from dsp.fir_decim import make_fir_decim` / `from dsp.fir_interp import make_fir_interp` |
| `#include "mymodule.h"` | `import mymodule` |

Only **qualified imports** are supported in pypeline — `import mymodule` then
`mymodule.my_func(...)`. The `from mymodule import *` form is not supported.

```c
// PipelineC
#include "uintN_t.h"
#include "axi/axis.h"
#include "mymodule.h"
```
```python
# pypeline
from pypeline import *          # brings in uint8_t, uint32_t, Reg, Wire, etc.
from stream.axis import make_axis_t
import mymodule
```

---

## 2. FPGA Part Declaration

```c
// PipelineC
#pragma PART "xc7a100tcsg324-1"
```
```python
# pypeline (module level)
PART("xc7a100tcsg324-1")
```

Without `PART()`, pypeline uses a software timing estimator instead of real synthesis.
See [pypeline_guide.md §5](pypeline_guide.md#top-level-entry-points).

---

## 3. Types

### 3a. Integer Types

Standard-width integer types have the same names in both languages.

| PipelineC | pypeline |
|---|---|
| `uint1_t`, `uint8_t`, `uint16_t`, `uint32_t`, `uint64_t` | same (built-in) |
| `int8_t`, `int32_t` | same (built-in) |
| `UINT_N(27)` / `uint27_t` | `make_uint_t(27)` |
| `INT_N(12)` / `int12_t` | `make_int_t(12)` |

### 3b. Struct Types

```c
// PipelineC
typedef struct rgb_t {
    uint5_t r;
    uint6_t g;
    uint5_t b;
} rgb_t;
```
```python
# pypeline
@struct
class rgb_t(NamedTuple):
    r: uint5_t
    g: uint6_t
    b: uint5_t
```

Struct fields are accessed the same way in both: `pixel.r`, `pixel.g`, etc.
Compound initializers use the NamedTuple constructor:
`rgb_t(r=uint5_t(31), g=uint6_t(0), b=uint5_t(0))`.

### 3c. Arrays

```c
// PipelineC
uint32_t data[4];
```
```python
# pypeline
data: uint32_t[4]
```

Indexing with a compile-time constant is free; indexing with a hardware signal infers a
mux tree. See [pypeline_guide.md §11](pypeline_guide.md#basic-types).

### 3d. Casting

A PipelineC C-style cast on a scalar int type has a direct pypeline equivalent: calling
the type with the value as its one positional argument. It behaves exactly like an
annotated-intermediate assignment (same truncation/sign-extension) — the two are
guaranteed to agree, since a cast lowers to the identical mechanism assignment uses, not
a separate one.

```c
// PipelineC
uint32_t widen(uint16_t x) {
    return (uint32_t)x;
}
```
```python
# pypeline
def widen(x: uint16_t) -> uint32_t:
    return uint32_t(x)   # identical to: tmp: uint32_t = x; return tmp
```

Casting to `char_t`, an `@enum` type, or an array type (`uint8_t[4](x)`) is not
supported. Casting between compound (struct/`@interface`-half) types is supported, but
unlike C's cast it is never an unchecked bit reinterpretation — it dispatches to a
function registered with `register_cast(src_t, dst_t, func)` or `@cast`, so a struct
cast is always a real, defined conversion. See
[pypeline_guide.md §11 (Casting)](pypeline_guide.md#casting).

### 3e. Enum Types

PipelineC `typedef enum` maps to a Python `IntEnum` subclass decorated with `@enum`:

```c
// PipelineC
typedef enum { IDLE=0, RUNNING=1, DONE=2 } state_t;
```

```python
# pypeline
from enum import IntEnum
from pypeline import enum

@enum
class state_t(IntEnum):
    IDLE    = 0
    RUNNING = 1
    DONE    = 2
```

Enums are integer-encoded (not one-hot). The bit width is computed automatically from the
largest member value. Member access (`state_t.IDLE`) and comparisons (`s == state_t.IDLE`)
work identically to PipelineC. Use `Reg[state_t]` for FSM state registers.

Parameterizable enums (like parameterizable structs) are written as user factories:

```python
def make_traffic_t(include_yellow=True):
    members = {"RED": 0, "GREEN": 2}
    if include_yellow:
        members["YELLOW"] = 1
    return enum(IntEnum("traffic_t", members))

traffic_t = make_traffic_t(include_yellow=True)
```

See [pypeline_guide.md §11 (Enum types)](pypeline_guide.md#enum-types) for the full API.

### 3f. Char Array (String) Types

PipelineC's `char`/`char[N]` maps to Pypeline's predefined `char_t` scalar type combined
with the same `[N]` array syntax used for any other array:

```c
// PipelineC
char name[16] = "hello";
```

```python
# pypeline
from pypeline import char_t

name: char_t[16] = "hello"
```

A string literal shorter than the declared array is zero-padded; longer raises an
elaboration error. String literals also work as struct-field initializers, return values,
and call arguments (`some_func("literal")`), exactly like PipelineC's `char[N]`
initializers and `char name[16]` function parameters.

`strlen(arr)` maps directly to PipelineC's `strlen()` and has the **same
capacity-not-content semantics**: it returns the array's declared size (a compile-time
constant), not a runtime scan for a NUL terminator — `strlen(name)` above is always `16`,
not `5`.

In simulation, a `char_t[N]` value is a `CharArray` (a list of `SimVal`s that also behaves
like the Python string it represents) — pass and compare plain Python `str` values
directly, no conversion needed (see [pypeline_guide.md §11](pypeline_guide.md#basic-types)).

`Reg[char_t[N]]` currently only supports zero-init (no `=` initializer) — see
[pypeline_DESIGN.md](pypeline_DESIGN.md#char-array-support) for the known limitation.

### 3g. Floating-Point Types

Pypeline has no native float type — this isn't a PipelineC construct being renamed,
it's new: `include/pypeline/floating_point.py` builds IEEE 754-like **struct** types
(`sign`/`exp`/`man` fields) with `+`/`-`/`*`/`/` already overloaded:

```python
from floating_point import float32_t, float64_t

def add(a: float32_t, b: float32_t) -> float32_t:
    return a + b   # dispatches to the library's registered adder
```

If you're translating PipelineC/C code that manually reinterprets a `uint32_t`'s
bits as a float (a union, a pointer cast, or hand-written `asuint32`/`asfloat32`-style
helpers), the pypeline equivalent is **not** a cast — a pypeline cast between two
struct types is always a value-preserving *conversion* through a registered function
(see [§3d Casting](#3d-casting)), never an unchecked reinterpretation of the same bits,
and no such conversion is registered between `float32_t` and `uint32_t` (that pairing
isn't a numeric conversion at all). Convert by bit-slicing the fields
out (or `concat()`-ing them back together):

```python
from pypeline import concat, uint32_t
from floating_point import float32_t

E_LEN = len(float32_t.typeof("exp"))   # 8
M_LEN = len(float32_t.typeof("man"))   # 23
S_BIT = E_LEN + M_LEN                  # 31 -- sign is the top bit

def uint32_to_float32(bits: uint32_t) -> float32_t:
    return float32_t(sign=bits[S_BIT], exp=bits[S_BIT-1:M_LEN], man=bits[M_LEN-1:0])

def float32_to_uint32(f: float32_t) -> uint32_t:
    return concat(f.sign, f.exp, f.man)   # first arg = MSB
```

That's for crossing a boundary declared as a plain `uintN_t` (a port, a stream
payload). Converting between float precisions, or to/from an actual int *value*,
is a different operation — use `make_float_converter`/`make_float_to_int`/
`make_int_to_float` (also in `floating_point`) instead of either of the above.

See [pypeline_guide.md §11](pypeline_guide.md#basic-types) for the full explanation
(including why `typeof()` keeps this generic across exponent/mantissa widths) and
`src/tests/pypeline_tests/inst/float32_add_test.py` /
`src/tests/pypeline_tests/inst/float_ops_test.py` for complete worked examples.

---

## 4. Top-Level Entry Points

Each `#pragma MAIN` / `#pragma MAIN_MHZ` function becomes an `@MAIN`-decorated Python
function. Each generates one independent VHDL process.

```c
// PipelineC — no frequency constraint
#pragma MAIN my_top
void my_top() { ... }

// PipelineC — with MHz constraint
#pragma MAIN_MHZ my_top 100.0
void my_top() { ... }
```
```python
# pypeline — no frequency constraint
@MAIN
def my_top():
    ...

# pypeline — with MHz constraint
@MAIN(100.0)
def my_top():
    ...
```

Multiple `#pragma MAIN` functions in one `.c` file → multiple `@MAIN` functions in one
`.py` file. They share the same global signals (see §8).

See [pypeline_guide.md §5](pypeline_guide.md#top-level-entry-points).

---

## 5. External Ports: DECL_INPUT / DECL_OUTPUT

External FPGA pins are declared at module scope. Port names must exactly match the
constraint file (XDC / PCF).

```c
// PipelineC
DECL_INPUT(uint32_t, my_data_in)
DECL_OUTPUT(uint32_t, my_data_out)
```
```python
# pypeline
my_data_in:  Input[uint32_t]
my_data_out: Output[uint32_t]
```

### Registered variants (DECL_INPUT_REG / DECL_OUTPUT_REG)

PipelineC's `DECL_INPUT_REG` and `DECL_OUTPUT_REG` insert a register stage on the port.
In pypeline, declare the port normally and add the register explicitly inside `@MAIN`:

```c
// PipelineC
DECL_INPUT_REG(uint1_t, btn)
DECL_OUTPUT_REG(uint1_t, led)
```
```python
# pypeline
btn: Input[uint1_t]
led: Output[uint1_t]

@MAIN
def top():
    btn_r: Reg[uint1_t]
    btn_r = btn             # register the input

    # ... logic using btn_r ...

    led_r: Reg[uint1_t]
    led_r = compute_led()
    led = led_r             # register the output
```

See [pypeline_guide.md §14](pypeline_guide.md#global-signals).

---

## 6. Registers: Static Local Variables

In PipelineC, `static` local variables inside a function persist across clock cycles —
they are registers (flip-flops). In pypeline, use `Reg[T]`.

```c
// PipelineC
void my_func() {
    static uint32_t counter = 0;
    static uint32_t accum   = 10;   // non-zero initial value
    static uint1_t  flag    = 1;
    static uint8_t  buf[16];        // register array
    counter += 1;
}
```
```python
# pypeline
@MAIN
def my_func():
    counter: Reg[uint32_t]           # initialises to 0
    accum:   Reg[uint32_t] = 10      # non-zero initial value
    flag:    Reg[uint1_t]  = 1
    buf:     Reg[uint8_t[16]]        # register array
    counter = counter + 1
```

`Reg[T]` uses **blocking-assignment semantics**: reading `counter` before any assignment
gives the previous cycle's value; reading after assignment gives the new value. The final
assigned value latches at the next clock edge.

Functions containing `Reg[T]` must be decorated `@hw_func` or `@MAIN` so simulation
tracks register state correctly.

See [pypeline_guide.md §8](pypeline_guide.md#registers-regt).

---

## 7. Feedback Signals

PipelineC's `#pragma FEEDBACK` marks a variable that is used (read) before it is driven
(written) within the same function body — a combinational reverse-propagating path common
in handshake logic.

```c
// PipelineC
uint1_t ready_for_in;
#pragma FEEDBACK ready_for_in
// ... later, after uses of ready_for_in:
ready_for_in = downstream_ready & some_condition;
```
```python
# pypeline
ready_for_in: Feedback[uint1_t]      # declare with Feedback annotation
# ... uses of ready_for_in before the assignment:
if ready_for_in:
    ...
# ... later, the driver:
ready_for_in = downstream_ready & some_condition
```

`Feedback[T]` is purely combinational (no storage, no clock edge). Do not give it an
initializer. See [pypeline_guide.md §9](pypeline_guide.md#feedback-wires-feedbackt).

---

## 8. Global Instances (GLOBAL_ Macros)

PipelineC's `GLOBAL_*` macros are shorthand for a common pattern:

1. Declare global wires for the instance's input and output.
2. Instantiate the function (possibly with buffering / handshake logic).
3. Wire everything together inside a dedicated `@MAIN`.

pypeline makes all three steps explicit. The subsections below show each macro and its
pypeline equivalent.

### 8a. GLOBAL_FUNC_INST — combinational, zero latency

```c
// PipelineC
// Declares: my_inst_in (in_t), my_inst_out (out_t)
GLOBAL_FUNC_INST(my_inst, out_t, my_func, in_t)
```
```python
# pypeline
my_inst_in:  Wire[in_t]
my_inst_out: Wire[out_t]

@MAIN
def my_inst_main():
    my_inst_out = my_func(my_inst_in)
```

### 8b. GLOBAL_PIPELINE_INST — registered input + output (≥2 cycle latency)

```c
// PipelineC
GLOBAL_PIPELINE_INST(my_inst, out_t, my_func, in_t)
```
```python
# pypeline
my_inst_pipeline = make_autopipeline(my_func, has_input_reg=True, has_output_reg=True)

my_inst_in:  Wire[in_t]
my_inst_out: Wire[out_t]

@MAIN
def my_inst_main():
    my_inst_out = my_inst_pipeline(my_inst_in)
```

See [pypeline_guide.md §15](pypeline_guide.md#tool-chosen-implementation-autopipeline-and-autofsm).

The wrapped function may be flat or hierarchical. Neither frontend requires users to
split its source into helper functions sized like pipeline stages: elaboration exposes
individual operations, and the common backend chooses legal operation-output or
bit-internal placements. Generated `N` register slices correspond to `N + 1`
combinational pipeline stages; see [SYN_DESIGN.md](SYN_DESIGN.md) and
[VHDL_DESIGN.md](VHDL_DESIGN.md).

### 8c. GLOBAL_VALID_READY_PIPELINE_INST — stream pipeline with FIFO

This is the most common pattern for high-throughput pipelined compute. pypeline provides
`make_stream_pipeline` as a direct equivalent.

```c
// PipelineC — func takes in_t, returns out_t
GLOBAL_VALID_READY_PIPELINE_INST(name, out_t, func, in_t, MAX_IN_FLIGHT)
// Declares: name_in (stream of in_t), name_in_ready,
//           name_out (stream of out_t), name_out_ready
```
```python
# pypeline
from stream.stream import make_stream_t
from stream.stream_pipeline import make_stream_pipeline

stream_in_t  = make_stream_t(in_t)
stream_out_t = make_stream_t(out_t)
name_pipeline_func, name_pipeline_t = make_stream_pipeline(func, MAX_IN_FLIGHT)

name_in:          Wire[stream_in_t]
name_out:         Wire[stream_out_t]
name_out_ready:   Wire[uint1_t]      # driven by the downstream consumer
name_in_ready:    Wire[uint1_t]      # read by the upstream producer

@MAIN
def name_main():
    result = name_pipeline_func(name_in, name_out_ready)
    name_out      = result.stream_out
    name_in_ready = result.stream_in.ready
```

See [pypeline_guide.md §25](pypeline_guide.md#pipelined-stream-wrappers-make_stream_pipeline).

### 8d. GLOBAL_STREAM_FIFO — synchronous FIFO

```c
// PipelineC
// Declares: fifo_name_in, fifo_name_in_ready,
//           fifo_name_out, fifo_name_out_ready
GLOBAL_STREAM_FIFO(T, fifo_name, depth)
```
```python
# pypeline
from stream.stream import make_stream_t
from stream.stream_fifo import make_stream_fifo

stream_T = make_stream_t(T)
fifo_func, fifo_t = make_stream_fifo(T, depth)

fifo_name_in:        Wire[stream_T]
fifo_name_out:       Wire[stream_T]
fifo_name_in_ready:  Wire[uint1_t]
fifo_name_out_ready: Wire[uint1_t]   # driven by downstream consumer

@MAIN
def fifo_name_main():
    result = fifo_func(fifo_name_out_ready, fifo_name_in)
    fifo_name_out      = result.out_stream
    fifo_name_in_ready = result.in_ready
```

See [pypeline_guide.md §24](pypeline_guide.md#fifos-make_stream_fifo).

### 8e. GLOBAL_VALID_READY_MCP_INST — multi-cycle path pipeline

```c
// PipelineC
GLOBAL_VALID_READY_MCP_INST(name, out_t, func, in_t, ncycles)
```
```python
# pypeline
from pypeline import make_valid_ready_mcp

name_mcp_func, name_mcp_t = make_valid_ready_mcp(func, ncycles)

# Wire and @MAIN pattern identical to 8c above,
# substituting name_mcp_func for name_pipeline_func.
```

See [pypeline_guide.md §16](pypeline_guide.md#multi-cycle-paths-multi_cycle).

### 8f. Stream wrapper for AUTOFSM — `make_stream_autofsm`

No PipelineC macro maps onto this one directly — `AUTOFSM` (the resource-shared
FSM builder) is pypeline-only, with no C-side equivalent to wrap. Included here
because it completes the family started by 8c/8e above: a third
function-to-stream wrapper, same port shape, this time around `AUTOFSM` instead
of `AUTOPIPELINE`/`MULTI_CYCLE[...]`.

```python
# pypeline
from stream.stream_autofsm import make_stream_autofsm

name_autofsm_func, name_autofsm_t = make_stream_autofsm(func)

# Wire and @MAIN pattern identical to 8c above,
# substituting name_autofsm_func for name_pipeline_func.
```

Unlike `AUTOFSM(func)`'s own raw call site (which drops a result if the
consumer isn't ready, and needs a hand-rolled `busy` register), the wrapper
gives a real valid/ready port with a held, never-dropped result across a
stalled consumer. See
[pypeline_guide.md §27](pypeline_guide.md#stream-wrapper-for-autofsm-make_stream_autofsm).

---

## 9. Bit Manipulation

Most bitwise operators are identical. The differences are in packing/unpacking helpers.

| PipelineC | pypeline | Notes |
|---|---|---|
| `>>`, `<<`, `&`, `\|`, `^`, `~` | same operators | |
| `uint8_uint8(b1, b0)` | `concat(b1, b0)` | first arg = MSB |
| `uint16_uint16(msb, lsb)` | `concat(msb, lsb)` | |
| `rotl32_16(x)` | `rotl(x, 16)` | `rotl(value, amount)` -- width comes from `value`'s type |
| `rotr32_8(x)` | `rotr(x, 8)` | |
| `x[15]` | `x[15]` | single-bit select → `uint1_t` |
| `x[15:8]` | `x[15:8]` | bit-slice read |
| `x[7:0] = y` | `x[7:0] = y` | bit-slice assign |
| `bit_dup(b, 8)` | `bit_dup(b, 8)` | replicate bit N times |

**Byte / bit array conversions**

```c
// PipelineC — pack array of bytes into a uint
UINT_TO_BYTE_ARRAY(dst_array, 16, src_uint128)
uint128_t repacked = uint8_array16_le(src_array);
```
```python
# pypeline — loop over byte slices
for i in range(16):
    dst_array[i] = src_uint128[i*8+7 : i*8]

repacked = bswap(src_array)          # or manual concat() chain
```

See [pypeline_guide.md §10](pypeline_guide.md#bit-manipulation).

---

## 10. Streams and Handshakes

### Stream type declaration

```c
// PipelineC
DECL_STREAM_TYPE(my_t)
// creates: my_t_stream_t { my_t data; uint1_t valid; }
stream(my_t) s;
```
```python
# pypeline
stream_my_t = make_stream_t(my_t)    # returns the stream type
s: stream_my_t
```

### AXI-Stream widths

PipelineC's pre-built axis types map directly to `make_axis_t(n)` where `n` is the
number of byte lanes.

| PipelineC type | pypeline |
|---|---|
| `axis8_t` | `make_axis_t(1)` |
| `axis32_t` | `make_axis_t(4)` |
| `axis128_t` | `make_axis_t(16)` |
| `axis512_t` | `make_axis_t(64)` |

```c
// PipelineC — 128-bit AXI-Stream
stream(axis128_t) my_stream;
```
```python
# pypeline
axis128_t    = make_axis_t(16)
stream_axis128_t = make_stream_t(axis128_t)
my_stream: stream_axis128_t
```

### Valid/ready handshake

The handshake pattern is the same concept in both languages: `.valid` travels with the
data, `ready` flows in the opposite direction as a plain `uint1_t`.

```c
// PipelineC — inside a MAIN, consuming a stream
if (my_stream_in.valid & downstream_ready) {
    my_stream_in_ready = 1;
    // process my_stream_in.data
}
```
```python
# pypeline — same logic
if my_stream_in.valid & downstream_ready:
    my_stream_in_ready = uint1_t(1)
    # process my_stream_in.data
```

See [pypeline_guide.md §22](pypeline_guide.md#bidirectional-ports-interface) and
[§23](pypeline_guide.md#axi-stream-axis_t).

---

## 11. Synthesis Pragmas

Most PipelineC `#pragma` annotations have a direct pypeline equivalent.

| PipelineC | pypeline | Reference |
|---|---|---|
| `#pragma PART "..."` | `PART("...")` at module level | [§5](pypeline_guide.md#top-level-entry-points) |
| `#pragma MAIN func` | `@MAIN` decorator | [§5](pypeline_guide.md#top-level-entry-points) |
| `#pragma MAIN_MHZ func 100.0` | `@MAIN(100.0)` decorator | [§5](pypeline_guide.md#top-level-entry-points) |
| `DECL_INPUT(uint1_t, clk)` + `CLK_MHZ(clk, 100.0)` | `clk: Input[uint1_t] = make_clock(100.0)` | [§5](pypeline_guide.md#top-level-entry-points) |
| `#pragma FEEDBACK x` | `x: Feedback[T]` annotation | [§9](pypeline_guide.md#feedback-wires-feedbackt) |
| `#pragma FUNC_WIRES func` | `@wires` decorator on the function | [§18](pypeline_guide.md#just-wires-synthesis-hint-wires) |
| `#pragma AUTOPIPELINE` on a call | `result = autopipeline(func(args))` | [§15](pypeline_guide.md#tool-chosen-implementation-autopipeline-and-autofsm) |
| `#pragma INST_ARRAY` | factory function + Python list/loop | [§12](pypeline_guide.md#parametric-hardware-with-factory-functions) |
| `#pragma MULTI_CYCLE N` | `MC = MULTI_CYCLE[N]` | [§16](pypeline_guide.md#multi-cycle-paths-multi_cycle) |

### FUNC_WIRES

```c
// PipelineC
my_out_t my_func(my_in_t x) { ... }
#pragma FUNC_WIRES my_func
```
```python
# pypeline
@wires
def my_func(x: my_in_t) -> my_out_t:
    ...
```

### AUTOPIPELINE

```c
// PipelineC — inside a MAIN or function
#pragma AUTOPIPELINE
result = my_expensive_func(input);
```
```python
# pypeline
result = autopipeline(my_expensive_func(input))
# or with explicit stage count:
result = autopipeline(my_expensive_func(input), 4)
```

---

## 12. Parametric / Generic Hardware

PipelineC achieves generics by `#define`-ing a type then `#include`-ing a file multiple
times, or by using the `PPCAT` token-pasting macro to build instance names dynamically.
pypeline uses ordinary Python factory functions.

```c
// PipelineC — generic adder via repeated include
#define T uint32_t
#include "generic_adder.h"
#undef T
#define T uint16_t
#include "generic_adder.h"
#undef T
```
```python
# pypeline — factory function
def make_adder(T):
    @hw_func
    def adder(a: T, b: T) -> T:
        return a + b
    return adder

adder_u32 = make_adder(uint32_t)
adder_u16 = make_adder(uint16_t)
```

`PPCAT(INST_NAME, _pipeline)` style dynamic naming → simply use the variable names
returned by the factory.

See [pypeline_guide.md §12](pypeline_guide.md#parametric-hardware-with-factory-functions).

---

## 13. Not Yet Supported

The following PipelineC features do not yet have a pypeline equivalent.

| PipelineC feature | Notes |
|---|---|
| Multiple clock domains (`MAIN_MHZ_GROUP`, `#pragma ASYNC_WIRE`) | Not supported — `make_clock(mhz)` (§11 above) covers a single named/generated clock, but a tagged clock must match some `@MAIN`'s rate exactly; clock groups (distinct domains at the same rate) and async wires are not supported |
| Async clock-crossing FIFOs (`GLOBAL_STREAM_FIFO` across clock domains) | Not supported |
| Dual-port stream RAM (`DECL_STREAM_RAM_DP_W_R_1`) | Use `vhdl()` passthrough |
| Multiple / early `return` statements (returning from inside an `if` branch) | Not supported — a pypeline function has exactly one `return`, which must be the final top-level statement; restructure to assign a result variable in each branch and return it once at the end (see [pypeline_guide.md §6](pypeline_guide.md#your-first-hardware-function)) |
| `Reg[char_t[N]] = <initializer>` (register power-on value for a char array, e.g. equivalent of C's `static char name[16] = "boot";`) | Not supported for hardware elaboration — raises `ElaborationError`. `Reg[char_t[N]]` with no initializer (zero-init) works normally. See [pypeline_DESIGN.md](pypeline_DESIGN.md#char-array-support) |
| C-style casts to `char_t`, an `@enum` type, or an array type | Not supported (scalar int↔int and struct/`@interface`-half casts are — see [§3d Casting](#3d-casting)) |

See also the [Limitations](pypeline_guide.md#limitations--not-yet-supported) section
of the pypeline guide.

---

## 14. Debug Output: printf / sim_print

PipelineC's `printf(fmt, ...)` maps to pypeline's `sim_print(...)` — both print during
simulation and elaborate to a real VHDL console `write(output, ...)` statement:

```c
// PipelineC
printf("n=%d hex=%X\n", n, n);
```

```python
# pypeline
from pypeline import sim_print

sim_print(f"n={n} hex={hex(n)}")
```

Note two differences from C's `printf`:

- **Syntax.** pypeline uses ordinary Python interpolation (an f-string, one argument) instead
  of a separate format-string-plus-`%`-args form — `printf("...%d...", n)` isn't valid
  Python, so it isn't `sim_print`'s syntax either.
- **Newline.** C's `printf` requires an explicit `\n`; `sim_print` appends one automatically,
  like real Python `print()`.

`%s` pairs with `char_t[N]` (see [§3f](#3f-char-array-string-types)) via plain `{name}`
interpolation — `sim_print(f"name={name}")` — auto-inferred from the argument's type, same
as plain integers. A single `char_t` still needs `chr(...)`, since a bare `{ch}` is
ambiguous between a number and a character (see
[PY_TO_LOGIC_DESIGN.md](PY_TO_LOGIC_DESIGN.md#sim_print--printf-style-console-output)).

`%f` has no pypeline equivalent yet — pypeline has no native Python-float representation for
its bit-packed float type.

See [pypeline_guide.md](pypeline_guide.md#sim_print--printf-style-console-output) and
[PY_TO_LOGIC_DESIGN.md](PY_TO_LOGIC_DESIGN.md#sim_print--printf-style-console-output) for
full details.
