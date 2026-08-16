# Pypeline HDL

[Pypeline](pypeline_guide.md) is the Python front end for [PypelineC](../README.md).

We are happy to help, reach out: [PipelineC Discord](https://discord.gg/Aupm3DDrK2), [Mastodon](http://fosstodon.org/@pypelinec), [BlueSky](https://bsky.app/profile/pypelinec.bsky.social), [Discussions](https://github.com/JulianKemmerer/PipelineC/discussions) :)

# Quick Start

Clone the repo:
```
git clone https://github.com/JulianKemmerer/PipelineC.git
cd PipelineC/
```

Try simulating the [blinking an LED](../examples/pypeline/blink.py) demo. This runs in
Pypeline's native Python simulator, so it works right away for most people with no
toolchain setup at all:
```
./src/pypelinec examples/pypeline/blink.py --sim --comb --run 3
```

Example console output:

```
Clock:  0
counter=0 led=0

Clock:  1
counter=1 led=0

Clock:  2
counter=2 led=0
```

That's `blink.py`:
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

You can also generate the design's real VHDL without running any synthesis tool:
```
./src/pypelinec examples/pypeline/blink.py --comb --no_synth
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

## Set up your tools

Depending on what you're doing, 'install' could be as as simple as adding `pypelinec` to your `PATH` for convenience:
```
export PATH=$PATH:$(pwd)/src
```

For installing/configuring simulation, synthesis, and bitstream generation tools see the wiki's [Set up your tools](https://github.com/JulianKemmerer/PipelineC/wiki/Running-the-Tool) page.

For a more complete, officially-packaged install, the repo also ships a Nix package
(`default.nix`/`nix/package.nix`) that installs a self-contained PyRTL + GHDL + Yosys (+
the Yosys GHDL plugin) toolchain in one step — the same free/open PyRTL+GHDL+Yosys-based
flow tools like [Latchup.app](https://latchup.app) are built around:
```
nix-build default.nix
export PATH=$PATH:$(pwd)/result/bin
pypelinec examples/pypeline/blink.py --comb   # now runs the real PyRTL+GHDL+Yosys flow
```

Vendor toolchains (Vivado/Quartus/Diamond/etc.) still need their own proprietary installs
regardless of which path you take.

## Next Steps

* Read the [Pypeline language guide](pypeline_guide.md). It walks
  through a full worked example ([VGA test pattern](../examples/pypeline/vga_test_pattern.py))
  and then covers every language feature in its own section.
* See the [examples/pypeline](../examples/pypeline) directory for more example code.
* Coming from the C front end? See
  [`docs/pipelinec_to_pypeline.md`](pipelinec_to_pypeline.md) for a pattern-by-pattern
  translation reference.

# Overview

Consider the following generic register + combinatorial logic, compared across Pypeline,
VHDL, and Verilog:

<table>
<tr>
<th>Pypeline</th>
<th>VHDL</th>
<th>Verilog</th>
</tr>
<tr>
<td valign="top">

```python
def some_func_name(input: some_type_t) -> some_type_t:
    the_reg: Reg[some_type_t]

    # ... Do work with 'input', 'the_reg'
    # ... and other variables, functions, etc ...
    the_reg = work(the_reg, input)

    return the_reg
```

</td>
<td valign="top">

```vhdl
-- Combinatorial logic with a storage register
signal the_reg : some_type_t;
signal the_wire : some_type_t;
process(input_wire, the_reg) is -- inputs sync to clk
  variable input_variable: some_type_t;
  variable the_reg_variable : some_type_t;
begin
  input_variable := input_wire;
  the_reg_variable := the_reg;

  -- ... Do work with 'input_variable', 'the_reg_variable'
  -- and other variables, functions, etc and it kinda looks like C ...
  the_reg_variable := work(input_variable, the_reg_variable);

  the_wire <= the_reg_variable;
end process;
the_reg <= the_wire when rising_edge(clk);
output_wire <= the_wire;
```

</td>
<td valign="top">

```sv
// Combinatorial logic with a storage register
some_type_t the_reg;
some_type_t the_wire;
always@(input_wire, the_reg) begin // inputs sync to clk
  some_type_t input_variable;
  some_type_t the_reg_variable;

  input_variable = input_wire;
  the_reg_variable = the_reg;

  // ... Do work with 'input_variable', 'the_reg_variable'
  // and other variables, functions, etc and it kinda looks like C ...
  the_reg_variable = work(input_variable, the_reg_variable);

  the_wire <= the_reg_variable;
end
always_ff@(posedge clk) begin
  the_reg <= the_wire;
end
assign output_wire = the_wire;
```

</td>
</tr>
</table>

<img alt="schematic of generic hdl" src="https://github.com/user-attachments/assets/e68811e2-591f-462d-88e7-22723233f33b" />

Pypeline functions are a single clock domain, rising edge assumed. Function arguments are
input ports, the return value is the output port (both type-annotated). Function bodies are
combinatorial logic dataflow graphs; a `Reg[T]`-annotated local variable is the only thing
that turns a function into a stateful process like the VHDL/Verilog above.

[Is this HLS?](https://github.com/JulianKemmerer/PipelineC/wiki/Is-this-HLS%3F)

Functions = combinatorial logic to be pipelined (a single Python function describes an
N>=0 clock pipeline). Pure functions can be pipelined to 'arbitrary' N>0 clock cycle
pipelines. If a function is marked with [`@MAIN`](pypeline_guide.md#top-level-entry-points)
then its inputs and return value are used for top level input and output ports.

[`Reg[T]`](pypeline_guide.md#registers-regt) local variables = registers. Use a
register and N=0. The function now describes a "stateful function" of combinatorial
logic and registers, think processes in HDL.

'Invocation is instantiation' is the default behavior of function calls. Each function
call location is a new instance of the function's module.

[Global signals](pypeline_guide.md#global-signals) (`Wire[T]`/`Input[T]`/`Output[T]`)
work similar to registers but also can be used as a mechanism for moving data between
functions. Multiple locations can read a global wire but there can only be one instance
of a function that writes to it.

Python isn't a great hardware description language in itself. Some functionality is
provided to bridge the gap between Python and traditional HDLs (see
[Bit Manipulation](pypeline_guide.md#bit-manipulation) and
[Types](pypeline_guide.md#basic-types)).

Pypeline can replace VHDL/Verilog almost entirely. However, if the need arises there
are [hooks for writing arbitrary VHDL](pypeline_guide.md#raw-vhdl-passthrough-vhdl)
instead of Pypeline code.

The Pypeline tool is pure Python other than calls to the synthesis+simulation tools.
See how to setup and [run the tool](https://github.com/JulianKemmerer/PipelineC/wiki/Running-the-Tool).

Pypeline is synthesized into hardware so we can't avoid talking hardware for long.

Hardware modules have input ports. Input ports are function arguments (type-annotated).
Function return statements are the single output port. Do multiple outputs as a
[struct](pypeline_guide.md#basic-types).

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

See the guide's [Limitations / Not Yet Supported](pypeline_guide.md#limitations--not-yet-supported)
section for the current list of known gaps.

## Tools & CLI

## Pure functions can be pipelined!
**Quickly render basic un-pipelined combinatorial logic VHDL:**
```
pypelinec ./examples/pypeline/pipeline.py --comb
```
**To produce a pipeline that meets timing at operating frequency `F`**:

* First [have tools installed](https://github.com/JulianKemmerer/PipelineC/wiki/Running-the-Tool). (or install free [PyRTL](https://ucsbarchlab.github.io/PyRTL/) Python package for experimental ASIC timing models and provide no `PART()`.)
* And then [open and edit](../examples/pypeline/pipeline.py) `pipeline.py` to specify the target frequency and FPGA part:
  * Ex. `@MAIN(F)` says the `my_pipeline` function is a single top level `@MAIN` function intended to run at `F`MHz — see [Top-Level Entry Points](pypeline_guide.md#top-level-entry-points).
  * Ex. `PART("LFE5UM5G-85F-8BG756C")` for `ghdl+yosys+nextpnr` `ECP5U` flow.

* Since `my_pipeline` is a pure function the Pypeline tool will autopipeline the function to meet the target operating frequency.
```
pypelinec ./examples/pypeline/pipeline.py # Default no-arguments autopipelines when possible.
```

**To produce a pipeline of user selected `N` clock cycles** (N+1 total stages) run this command:
```
pypelinec ./examples/pypeline/pipeline.py --coarse --sweep --start N --stop N
```

**For fast iteration**, to see a pipelined result quickly without waiting on
sweep synthesis (timing is not verified -- raise the `@MAIN` mhz target for
more stages) or on hierarchical delay measurement:
```
pypelinec ./examples/pypeline/pipeline.py --no_sweep --no_hier_syn
```

### VHDL (cocotb+GHDL) simulation: `--cocotb --ghdl`

Passing `--cocotb --ghdl` on the `pypelinec` command line elaborates the design to VHDL
and simulates it with a real GHDL simulator via cocotb, instead of using the native
Python simulator. Use this when you need cycle-accurate confirmation against the actual
generated VHDL (e.g. verifying a `vhdl()` passthrough or a hand-written `@sim_model`
really matches its hardware), or when a design uses a feature the native simulator
doesn't model yet.

### `--out_dir`

`--out_dir <path>` sets the build/simulation output directory explicitly (VHDL, logs,
timing-params caches, etc.), instead of a freshly generated default directory. Pointing
two separate invocations at the same `--out_dir` lets a later run reuse an earlier run's
warm sweep/build results instead of paying for them again — this is how
`pypeline_sim_debug.py` (below) gets both its native and VHDL runs to agree on the same
discovered pipeline latencies.

### `pypeline_sim_debug.py` — native-vs-VHDL cycle diff tool

`src/pypeline_sim_debug.py` runs a testbench both ways — native sim, and `--cocotb
--ghdl` VHDL sim — and diffs their `sim_print(..., debug=True)` output cycle by cycle.
It exists to localize *cycle-timing* mismatches (data correct, but arriving on the
wrong clock cycle) that ordinary `sim_assert`s don't catch. Invoke it exactly like
`pypelinec ... --sim ...`; it adds `--cocotb --ghdl` itself for the VHDL run:

```
pypeline_sim_debug.py ./src/my_design_tb.py --sim --comb --run all   # comb compare
pypeline_sim_debug.py ./src/my_design_tb.py --sim --run all          # PIPELINED compare
```

`--comb` runs compare zero-latency native sim against comb VHDL, concurrently. Without
`--comb`, the tool first does a single build-only pass into a shared `out_dir`, then
points both the native and VHDL `--sim` invocations at that same warm `out_dir` so both
converge on the same discovered pipeline latencies — see
[`docs/pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md)'s "Pipelined native sim" section
for the warm-`out_dir` build orchestration and convergence guarantees.

