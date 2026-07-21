# Pypeline HDL

Pypeline is the Python front end for [PypelineC](../README.md).

We are happy to help, reach out: [PipelineC Discord](https://discord.gg/Aupm3DDrK2), [Mastodon](http://fosstodon.org/@pypelinec), [BlueSky](https://bsky.app/profile/pypelinec.bsky.social), [Discussions](https://github.com/JulianKemmerer/PipelineC/discussions) :)

# Quick Start

Clone the repo, add its `src/` and `include/pypeline` directories to your
`PYTHONPATH`, and add `src/` to your `PATH` for the `pypelinec` command:
```
git clone https://github.com/JulianKemmerer/PipelineC.git
cd PipelineC/
export PYTHONPATH=$PYTHONPATH:$(pwd)/src:$(pwd)/include/pypeline
export PATH=$PATH:$(pwd)/src
```
Any Python file can now do `from pypeline import *` and run native Python based simulations.

Typical [blinking an LED](../examples/pypeline/blink.py) code:
```python
from pypeline import *

# 'Called'/'Executing' every 40ns (25MHz)
@MAIN(25.0)
def blink() -> uint1_t:
    # Count to 25000000 iterations * 40ns each = 1 sec
    counter: Reg[uint32_t] = 0

    # LED on/off state
    led: Reg[uint1_t] = 0

    sim_print(f"counter={counter} led={led}")

    # If reached 1 second
    if counter == (25000000 - 1):
        led = ~led  # Toggle led
        counter = 0  # Reset counter
    else:
        counter = counter + 1  # one 40ns increment

    return led
```

```
# Simulate in native Python sim - no toolchain needed
pypelinec examples/pypeline/blink.py --sim --comb --run 10
```

Example console output:

```
Clock:  0
counter=0 led=0

Clock:  1
counter=1 led=0

Clock:  2
counter=2 led=0
...
```

```
# Build/synthesize for real hardware
pypelinec ./examples/pypeline/blink.py
```

Example console output: (final product is VHDL/Verilog files)

```
Output directory: ./pipelinec_output_blink.py_304105
...
...
...
Output VHDL files: ./pipelinec_output_blink.py_304105/vhdl_files.txt
```

The generated top-level VHDL entity (`top.vhd`) has one input clock (named from the
`@MAIN(25.0)` frequency) and one output port (from `blink`'s `-> uint1_t` return value):
```vhdl
entity top is
port(
  -- All clocks
  clk_25p0 : in std_logic;

  -- IO for each main func
  blink_return_output : out unsigned(0 downto 0)
);
end top;
```

## Pure functions can be pipelined!
**Quickly render basic un-pipelined combinatorial logic VHDL:**
```
pypelinec ./examples/pypeline/pipeline.py --comb
```
**To produce a pipeline that meets timing at operating frequency `F`**:

* First [have tools installed](https://github.com/JulianKemmerer/PipelineC/wiki/Running-the-Tool). (or install free [PyRTL](https://ucsbarchlab.github.io/PyRTL/) Python package for experimental ASIC timing models and provide no `PART()`.)
* And then [open and edit](../examples/pypeline/pipeline.py) `pipeline.py` to specify the target frequency and FPGA part:
  * Ex. `@MAIN(F)` says the `my_pipeline` function is a single top level `@MAIN` function intended to run at `F`MHz — see [Top-Level Entry Points](pypeline_guide.md#5-top-level-entry-points).
  * Ex. `PART("LFE5UM5G-85F-8BG756C")` for `ghdl+yosys+nextpnr` `ECP5U` flow.

* Since `my_pipeline` is a pure function the Pypeline tool will autopipeline the function to meet the target operating frequency.
```
pypelinec ./examples/pypeline/pipeline.py # Default no-arguments autopipelines when possible.
```

**To produce a pipeline of user selected `N` clock cycles** (N+1 total stages) run this command:
```
pypelinec ./examples/pypeline/pipeline.py --coarse --sweep --start N --stop N
```


# Overview

* Read the [Pypeline language guide](pypeline_guide.md) — start to finish, it walks
  through a full worked example ([VGA test pattern](../examples/pypeline/vga_test_pattern.py))
  and then covers every language feature in its own section.
* [Set up your tools](https://github.com/JulianKemmerer/PipelineC/wiki/Running-the-Tool)
  for simulation, synthesis, and bitstream generation. (Native Python simulation needs
  no toolchain at all — see the guide's [Simulation](pypeline_guide.md#4-simulation)
  section.)
* See the [examples/pypeline](../examples/pypeline) directory for more code, and
  [include/pypeline](../include/pypeline) for the reusable library (VGA, DSP/FIR,
  AXI-Stream, fixed/floating point, board support, etc).

[Is this HLS?](https://github.com/JulianKemmerer/PipelineC/wiki/Is-this-HLS%3F)

Functions = combinatorial logic to be pipelined (a single Python function describes an
N>=0 clock pipeline). Pure functions can be pipelined to 'arbitrary' N>0 clock cycle
pipelines. If a function is marked with [`@MAIN`](pypeline_guide.md#5-top-level-entry-points)
then its inputs and return value are used for top level input and output ports.

[`Reg[T]`](pypeline_guide.md#8-registers-regt) local variables = registers. Use a
register and N=0. The function now describes a "stateful function" of combinatorial
logic and registers, think processes in HDL. Generally speaking, isolate and minimize
your use of registers for higher operating frequencies.

'Invocation is instantiation' is the default behavior of function calls. Each function
call location is a new instance of the function's module.

[Global signals](pypeline_guide.md#14-global-signals) (`Wire[T]`/`Input[T]`/`Output[T]`)
work similar to registers but also can be used as a mechanism for moving data between
functions. Multiple locations can read a global wire but there can only be one instance
of a function that writes to it.

Complex 'clock-by-clock' derived state machines can be written directly, clock cycle by
clock cycle, using `Reg[T]` the same way you would in a traditional HDL process.

Python isn't a great hardware description language in itself. Some functionality is
provided to bridge the gap between Python and traditional HDLs (see
[Bit Manipulation](pypeline_guide.md#10-bit-manipulation) and
[Types](pypeline_guide.md#11-types)).

Pypeline can replace VHDL/Verilog almost entirely. However, if the need arises there
are [hooks for writing arbitrary VHDL](pypeline_guide.md#17-raw-vhdl-passthrough-vhdl)
instead of Pypeline code.

The Pypeline tool is pure Python other than calls to the synthesis+simulation tools.
See how to setup and [run the tool](https://github.com/JulianKemmerer/PipelineC/wiki/Running-the-Tool).

Pypeline is synthesized into hardware so we can't avoid talking hardware for long.

Hardware modules have input ports. Input ports are function arguments (type-annotated).
Function return statements are the single output port. Do multiple outputs as a
[struct](pypeline_guide.md#11-types).

Each function describes comb. logic (possibly to be auto-pipelined) that exists in a
single clock domain. Functions marked `@MAIN` are single instance top level design
modules (i.e. where you can have board connections). The clock domain for most
functions is inferred from use within frequency-specified `@MAIN` functions.

The comb. logic body of a Pypeline function is synthesized to a hardware pipeline. That
is, a sequential series of combinatorial stages of logic separated by registers.

```python
# Simple example of math pipeline
def main(x1: float, x2: float, y1: float, y2: float) -> float:
    x_sum: float = x1 + x2
    y_sum: float = y1 + y2
    return x_sum + y_sum
```
The above example instantiates 3 floating point adders. Two in parallel, and a third
for the return. You can think of the Pypeline main function as executing over and over
again in a loop, each time getting a new set of inputs. The body of Pypeline functions
are data flow graphs.

**Examples:** See the [examples/pypeline](../examples/pypeline) directory.

Pypeline can generate a hardware pipeline for almost any operating frequency by
increasing the depth/latency of the pipeline. All functions (ex. including floating
point operations) are broken down into subpipelines thus allowing for fine grained
control of synthesis results.

See the guide's [Limitations / Not Yet Supported](pypeline_guide.md#26-limitations--not-yet-supported)
section for the current list of known gaps.
