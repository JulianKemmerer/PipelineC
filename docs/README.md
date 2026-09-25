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

## Next Steps

Depending on what you're doing, 'install' could be as as simple as adding `pypelinec` to your `PATH` for convenience:
```
export PATH=$PATH:$(pwd)/src
```

Vendor toolchains (Vivado/Quartus/Diamond/etc.) still need their own proprietary installs
regardless of which path you take.

* Read the [Pypeline language guide](pypeline_guide.md). It walks
  through a full worked example ([VGA test pattern](../examples/pypeline/vga_test_pattern.py))
  and then covers every language feature in its own section.
* See the [examples/pypeline](../examples/pypeline) directory for more example code.
* [Install your toolchains.](#set-up-your-tools)
* Putting a design on hardware for the first time? See
  [Dev Board Setup](https://github.com/JulianKemmerer/PipelineC/wiki/Dev-Board-Setup).
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

This section owns tool invocation and generated artifacts. Source syntax and semantics
belong in the [Pypeline HDL Language Guide](pypeline_guide.md).

### Common workflows

```sh
# Generate combinational VHDL without invoking synthesis
pypelinec examples/pypeline/blink.py --comb --no_synth

# Characterize combinational timing without automatic pipelining
pypelinec examples/pypeline/pipeline.py --comb

# Run timing-driven automatic implementation using source PART/SYN_TOOL/@MAIN settings
pypelinec examples/pypeline/pipeline.py

# Exercise HDL generation and synthesis for a small wrapper
pypelinec design_synth_top.py --comb --syn_tool device_models
```

Run `pypelinec --help` for the complete current option list.

### Automatic pipelining
**Quickly render basic un-pipelined combinatorial logic VHDL:**
```
pypelinec ./examples/pypeline/pipeline.py --comb
```
**To produce a pipeline that meets timing at operating frequency `F`**:

* First [have tools installed](#set-up-your-tools).
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

### Simulation

Use native strict simulation for fast source-level tests, then include at least one
generated-VHDL check for every reusable block. Native simulation cannot expose
VHDL-only identifier restrictions, unknown-value warm-up, raw-VHDL mismatches, or
VHDL integer display overflow.

```sh
# Native source simulation for a fixed number of cycles
pypelinec examples/pypeline/blink.py --sim --comb --run 10

# Run until source calls sim_finish()
pypelinec design_tb.py --sim --comb --run all

# Simulate generated VHDL through cocotb + GHDL
pypelinec design_tb.py --sim --comb --cocotb --ghdl --run all

# Run the language guide's VGA example for one 800x525 frame
pypelinec examples/pypeline/vga_test_pattern.py --sim --comb --run 420000
```

`pypelinec DESIGN.py --sim --run N` simulates the final, possibly automatically
pipelined implementation. Add `--comb` to simulate the source
without running automatic implementation first. With no external simulator selected,
Pypeline uses its native Python simulator in strict, width-accurate mode.

For lower-level native-simulator control:

```sh
python3 src/pypeline_sim.py DESIGN.py --run 1000 --mode strict
```

| Mode | Behavior |
|---|---|
| `strict` (default) | Typed values with masking/sign behavior at every operation and assignment |
| `loose` | Typed `SimVal` values and bit indexing, without arithmetic-width masking |
| `raw` | Plain Python integers for maximum speed; no casting and no reliable bit indexing on arithmetic results |

The direct simulator accepts a numeric cycle count or `all` to run until
`sim_finish()` (subject to its safety cap). `pypelinec --sim` currently always uses
strict mode.

A design's `@initial(sim=True)` / `@final(sim=True)` hooks run once before the first
clock and once after the last, with every simulator (native or cocotb+GHDL, `--comb`
or not). The final hooks run however the run ended, which makes them the place for
end-of-run checks. `@initial(syn=True)` / `@final(syn=True)` hooks run once around a
`pypelinec` build: after the design is imported, and right after the final VHDL is
written (before any `--pins` bitstream step). See
[`@initial` / `@final`](pypeline_guide.md#initial--final--startend-of-run-hooks).

`PYPELINE_SIM_SOFT_OPS` controls whether matcher-registered operators execute their
structural implementation during native simulation. Leave it unset (or set `all`/`1`)
to dispatch every registered operation, use `none`/`0` for the faster built-in
value-equivalent paths, or provide a comma-separated list such as
`NEGATE,LT,LTE,GT,GTE`. Source can make the same choice with
`set_sim_soft_ops(spec)` before simulation; it does not change elaborated hardware.

#### VHDL (cocotb+GHDL) simulation: `--cocotb --ghdl`

Passing `--cocotb --ghdl` on the `pypelinec` command line elaborates the design to VHDL
and simulates it with a real GHDL simulator via cocotb, instead of using the native
Python simulator. Use this when you need cycle-accurate confirmation against the actual
generated VHDL (e.g. verifying a `vhdl()` passthrough or a hand-written `@sim_model`
really matches its hardware), or when a design uses a feature the native simulator
doesn't model yet.

Other simulator/output selectors are `--edaplay`, `--modelsim`, `--cxxrtl`, and
`--verilator`. `--makefile FILE` supplies an existing simulator Makefile;
`--main_cpp FILE` supplies a C++ driver for CXXRTL or Verilator.

For designs with automatic latency, omit `--comb` from both native and generated-VHDL
simulation and reuse or copy a warm output directory so both runs see the same converged
implementation. Pair hand-written `vhdl()` with `@sim_model`; use the cycle-diff tool
below when their timing may disagree.

#### `pypeline_sim_debug.py` — native-vs-VHDL cycle diff tool

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
discovered pipeline latencies. The build is repeated only if installing a discovered
latency changes the realized pipeline shape; both simulator directories are copied from
the same converged build, so native and VHDL compare the same implementation.

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
[`sim_print(..., debug=True)`](pypeline_guide.md#sim_print-debugtrue--tagged-prints)
section for how to tag prints for this tool.

### Output directories: `--out_dir`

`--out_dir <path>` sets the build/simulation output directory explicitly (VHDL, logs,
timing-params caches, etc.), instead of a freshly generated default directory.

- **Reusing a warm directory.** A later invocation pointed at the same `--out_dir`
  reuses the earlier run's warm sweep/build results instead of paying for them again.
  So does an invocation pointed at a copy of that directory.
- **One process at a time.** Never run two invocations in one `--out_dir` at the same
  time. To run several from the same warm results, give each its own copy.
- **Example.** The cycle-diff tool uses separate copies of one warm directory so its
  native and VHDL runs agree on the same discovered pipeline latencies.
- **Resuming.** If a run stops before it finishes, rerun it with the same `--out_dir` to
  pick up where it left off. This helps with large designs and long synthesis sweeps.
- **Stale files.** If you see odd behavior, start again from a fresh output directory
  ([#82](https://github.com/JulianKemmerer/PipelineC/issues/82)). If
  a run was stopped during synthesis, delete the failed run's (tool-specific) synthesis
  log before trying again.
- **Default and layout.** Without `--out_dir`, a new output directory is created inside
  the current one. `built_in/` holds the VHDL for built-in operators and muxes, `<top>/`
  (named by `--top`) holds the final top level, and code from each source file goes in a
  directory named after that file's path. For example, code from
  `examples/pypeline/blink.py` goes in `examples/pypeline/blink.py/`. This layout may
  change ([#183](https://github.com/JulianKemmerer/PipelineC/issues/183),
  [#214](https://github.com/JulianKemmerer/PipelineC/discussions/214)). Use the manifests
  in [Generated files and reports](#generated-files-and-reports) rather than relying on it.

### Build modes and output options

| Option | Meaning |
|---|---|
| *(no mode flag)* | Run the planned timing-driven pipeline sweep for each eligible `@MAIN` with a clock goal |
| `--comb` | Keep the design combinational and run one timing characterization per clock |
| `--no_synth` | Generate combinational HDL without invoking a synthesis backend |
| `--full_hier_syn` | Measure every hierarchy level rather than estimating hierarchy from measured leaves |
| `--no_hier_syn` | Measure primitive leaves only; fastest warm-cache path, but disables fallback when hierarchy estimates are inaccurate |
| `--pipeline_min_effort N` | After timing is met, allow up to N additional full-design runs to reduce register count; zero accepts the first passing result |
| `--mult infer\|fabric` | Infer target multiplier/DSP primitives or force multipliers into fabric logic |
| `--verilog` | Convert the final VHDL top to Verilog through GHDL and Yosys |
| `--yosys_json` | Stop after writing the Yosys JSON netlist |
| `--xo_axis` | Write the packaging script for a Vitis AXI-Stream `.xo` IP |
| `--pins FILE` | Supply the pin-constraint file used for the final implementation (see [Full bitstream builds](#full-bitstream-builds---pins)) |
| `--top NAME` | Change the generated top-level module name from `top` |

`--mux_delay_by_width` and `--no_mux_delay_by_width` force mux timing-cache keys to
include or ignore operand width. The default is backend-dependent: PyRTL uses its
measured width-independent model, while the sky130 device model keys by width.

`-j N` / `--jobs N` limits concurrent synthesis processes. Treat it primarily as a
memory limit: each job is a complete vendor process. Efinity place-and-route has been
observed near 3.7 GB per leaf, so use `-j 1` on a memory-constrained machine.

An implemented netlist with no timing paths is an error, commonly because all logic was
optimized away and no top-level output remains. Mark intentionally path-free source with
`@wires`; otherwise connect an observable output.

### Synthesis backends and target selection

The target is one decision with two inputs. A part can come from source `PART("...")` or
`--part`; a backend can come from source `SYN_TOOL("...")` or `--syn_tool`. Duplicate
settings must agree, and a named backend must be compatible with the part. A backend
named without a part supplies its default part.

| Part/family | `--syn_tool` | Default part | Timing flow |
|---|---|---|---|
| No part | `pyrtl` | none | Generic PyRTL software delay model; default when nothing is selected |
| `xc...` | `vivado`; `xc7...` also `open_tools` | `xc7a35ticsg324-1l` | Vivado, or OpenXC7 open tools when selected |
| `ep...`, `10c...`, `5c...` | `quartus` | `5CEBA4F23C8` | Quartus |
| ECP5 `lfe5u...` | `open_tools` | `LFE5U-85F-6BG381C` | GHDL + Yosys + nextpnr |
| iCE40 `ice...` | `open_tools` or `diamond` | `ICE40UP5K-SG48` | Open tools, or Diamond when selected/available |
| `T8...`, `Ti...` | `efinity` | `Ti60F225` | Efinity |
| `GW...` | `gowin` | `GW2AR-LV18QN88PC8:C` | Gowin |
| `CCGM...` | `cc_tools` | `CCGM1A1` | CologneChip tools |
| `sky130...` | `device_models` | `sky130` | GHDL/Yosys mapping plus internal liberty STA |

Examples:

```sh
pypelinec design.py --syn_tool quartus
pypelinec design.py --part xc7a35ticsg324-1l
pypelinec design.py --part xc7a35tcpg236-1 --syn_tool open_tools
pypelinec design.py --syn_tool device_models
```

`device_models` currently ships only `sky130_fd_sc_hvl` at the
`tt_025C_3v30` corner. It reports a pre-place-and-route estimate and models no
net/interconnect delay; its area and delay results are useful for consistent local
comparisons, not signoff.

### Automatic implementation and sweeps

The default planned sweep places cuts through eligible combinational logic and uses
timing feedback to refine the result. Coarse mode instead treats the design as a single
uniform slicing problem:

```sh
# Search a coarse latency range one cycle at a time
pypelinec design.py --coarse --sweep --start 2 --stop 8

# Write only the first planned placement; timing is not verified
pypelinec design.py --no_sweep
```

`--no_sweep` performs zero sweep synthesis iterations and must never be described as a
timing-passing build. The coarse sweep also has a known limitation on designs with many
1–3-bit leaves at high cut counts: it can fail with an interior zero-bit-stage error;
use the default planned sweep for those designs.

Automatic latency values depend on the workflow. A normal timing-driven build starts
`AUTO_PIPELINE(start_latency=S)` at S, discovers the implemented value, and
re-elaborates until every source read of `.latency` agrees with the hardware. A
non-`--comb` native simulation uses that converged configuration. `--comb`,
`--no_synth`, `--yosys_json`, and direct source simulation do not
discover an unconstrained pipeline or FSM latency: `AUTO_PIPELINE`/`AUTO_FSM` read zero
there unless a fixed pipeline latency applies. `AUTO_MULTI_CYCLE` reads `latency=`, else
`start_latency=`, else one. An automatic RAM without a fixed or selected plan uses its
mandatory one-cycle synchronous baseline. Fixed `AUTO_PIPELINE(latency=N)` and RAM
latencies are honored in every mode.

Automatic features add these controls and reports:

- `AUTO_PIPELINE` and `AUTO_MULTI_CYCLE` participate in the latency feedback pass.
  `sweep_history.json` records the actual cuts, constraints, timing measurements, final
  outcome, and confirmation run. Fixed `latency=` remains fixed; `max_latency=` is a hard
  limit.
- `AUTO_COMB_AREA_OPT` and `AUTO_COMB_DELAY_OPT` write
  `auto_comb_area_opt_report.json` / `auto_comb_delay_opt_report.json` and candidate
  source under `auto_comb_opt_generated/`.
- `AUTO_FSM` writes generated implementations under `auto_fsm_generated/`.
  `--auto_fsm_budget_scale` sets the initial fraction of one clock available to a
  state. `--auto_fsm_no_area_sweep`, `--auto_fsm_abstract_area`,
  `--auto_fsm_sweep_debug`, repeatable `--auto_fsm_open SUBSTR`, repeatable
  `--auto_fsm_unshare SUBSTR=N`, and `--auto_fsm_ctl {auto,v3,v2,onehot}` are
  diagnostic/A-B controls; the defaults perform the normal minimum-area search and
  automatically select a control encoding.
- Auto-pipelined RAM plan search is currently synthesis-supported by the ECP5 open-tools
  flow. Its selected plans also appear in `sweep_history.json`, while
  `auto_pipeline_ram_history.json` records all tried plans, frequencies, resources, and
  the winner.

### Generated files and reports

The output directory contains intermediate sweep shapes as well as the final design.
Consume the explicit manifests and indexes instead of globbing generated directories:

- `vhdl_files.txt` is the authoritative dependency-ordered list of final VHDL sources.
  It is one whitespace-separated line of absolute paths and can be used as a GHDL
  response-file list. Do not compile a directory glob: it can mix incompatible timing
  variants left by sweep iterations.
- `top/top.vhd` is the stable public top after final timing selection.
  `c_structs_pkg.pkg.vhd` contains translated structs, arrays, enums, and conversions;
  `global_wires_pkg.pkg.vhd` contains shared-global records.
- `name_index.log` maps emitted entities, types, helpers, instances, wires, shortened
  names, source paths/lines, generated sources, and pipeline variants back to Pypeline
  source. Use it instead of parsing a generated identifier or timing hash.
- `pypeline_generated_source/` contains navigable Python source for generated interface,
  cast, byte-conversion, and other helper functions.
- `<top>/sweep_history.json` records every whole-design timing iteration and its final
  verified or unverified status.
- `host/pypeline_host_types.py` is a standalone standard-library-only Python module for
  types registered by byte serialization or `host_export(...)`. Copy it beside host
  software; exported structs are namedtuples with `zero()`, `_replace`, `to_bytes`,
  `from_bytes`, and `BYTE_LENGTH`, while exported enums are `IntEnum`s.

Timing-specific generated entities are not a stable integration API. Depend on the
stable top, import record declarations from `c_structs_pkg`, or add a small scalar-port
wrapper when external HDL needs a durable boundary.

### Using the output in an existing project

The simplest and most flexible way to use Pypeline is to add only the generated VHDL to
an existing bitstream build flow. Add the files listed in `vhdl_files.txt`, plus
whatever tool-specific file the backend generates:

| Backend | Generated files to use |
|---|---|
| Xilinx Vivado | `read_vhdl.tcl` |
| Intel Quartus | `pipelinec_top.qip` Quartus IP file |
| Lattice Diamond | `vhdl_files.txt` and the top module's project file |
| GHDL + Yosys + nextpnr | `vhdl_files.txt` and the top module's build script (`.sh`) |
| OpenXC7 | `vhdl_files.txt` and the top build script (GHDL/Yosys + nextpnr-xilinx); a `--pins` build also writes `top.fasm`, `top.frames` and `top.bit` |
| Gowin EDA | `vhdl_files.txt` and the top module's build script (`.tcl`) |
| Efinix Efinity | `vhdl_files.txt`, the top module's build script (`.sh`), and project (`.xml`) |
| Cologne Chip toolchain | `vhdl_files.txt` and the top module's build script (`.sh`) |
| PyRTL models | `vhdl_files.txt` and the top module's build script (`.sh`) |

For example, this Vivado Tcl removes all old Pypeline files from a project and adds the
newly generated VHDL:

```tcl
remove_files /home/user/pipelinec_output/*;
source /home/user/pipelinec_output/read_vhdl.tcl;
```

### Full bitstream builds: `--pins`

Some backends can also run the full build through to bitstream generation. Pass the
pin-constraint file with `--pins`:

* **Gowin EDA**: Pass a `.cst` pin-mapping file. By default the flow writes a `top.fs`
  bitstream to a directory like `<out_dir>/top/impl/pnr/`.
  * Test: `pypelinec ./examples/tool_tests/gowin_bitstream.c --pins ./examples/gowin/blink.cst`
* **OpenXC7**: Pass an `.xdc` pin/IO-standard file, an explicit XC7 part, and
  `--syn_tool open_tools`. The flow runs nextpnr-xilinx, converts its FASM output with
  Project X-Ray, and writes `<out_dir>/top/top.bit`.
  * Test: `pypelinec ./examples/pypeline/blink.py --part xc7a35tcpg236-1 --syn_tool open_tools --pins ./src/tests/pypeline_tests/constraints/openxc7_basys3_blink.xdc`


## Set up your tools

### Requirements

The `pypelinec` tool is pure Python. It only needs extra setup for the synthesis and
simulation tools it calls. You can run it without an FPGA part or any synthesis tool
installed, but then you get no automatic pipelining or timing feedback: only plain
generated VHDL, as in `--comb --no_synth` mode.

Only Linux environments are supported, and a C preprocessor (`cpp`) must be installed.
Native Windows and [Mac](https://github.com/JulianKemmerer/PipelineC/issues/286) support
still needs work. On those systems, run Pypeline and the synthesis/simulation tools inside
a Linux virtual machine or [Windows Subsystem for Linux (WSL)](https://docs.microsoft.com/en-us/windows/wsl/about).

[ghdl](https://github.com/ghdl/ghdl), [yosys](https://github.com/YosysHQ/yosys), and
[ghdl-yosys-plugin](https://github.com/ghdl/ghdl-yosys-plugin) are required for `--verilog`
and `--verilator` support.

### Synthesis tools

Install one or more synthesis tools. Each backend first looks for its executable on the
user `PATH`. If it isn't there, it falls back to the path constant at the top of that
backend's source file. Each entry below has a small smoke-test design under
[`examples/tool_tests/`](../examples/tool_tests). See
[Synthesis backends and target selection](#synthesis-backends-and-target-selection)
for which part selects which tool.

* **Xilinx Vivado**: Finds `vivado` on the `PATH`. Failing that, set the `XILINX_VIVADO`
  environment variable (a path like `/Xilinx/Vivado/2019.2`) or edit the `VIVADO_DIR`
  constant in [VIVADO.py](../src/VIVADO.py).
  * Test: `pypelinec ./examples/tool_tests/vivado.c`
* **Intel Quartus**: Finds `quartus_sh` on the `PATH`, or edit the `QUARTUS_PATH` constant in
  [QUARTUS.py](../src/QUARTUS.py).
  * Test: `pypelinec ./examples/tool_tests/quartus.c`
* **Lattice Diamond**: Finds `diamondc` on the `PATH`, or edit the `DIAMOND_PATH` and
  `DIAMOND_TOOL` constants in [DIAMOND.py](../src/DIAMOND.py).
  * Test: `pypelinec ./examples/tool_tests/diamond.c`
* **GHDL + Yosys + ghdl-yosys-plugin + nextpnr**: The easiest install is the
  [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build). Extract a current build
  and set `OSS_CAD_SUITE` to its root. Without it, Pypeline looks for the executables on
  the `PATH`.
  * **Warning:** Tool versions installed with `apt-get` are likely too old to work. If you
    build the tools yourself, use the latest [ghdl](https://github.com/ghdl/ghdl),
    [yosys](https://github.com/YosysHQ/yosys), and
    [ghdl-yosys-plugin](https://github.com/ghdl/ghdl-yosys-plugin).
    [nextpnr](https://github.com/YosysHQ/nextpnr) is needed for automatic pipelining.
  * Older `ghdl` versions do not support the `IEEE` `float` library.
  * Yosys fails to load the `ghdl` shared library if `ghdl-yosys-plugin` isn't installed.
  * Test: `pypelinec ./examples/tool_tests/open_tools.c`
* **OpenXC7 (open-source Xilinx 7-series flow)**:
  * Set `OSS_CAD_SUITE` to a current
    [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build).
  * Set `OPENXC7` to an OpenXC7 bundle, or edit the `OPENXC7_PATH` default in
    [OPEN_TOOLS.py](../src/OPEN_TOOLS.py):
    * [FPGAwars/OpenXC7 prebuilt releases](https://github.com/FPGAwars/tools-openxc7/releases).
    * [openXC7/toolchain-installer](https://github.com/openXC7/toolchain-installer) for a source build.
    * `OPENXC7_CHIPDB` and `PRJXRAY_DB_DIR` override nonstandard chipdb/database layouts.
    * The chipdb must be the part's own package: `xc7a35tcpg236.bin` for
      `xc7a35tcpg236-1`. To use a chipdb named only by device, such as the
      `xc7a35t.bin` the nextpnr-xilinx README builds, set `OPENXC7_CHIPDB` to that file.
  * Smoke test: `pypelinec ./examples/pypeline/blink.py --part xc7a35tcpg236-1 --syn_tool open_tools --comb`
* **Gowin EDA**: Finds `gw_sh` on the `PATH`, or edit the `GOWIN_PATH` constant in
  [GOWIN.py](../src/GOWIN.py).
  * Test: `pypelinec ./examples/tool_tests/gowin_pipeline.c`
* **Efinix Efinity**: Finds `efx_run.py` on the `PATH`, or edit the `EFINITY_PATH` constant in
  [EFINITY.py](../src/EFINITY.py).
  * Test: `pypelinec ./examples/tool_tests/efinity.c`
* **Cologne Chip toolchain**: Finds `p_r` on the `PATH`, or edit the `CC_TOOLS_PATH` constant
  in [CC_TOOLS.py](../src/CC_TOOLS.py). Either way, Pypeline expects an extracted
  `cc-toolchain` directory from the
  [most recent build](https://www.colognechip.com/programmable-logic/gatemate/gatemate-download).
  * Test: `pypelinec ./examples/tool_tests/cc_tools.c`
* **PyRTL models**: Install the Python packages `pyrtl` and its dependency `pyparsing`. These
  models are the default when no part is specified.
  * Test: `pypelinec ./examples/tool_tests/pyrtl.c`
* **sky130 device models**: Built in. Select them with `--syn_tool device_models` or
  `PART("sky130")`. They use the GHDL/Yosys tools listed above.

### Simulation tools

These are only needed for `--sim` runs (see [Simulation](#simulation)):

* **Native Python**: No install or setup needed. `--sim` with no simulator selected uses
  the native simulator.
* **Modelsim**: Install Modelsim, then put `vsim` on the `PATH` or edit the `MODELSIM_PATH`
  constant in [MODELSIM.py](../src/MODELSIM.py). Use `--modelsim`.
* **Verilator or CXXRTL**: The easiest install is the
  [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) with `OSS_CAD_SUITE` set
  (see above). Without it, Pypeline looks for the executables on the `PATH`. Use
  `--verilator` or `--cxxrtl`.
* **cocotb + GHDL**: Follow the [cocotb install instructions](https://docs.cocotb.org/).
  GHDL is currently the only simulator supported, and `ghdl` must be on the `PATH`. Use
  `--cocotb --ghdl`.

### Nix

For a more officially-packaged install currently limited to open source tools, the repo provides a Nix package
(`default.nix`/`nix/package.nix`). It installs a self-contained PyRTL + GHDL + Yosys toolchain in one step, the same flow tools like [Latchup.app](https://latchup.app) are built around:
```
nix-build default.nix
export PATH=$PATH:$(pwd)/result/bin
pypelinec examples/pypeline/blink.py --comb   # runs the real PyRTL+GHDL+Yosys flow
# can specify --syn_tool device_models (or source code PART('sky130')) to use an alternative ASIC timing model instead
```
