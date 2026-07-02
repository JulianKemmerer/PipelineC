# PipelineC → pypeline Translation Guide

This guide helps you translate existing PipelineC (C-based HDL) designs to
[pypeline](pypeline_guide.md) (the Python front-end for PipelineC).
It is organised around common PipelineC patterns, showing the equivalent pypeline Python
side-by-side. For the full pypeline API reference see [pypeline_guide.md](pypeline_guide.md).

PipelineC documentation: [GitHub wiki](https://github.com/JulianKemmerer/PipelineC/wiki)

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
See [pypeline_guide.md §5](pypeline_guide.md#5-top-level-entry-points).

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
mux tree. See [pypeline_guide.md §11](pypeline_guide.md#11-types).

### 3d. Enum Types

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

See [pypeline_guide.md §3d](pypeline_guide.md#3d-enum-types) for the full API.

### 3e. Char Array (String) Types

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

In simulation, use `str_to_char_array(s, n)` / `char_array_to_str(value)` to convert
to/from Python `str` (a `char_t[N]` sim value is a plain list, like any other array — see
[pypeline_guide.md §11](pypeline_guide.md#11-types)).

`Reg[char_t[N]]` currently only supports zero-init (no `=` initializer) — see
[pypeline_DESIGN.md](pypeline_DESIGN.md#char-array-support) for the known limitation.

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

See [pypeline_guide.md §5](pypeline_guide.md#5-top-level-entry-points).

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

See [pypeline_guide.md §14](pypeline_guide.md#14-global-signals).

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

See [pypeline_guide.md §8](pypeline_guide.md#8-registers-regt).

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
initializer. See [pypeline_guide.md §9](pypeline_guide.md#9-feedback-wires-feedbackt).

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

See [pypeline_guide.md §15](pypeline_guide.md#15-forcing-pipelining-autopipeline).

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
    name_in_ready = result.ready_for_stream_in
```

See [pypeline_guide.md §24](pypeline_guide.md#24-pipelined-stream-wrappers-make_stream_pipeline).

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

See [pypeline_guide.md §23](pypeline_guide.md#23-fifos-make_stream_fifo).

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

See [pypeline_guide.md §16](pypeline_guide.md#16-multi-cycle-paths-multi_cycle).

---

## 9. Bit Manipulation

Most bitwise operators are identical. The differences are in packing/unpacking helpers.

| PipelineC | pypeline | Notes |
|---|---|---|
| `>>`, `<<`, `&`, `\|`, `^`, `~` | same operators | |
| `uint8_uint8(b1, b0)` | `concat(b1, b0)` | first arg = MSB |
| `uint16_uint16(msb, lsb)` | `concat(msb, lsb)` | |
| `rotl32_16(x)` | `rotl(x, 16, 32)` | `rotl(value, amount, width)` |
| `rotr32_8(x)` | `rotr(x, 8, 32)` | |
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

See [pypeline_guide.md §10](pypeline_guide.md#10-bit-manipulation).

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

See [pypeline_guide.md §21](pypeline_guide.md#21-validready-streams-stream_t) and
[§22](pypeline_guide.md#22-axi-stream-axis_t).

---

## 11. Synthesis Pragmas

Most PipelineC `#pragma` annotations have a direct pypeline equivalent.

| PipelineC | pypeline | Reference |
|---|---|---|
| `#pragma PART "..."` | `PART("...")` at module level | [§5](pypeline_guide.md#5-top-level-entry-points) |
| `#pragma MAIN func` | `@MAIN` decorator | [§5](pypeline_guide.md#5-top-level-entry-points) |
| `#pragma MAIN_MHZ func 100.0` | `@MAIN(100.0)` decorator | [§5](pypeline_guide.md#5-top-level-entry-points) |
| `#pragma FEEDBACK x` | `x: Feedback[T]` annotation | [§9](pypeline_guide.md#9-feedback-wires-feedbackt) |
| `#pragma FUNC_WIRES func` | `@wires` decorator on the function | [§18](pypeline_guide.md#18-just-wires-synthesis-hint-wires) |
| `#pragma AUTOPIPELINE` on a call | `result = autopipeline(func(args))` | [§15](pypeline_guide.md#15-forcing-pipelining-autopipeline) |
| `#pragma INST_ARRAY` | factory function + Python list/loop | [§12](pypeline_guide.md#12-parametric-hardware-with-factory-functions) |
| `#pragma MULTI_CYCLE N` | `MC = MULTI_CYCLE[N]` | [§16](pypeline_guide.md#16-multi-cycle-paths-multi_cycle) |

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

See [pypeline_guide.md §12](pypeline_guide.md#12-parametric-hardware-with-factory-functions).

---

## 13. Not Yet Supported

The following PipelineC features do not yet have a pypeline equivalent.

| PipelineC feature | Notes |
|---|---|
| Multiple clock domains (`MAIN_MHZ_GROUP`, `#pragma ASYNC_WIRE`) | Not supported |
| Async clock-crossing FIFOs (`GLOBAL_STREAM_FIFO` across clock domains) | Not supported |
| Dual-port stream RAM (`DECL_STREAM_RAM_DP_W_R_1`) | Use `vhdl()` passthrough |
| `CLK_MHZ` annotation for non-MAIN peripheral clocks | Not supported |
| Simulation of `vhdl()`-based primitives | `make_stream_fifo`, `make_stream_pipeline`, `make_valid_ready_mcp` raise `NotImplementedError` in simulation; synthesise normally via `pipelinec` |
| Multiple / early `return` statements (returning from inside an `if` branch) | Not supported — a pypeline function has exactly one `return`, which must be the final top-level statement; restructure to assign a result variable in each branch and return it once at the end (see [pypeline_guide.md §6](pypeline_guide.md#6-your-first-hardware-function)) |
| `Reg[char_t[N]] = <initializer>` (register power-on value for a char array, e.g. equivalent of C's `static char name[16] = "boot";`) | Not supported for hardware elaboration — raises `ElaborationError`. `Reg[char_t[N]]` with no initializer (zero-init) works normally. See [pypeline_DESIGN.md](pypeline_DESIGN.md#char-array-support) |

See also the [Limitations](pypeline_guide.md#25-limitations--not-yet-supported) section
of the pypeline guide.
