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

Vendor toolchains (Vivado/Quartus/Diamond/etc.) still need their own proprietary installs
regardless of which path you take.

### Nix

For a more officially-packaged install currently limited to open source tools, the repo provides a Nix package
(`default.nix`/`nix/package.nix`). It installs a self-contained PyRTL + GHDL + Yosys toolchain in one step, the same flow tools like [Latchup.app](https://latchup.app) are built around:
```
nix-build default.nix
export PATH=$PATH:$(pwd)/result/bin
pypelinec examples/pypeline/blink.py --comb   # runs the real PyRTL+GHDL+Yosys flow
# can specify --syn_tool device_models (or source code PART('sky130')) to use an alternative ASIC timing model instead
```

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

## Direct RTL semantics

The shorter Pypeline example above describes the same hardware without an event-driven
process model. A typed function is a hardware module: arguments are input ports, its
return value is an output port, and ordinary local variables are combinational wires.
A local annotated with [`Reg[T]`](pypeline_guide.md#registers-regt) is explicit stored
state. Pypeline assumes rising-edge operation within a single clock domain, so there are
no sensitivity lists, blocking/nonblocking assignment choices, or separate templates for
combinational and registered logic.

The [Python-versus-hardware execution
model](pypeline_guide.md#python-vs-hardware-execution) defines how each construct maps to
hardware: an `if` on a hardware value becomes a MUX, compile-time loops are unrolled,
register writes commit on a clock edge, and every call site creates a distinct module instance.
Functions marked [`@MAIN`](pypeline_guide.md#top-level-entry-points) become single-instance
top-level modules whose typed arguments and return value define FPGA ports.

## Hierarchy and interconnect by composition

“Invocation is instantiation”: [calling a hardware
function](pypeline_guide.md#calling-functions) creates and connects a module instance.
Functions can call functions to any depth, using typed values and structs instead of
repeating component declarations and one signal assignment per port. Multiple outputs
are grouped in [struct types](pypeline_guide.md#struct-types), while
[`Wire[T]`, `Input[T]`, and `Output[T]` global
signals](pypeline_guide.md#global-signals) connect logic that is not naturally expressed
as feed-forward function calls.

Real buses often carry signals in both directions. Pypeline's
[`@interface`](pypeline_guide.md#bidirectional-ports-interface) associates forward fields
such as payload and valid with reverse fields such as ready or credit, preserving their
direction as the two halves of one typed port. For straight-line composition,
[interface functions](pypeline_guide.md#interface-functions-write-feedforward-get-the-reverse-wired)
let the source describe the forward dataflow while Pypeline generates the reverse-path
wiring.

## Parameterized, reusable hardware

A Pypeline design file is also a regular Python module. Module-level code executes at
elaboration time, so ordinary Python can compute constants, inspect types, build lookup
tables, and create specialized hardware. [Factory
functions](pypeline_guide.md#parametric-hardware-with-factory-functions) parameterize
functions and compound types by widths, element types, counts, or configuration values;
each specialized hardware function receives its own correctly typed VHDL entity.
Libraries can also define [custom operators](pypeline_guide.md#custom-operators), allowing
a reusable type to carry an implementation rather than forcing every design to
reconstruct it from low-level wires.

This elaboration model goes beyond a fixed set of HDL `generate` constructs: Python code
can define new hardware abstractions, and those abstractions compose with the same
functions, structs, arrays, streams, and interfaces used by hand-written Pypeline logic.

## Automatic implementation with visible hardware

Pure, feedback-free functions describe dataflow that Pypeline can transform into a
hardware pipeline: combinational stages separated by inserted registers.

```python
# Simple example of math pipeline
def main(x1: float, x2: float, y1: float, y2: float) -> float:
    x_sum: float = x1 + x2
    y_sum: float = y1 + y2
    return x_sum + y_sum
```
The above example instantiates 3 floating point adders. Two in parallel, and a third
for the return. The function behaves as a continuously active dataflow graph, accepting
new inputs as the pipeline permits rather than running like a software subroutine.

The [automatic implementation
features](pypeline_guide.md#automatic-hls-like-implementation) can insert pipeline stages
to meet a clock target or select a multi-cycle implementation. Experimental transforms
can optimize combinational area or delay and explore resource-shared FSM implementations.
The chosen latency remains visible to the design so handshakes and surrounding storage
can adapt to the result. This keeps cycles and interfaces explicit while moving
repetitive implementation search into the compiler.

## Conventional output and incremental adoption

Pypeline resolves factories, parameterized types, and interface composition during its
own elaboration, rather than requiring every downstream EDA tool to implement equivalent
advanced HDL features. It then emits human-readable VHDL, keeping generated designs
inside established FPGA synthesis and HDL simulation flows. Its native Python simulator
supports fast iteration, while [cocotb with GHDL](pypeline_guide.md#simulation) can check
the actual generated VHDL. Existing blocks and vendor primitives can be integrated with the
[raw VHDL passthrough](pypeline_guide.md#raw-vhdl-passthrough-vhdl), so adopting Pypeline
does not require rewriting every block at once.

See the [examples](../examples/pypeline), the complete [language
guide](pypeline_guide.md), and the guide's [Limitations / Not Yet
Supported](pypeline_guide.md#limitations--not-yet-supported) section. In particular,
Pypeline currently describes each function in one clock domain and does not yet support
multiple clock domains or asynchronous clock crossings.

## Tools & CLI

## Pure functions can be pipelined!
**Quickly render basic un-pipelined combinatorial logic VHDL:**
```
pypelinec ./examples/pypeline/pipeline.py --comb
```
**To produce a pipeline that meets timing at operating frequency `F`**:

* First [have tools installed](https://github.com/JulianKemmerer/PipelineC/wiki/Running-the-Tool).
  * Or use `PART("sky130")` / `--syn_tool device_models` to use a custom internal ASIC timing model.
* And then [open and edit](../examples/pypeline/pipeline.py) `pipeline.py` to specify the target frequency and FPGA part:
  * Ex. `@MAIN(F)` says the `my_pipeline` function is a single top level `@MAIN` function intended to run at `F`MHz — see [Top-Level Entry Points](pypeline_guide.md#top-level-entry-points).
  * Ex. `PART("LFE5UM5G-85F-8BG756C")` for `ghdl+yosys+nextpnr` `ECP5U` flow.
  * Or name the tool instead and let it pick its own default part: `SYN_TOOL("quartus")` in the source, or `--syn_tool quartus` / `--part 5CEBA4F23C8` on the command line — see [FPGA target device](pypeline_guide.md#fpga-target-device).

* Since `my_pipeline` is a pure function the Pypeline tool will auto-pipeline the function to meet the target operating frequency.
```
pypelinec ./examples/pypeline/pipeline.py # Default no-arguments auto-pipelines when possible.
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
timing-params caches, etc.), instead of a freshly generated default directory.

- **Reusing a warm directory.** A later invocation pointed at the same `--out_dir`
  reuses the earlier run's warm sweep/build results instead of paying for them again.
  So does an invocation pointed at a copy of that directory.
- **One process at a time.** Never run two invocations in one `--out_dir` at the same
  time. To run several from the same warm results, give each its own copy.
- **Example.** This is how `pypeline_sim_debug.py` (below) gets its native and VHDL
  runs to agree on the same discovered pipeline latencies.

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
`--comb`, the tool first does a single build-only pass into `<out_dir>/build`, then
runs the native and VHDL `--sim` invocations concurrently, each in its own copy of that
warm directory (`<out_dir>/native`, `<out_dir>/vhdl`), so both converge on the same
discovered pipeline latencies — see
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