There are three constraints on a pipelined (non-`--comb`) compare:
- **Valid-gate every probe.** VHDL pipeline registers read `'U'` during warm-up; native
  delay lines start at typed zeros — an un-gated data print can never match there. Gate
  on a valid bit carried through the same pipeline.
- **Probe from stateful code, not inside the pipelined comb.** A print inside a
  pipelined region fires at stage-0 timing natively but at its retimed stage in VHDL.
- **Bundle co-timed outputs of a pipelined pure MAIN into one struct wire.** Native
  delays every wire a pipelined MAIN writes by that MAIN's total latency, but VHDL
  emerges each *separate* wire at its own cone depth — so a shallow side wire alongside
  a deep one diverges. Fields of one struct wire emerge together in both and match.

The tool reports the first cycle where the two runs' debug-tagged lines differ, plus
the total mismatch count, and exits non-zero on any mismatch. Full raw stdout from both
runs is always saved to `<out_dir>/native.log` and `<out_dir>/vhdl.log` (`--out_dir`
defaults to a fresh `./pypeline_sim_debug_out_<design>_<pid>` directory if not given).
On mismatch, the tool also prints a side-by-side dump of both runs' debug-tagged lines
for `--context` cycles before and after the first divergence (default 10; pass
`--context 0` to suppress it). See the guide's
[`sim_print(..., debug=True)`](pypeline_guide.md#sim_print-debugtrue--tagged-prints-for-pypeline_sim_debugpy)
section for how to tag prints for this tool.