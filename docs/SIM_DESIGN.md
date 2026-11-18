# SIM — simulation dispatch and HDL simulator backends

How `pypelinec --sim` picks a simulator and hands it the build: the native Python
simulator for Pypeline designs, or an external HDL simulator run on the generated VHDL.

- Implementation: [`src/SIM.py`](../src/SIM.py), plus one backend module per HDL
  simulator: [`src/COCOTB.py`](../src/COCOTB.py), [`src/VERILATOR.py`](../src/VERILATOR.py),
  [`src/CXXRTL.py`](../src/CXXRTL.py), [`src/MODELSIM.py`](../src/MODELSIM.py) and
  [`src/EDAPLAY.py`](../src/EDAPLAY.py). This document is their design documentation.
- The native simulator itself (`pypeline.py`'s in-process sim layer and the
  `pypeline_sim.py` multi-MAIN runner): [`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md).
- User-facing simulator setup and flags: [Simulation tools](README.md#simulation-tools)
  and [Other HDL simulators](README.md#other-hdl-simulators) in `docs/README.md`.

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section, if it
> has one, rather than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## Table of Contents

- [1. Who does what](#1-who-does-what)
- [2. Choosing a simulator](#2-choosing-a-simulator)
- [3. When simulation runs](#3-when-simulation-runs)
  - [Simulating built hardware](#simulating-built-hardware)
- [4. The backend contract](#4-the-backend-contract)
- [5. Backends](#5-backends)
  - [cocotb (`COCOTB.py`)](#cocotb-cocotbpy)
  - [Verilator (`VERILATOR.py`)](#verilator-verilatorpy)
  - [CXXRTL (`CXXRTL.py`)](#cxxrtl-cxxrtlpy)
  - [ModelSim (`MODELSIM.py`)](#modelsim-modelsimpy)
  - [EDA Playground (`EDAPLAY.py`)](#eda-playground-edaplaypy)
- [6. Waveforms](#6-waveforms)
  - [What a native waveform holds](#what-a-native-waveform-holds)
  - [Layout of a value](#layout-of-a-value)
  - [Timing](#timing)
  - [The VCD writer and FST](#the-vcd-writer-and-fst)
  - [Limitations](#limitations)
- [7. Import structure](#7-import-structure)
- [8. Tests](#8-tests)

---

## 1. Who does what

| module | role |
|---|---|
| `src/SIM.py` | selects the simulator (`SET_SIM_TOOL`), decides whether a run needs a build (`NATIVE_SIM_SKIPS_BUILD`, `SIM_AT_COMB_STAGE`, `BUILT_HARDWARE_IS_CURRENT`, `SIMULATE_BUILT_HARDWARE`), runs it (`DO_OPTIONAL_SIM`, and `DO_COMB_STAGE_SIM` after a `--comb` build's final files), records what native simulation and the next build's up-to-date check take from a build (`NATIVE_SIM_HARDWARE`, `BUILD_INPUTS`, `WRITE_BUILT_HARDWARE`), gathers what every backend needs (`GET_SIM_GEN_INFO`, `GET_SIM_FILES`, `GET_MAIN_FUNC_LATENCIES`), and checks and writes waveforms (`CHECK_WAVE_ARGS`; native simulation's `WaveRecorder`, see [Waveforms](#6-waveforms)) |
| `src/pypeline_sim.py` | the native simulator, used as `SIM_TOOL` for `.py` designs ([`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md)) |
| `src/COCOTB.py` | cocotb + GHDL on the generated VHDL, with a generated or user Makefile and testbench |
| `src/VERILATOR.py` | GHDL + yosys to Verilog, then Verilator with a generated or user `main.cpp` |
| `src/CXXRTL.py` | GHDL + yosys `write_cxxrtl`, then clang++ with a generated `main.cpp` |
| `src/MODELSIM.py` | a ModelSim project and `.do` script for interactive debug |
| `src/EDAPLAY.py` | copies the VHDL files into one directory for upload to edaplayground.com |

## 2. Choosing a simulator

`SET_SIM_TOOL(cmd_line_args, source_file)` sets the module global `SIM_TOOL` to a module
object, which the rest of `SIM.py` compares by identity (`SIM_TOOL is COCOTB`):

| flag | `SIM_TOOL` |
|---|---|
| `--cocotb` (with `--ghdl`) | `COCOTB` |
| `--verilator` | `VERILATOR` |
| `--cxxrtl` | `CXXRTL` |
| `--modelsim` | `MODELSIM` |
| `--edaplay` | `EDAPLAY` |
| none, `.py` design | `pypeline_sim` (the native simulator) |
| none, `.c` design | `EDAPLAY` (the module default) |

There is no `--native` flag: for a `.py` design, the absence of every other simulator flag
selects the native simulator. `--run N` (or `--run all`) is the cycle count every backend
that runs cycles reads from `args.run`. `--makefile` (cocotb) and `--main_cpp` (Verilator)
replace the generated driver files. `--wave FILE` (and, native only, `--wave_signals`)
records a waveform with the native simulator or cocotb + GHDL; the driver calls
`CHECK_WAVE_ARGS(args)` right after `SET_SIM_TOOL` ([Waveforms](#6-waveforms)).

## 3. When simulation runs

`src/pipelinec` (see [The build driver](SYN_DESIGN.md#the-build-driver-srcpipelinec))
calls `SIM` at four points:

- **Right after tool selection.** `NATIVE_SIM_SKIPS_BUILD(args)` is true when `SIM_TOOL is
  pypeline_sim` and comb simulation was requested (`--sim --comb`, `--sim_comb`, or
  `--no_synth`). The driver then calls `DO_OPTIONAL_SIM` and exits: no VHDL elaboration or
  synthesis happens, exactly like running `pypeline_sim.py` standalone.

  ```
  python3 src/pipelinec my_design.py --sim --run 1000
  ```

  is therefore `python3 src/pypeline_sim.py my_design.py --run 1000` **plus a full build
  first when `--comb` is absent**.
- **Before any build.** The driver takes the run's `BUILD_INPUTS(args, src_file)` and reads
  the `--out_dir`'s `built_hardware.json` (see
  [Simulating built hardware](#simulating-built-hardware)) twice:
  - `BUILT_HARDWARE_IS_CURRENT(build_inputs, args)`: when a plain build (no `--sim`, no
    `--rebuild`) finds the record of this very top from equal inputs, the build is up to
    date and the driver exits;
  - `SIMULATE_BUILT_HARDWARE(args, src_file, build_inputs)`: when it holds another top's
    hardware and this is a native `--sim`, it simulates that hardware and the driver exits.
    Otherwise a build follows, so it removes the record.
- **After a `--comb` build's final files.** `DO_COMB_STAGE_SIM` runs the sim when
  `SIM_AT_COMB_STAGE(args)` is true: for `--sim_comb`, and for a native `--sim` run
  that was degraded to comb because no synthesis tool is installed (zero latency,
  with a warning). The native simulator gets no timing params (zero MAIN latencies;
  a fixed `latency=` call site keeps its own `.latency` delay line); the others get
  the comb build's fixed-latency timing params.
- **After a pipelined build.** A non-`--comb` `--sim` run falls through to the full build
  (path-delay measurement, throughput sweep, AUTO_PIPELINE pin-and-confirm), and the
  simulator starts on the final VHDL, or, for the native simulator, with the built
  latencies emulated. The build exits before simulation if a timing goal was missed.

`DO_OPTIONAL_SIM(do_sim, parser_state, args, multimain_timing_params, source_file)` runs
the selected backend. For an external simulator it also runs a Pypeline design's
`@initial(sim)` / `@final(sim)` hooks around the tool run, catching the `SystemExit` of a
failed cocotb run too; the native simulator runs its hooks inside its own run loop, so
hooks never run twice (see
[`@initial` / `@final`](pypeline_sim_DESIGN.md#initial--final--startend-of-run-hooks)).

**Handing a build to the native simulator.** When `parser_state` and the final timing
params exist, `DO_OPTIONAL_SIM` passes `pypeline_sim.run_sim` what
`NATIVE_SIM_HARDWARE(parser_state, multimain_timing_params)` collects:

- the per-MAIN latencies (`GET_MAIN_FUNC_LATENCIES`, all zeros on the comb path);
- the converged AUTO_PIPELINE latencies (`AUTO_PIPELINE.HARVEST_AUTO_PIPELINE_LATENCIES`;
  divergences are already a fatal driver error, so they are ignored here);
- the RAM plans (`AUTO_PIPELINE.RAM_PLANS_FROM_STATE`);
- the AUTO_FSM schedules the final elaboration read (`pypeline.AUTO_FSM_SCHEDULE_CACHE`);
- for designs with fixed user pipelines, each instance's placements as plain data
  (`_slices`, IO-register flags, exact bit boundaries, delay), so only `run_sim`'s gate
  imports the fixed-pipeline evaluator
  ([Fixed User Pipelines](pypeline_sim_DESIGN.md#fixed-user-pipelines));
- the AUTO_MULTI_CYCLE counts actually constrained
  (`AUTO_MULTI_CYCLE.HARVEST_AUTO_MULTI_CYCLE_NCYCLES`);
- the CLI `--part` / `--syn_tool`.

Before that, `CHECK_PIPELINED_NATIVE_SIM_SUPPORTED` exits with an error, listing
`PIPELINED_NATIVE_SIM_PROBLEMS`, if a pipelined region (a pure `@MAIN` with latency, or an AUTO_PIPELINE call site with latency) uses a
`VOLATILE` global wire in its own body, or any global wire in a function called inside
the region: the native model cannot place those in time. `pypeline._sim_region_for` is
its runtime twin for plain native runs with no build. The native path always runs at the
default `strict` accuracy; `pipelinec` has no equivalent of `pypeline_sim.py`'s `--mode`.

### Simulating built hardware

A testbench is simulated on the hardware built for the design's real top, never on a
build of its own: its constant or `@sim_input` stimulus lets synthesis remove logic, and
a sweep timed on that removes pipeline stages the real design needs (see
[`WARN_UNTIMED_REGIONS`](SWEEP_DESIGN.md#untimed-regions)).

- **The record.** After a synthesizing build of a `.py` design meets timing, the driver
  calls `WRITE_BUILT_HARDWARE`. It writes `<out_dir>/built_hardware.json`
  (`BUILT_HARDWARE_FILE`, format `BUILT_HARDWARE_VERSION`) with:
  - what `NATIVE_SIM_HARDWARE` collects, as JSON: RAM plans as their fields, AUTO_FSM
    schedules reduced to the fields native simulation reads
    (`pypeline.AUTO_FSM_SIM_SCHEDULE_FIELDS`);
  - the top it built;
  - `PY_TO_LOGIC.DESIGN_SOURCE_HASHES()` of every source the build read;
  - its design parameter values;
  - `PIPELINED_NATIVE_SIM_PROBLEMS`, so a later simulation refuses what this one would;
  - `goal_mode`: `"pnr"` or `"syn"`, whether the build took a MAIN's clock goal from its
    rate or its `syn_mhz` (`SYN.TOOL_DOES_PNR`). AUTO_PIPELINE depths and AUTO_FSM
    schedules are recorded by binding, so an AUTO key used at several goals has one entry
    per goal (`key@50p0mhz`,
    [AUTO_DESIGN.md](AUTO_DESIGN.md#7-clock-goals-of-auto-objects));
  - `unbuilt_latency_reads` (`_unbuilt_latency_reads`): the `.latency` value the final
    elaboration read for each AUTO_PIPELINE or AUTO_MULTI_CYCLE it never instantiated,
    by kind and binding. A design reads such a tag when, for example, a factory builds an
    alternative the configuration leaves unused. A tag read with two different values is
    left out;
  - `build_inputs`: the run's `BUILD_INPUTS`, which the driver takes once, before the
    build reads anything:
    - the compiler's source hash (`SYN.COMPILER_SOURCE_HASH`) and the top;
    - every command-line setting except those in `_SETTINGS_OUTSIDE_BUILD_INPUTS` (where
      the build runs and with how many jobs, where caches live, debug output and
      simulation-only options), so a new setting counts by default. `-D` counts as the
      parsed parameter table, so order does not matter, and a `--latency_hints` or
      `--pins` file by its path and contents;
    - the `PIPELINEC_*`, `PYPELINEC_*` and `PYPELINE_*` environment variables and
      `PYTHONPATH`.
- **Replacing it.** A record is only ever the last met build. `SIMULATE_BUILT_HARDWARE`
  removes it whenever a build follows, which also covers `--comb` and `--no_synth`
  builds that rewrite the directory, and a build that misses timing writes none.
- **Up-to-date builds.** `BUILT_HARDWARE_IS_CURRENT` makes a plain build (no `--sim`, no
  `--rebuild`) of the recorded top do nothing when `_BUILD_INPUTS_DIFFERENCE` finds no
  difference: equal build inputs, and every recorded source still has its hash. The run
  prints `Up to date: ...` and the driver exits before writing anything. Otherwise it
  prints the first difference (`Building again: the --pipeline_min_effort setting
  changed ...`) and the build follows. Not part of the comparison, so `--rebuild` is the
  way to build again after changing them: the synthesis tool installation, files a
  design reads with `open()`, installed Python packages, and other environment
  variables.
- **Simulating it.** `SIMULATE_BUILT_HARDWARE` runs when the record's top differs from
  the file given, `SIM_TOOL` is the native simulator and `--sim` was given (a `--comb`
  run has already exited). It:
  - exits with an error if any recorded source's hash changed, if another version of the
    compiler built the record (its `build_inputs` compiler hash differs or is missing),
    or if the record lists problems;
  - calls `run_sim` with the recorded hardware, `built_hardware_from=` the directory and
    `design_params=` the recorded values, `goal_mode=` and `unbuilt_latency_reads=` (see
    [Simulating another top's built hardware](pypeline_sim_DESIGN.md#simulating-another-tops-built-hardware));
  - turns a `pypeline.BuiltHardwareError` into an error exit.

  Nothing is parsed, elaborated or written. A `--sim` of the recorded top itself is an
  ordinary build and simulation, even when its build is current: the record keeps only
  the AUTO_FSM schedule fields native simulation reads, and a design may read others when
  it is imported (some self-checking tests assert on their own schedule).

## 4. The backend contract

Each backend has one entry function, called by `SIM._DO_OPTIONAL_SIM` only when simulation
was requested:

| backend | entry |
|---|---|
| `COCOTB` | `DO_SIM(multimain_timing_params, parser_state, args)` |
| `VERILATOR` | `DO_SIM(multimain_timing_params, parser_state, args)` |
| `CXXRTL` | `DO_SIM(latency, parser_state)` (called with latency 0) |
| `MODELSIM` | `DO_OPTIONAL_DEBUG(do_debug, latency)` (always called; returns unless `do_debug`) |
| `EDAPLAY` | `SETUP_EDAPLAY(latency)` (called with latency 0) |

Each writes into its own subdirectory of `SYN.SYN_OUTPUT_DIRECTORY` (`cocotb/`,
`verilator/`, `cxxrtl/`, `all_vhdl_files/`; ModelSim writes its project at the top).
They share two `SIM.py` helpers:

- `GET_SIM_GEN_INFO(parser_state, multimain_timing_params)` returns a `SimGenInfo`: the
  external clocks and their MHz (`SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH`, with
  internally generated user clocks removed and external input clocks kept under their user
  names; a user clock's generated name includes its group, `clk_25p0_eth_rx`, as
  `VHDL.CLK_MHZ_GROUP_TEXT` builds it), the `*_DEBUG` input and output ports, and each
  MAIN's latency. Backends turn this
  into the clock and debug-port names of their generated testbench or header.
- `GET_SIM_FILES(latency)` walks the output directory for every `.vhd` file. EDAPlay and
  ModelSim use it; cocotb and the yosys-based backends use `vhdl_files.txt` or the final
  top instead (see [Artifact layers](VHDL_DESIGN.md#artifact-layers) for why the file list
  is the safer input).

## 5. Backends

### cocotb (`COCOTB.py`)

`DO_SIM` requires `cocotb-config` on `PATH`. Without `--makefile` it generates, in
`cocotb/`:

- `pipelinec_cocotb.py`, helpers named after the design's `*_DEBUG` ports
  (`DUMP_PIPELINEC_DEBUG(dut)` prints them all);
- `test_<top>.py`, a single-clock testbench (multiple clocks raise `NotImplementedError`)
  that drives the clock to `'0'` before its first rising edge, so the first logged
  `Clock: 0` is a real edge, then runs `--run N` cycles. It drives each reset pin
  (`SimGenInfo.reset_inputs`: the Pypeline reset `Input`s still top-level ports) to 1
  before the first edge and to 0 after it, the pulse native simulation drives
  ([guide](pypeline_guide.md#resets-in-simulation));
- a `Makefile` from `GET_MAKEFILE_TEXT`. GHDL is the only supported simulator (`--ghdl`,
  `--std=08`, plus `-frelaxed` when `AUTO_PIPELINE.RAM_REQUIRES_RELAXED_VHDL`). Its
  `SIM_ARGS` hold GHDL's waveform option, `GHDL_WAVE_ARG(args.wave)`: `--vcd=<top>.vcd`
  (written in `cocotb/`) without `--wave`, else `--vcd=`, `--fst=` or `--wave=` (GHW) with
  the absolute path of the `--wave` file, by its extension (`GHDL_WAVE_OPTIONS`).

It then runs `make` in that directory, prints stdout only (`pypeline_sim_debug.py`'s cycle
diff parses the interleaved `Clock: N` and `[SIM DEBUG PRINT: ...]` lines in order), and
fails the build on a nonzero exit.

- **cocotb's own pass/fail verdict, not `make`'s exit code.** `std.env.finish` (from
  `sim_finish()`) terminates GHDL out from under cocotb's still-awaiting test coroutine;
  cocotb cannot distinguish that from a real crash on its own, and its makefile cannot set
  an exit code at all (`Makefile.inc`: *"since we can't set an exit code from cocotb"*).
  `COCOTB.py` generates the `--run all` testbench with `expect_error=SimFailure` so
  cocotb's regression manager scores a clean `sim_finish()` stop as a genuine PASS, then
  reads the verdict from cocotb's own `results.xml` rather than `make`'s exit code or any
  console-text heuristic. A real failure (e.g. a firing `sim_assert`) still fails the
  build: GHDL itself exits nonzero in that case, which `make` (and `COCOTB.DO_SIM`)
  propagates. `--run all` has a safety cap of 1,000,000 cycles, after which the testbench
  raises. See `COCOTB.CHECK_COCOTB_RESULTS`'s docstring and
  `src/tests/pypeline_tests/inst/cocotb_verdict_test.py`, the regression guard for both
  halves.
- **`VHDL_SOURCES` is a GHDL `@file` response file, not an inlined list.**
  `COCOTB.GET_MAKEFILE_TEXT` sets `VHDL_SOURCES += @$(PIPELINEC_VHDL_FILES_TXT)` rather
  than the more obvious `$(shell cat vhdl_files.txt)`. cocotb's `Makefile.ghdl` writes its
  `analyse` target as one backslash-continued logical recipe line, so `make` hands the
  whole thing to the shell as a *single* argv string; Linux caps any one argv/envp string
  at `MAX_ARG_STRLEN` (`PAGE_SIZE * 32` = 131072 bytes here), independent of the much
  larger overall `ARG_MAX`. A large design's own VHDL file list, once every absolute path
  is inlined, can exceed that on its own (`make[1]: execvp: bash: Argument list too long`,
  failing before GHDL even starts). GHDL's `@file` response-file syntax is
  whitespace-split like a normal argv, so the existing space-separated `vhdl_files.txt`
  works unmodified as one. The `@...` token names no real file, so it must be declared
  `.PHONY` (a phony target is never "missing") or `make` refuses it as an unbuildable
  prerequisite; real dependency tracking moves to `CUSTOM_COMPILE_DEPS`, which cocotb's
  `Makefile.inc` also wires into `analyse`. Every other GHDL/yosys call site with the same
  shape (`OPEN_TOOLS`/`CXXRTL`/`PYRTL`/`CC_TOOLS`/`DEVICE_MODELS` writing a
  `yosys -p '<huge ghdl file list>'` shell one-liner) hits the identical limit and is fixed
  the same way via `OPEN_TOOLS.WRITE_YOSYS_SCRIPT`, which writes the commands to a `.ys`
  script file and passes `-s <path>` instead of `-p '<commands>'`. See
  `src/tests/pypeline_tests/inst/long_file_list_arg_len_test.py`.

### Verilator (`VERILATOR.py`)

`DO_SIM` writes `verilator/pipelinec_verilator.h` (`#define`s for the clock(s), the
`*_DEBUG` ports, a `DUMP_PIPELINEC_DEBUG(top)` macro and `<main>_LATENCY` for each MAIN)
and a default `main.cpp`, unless `--main_cpp` names one. It needs GHDL and yosys
(`OPEN_TOOLS.GHDL_BIN_PATH`, `OPEN_TOOLS.YOSYS_BIN_PATH`), converts the final top to Verilog
with `OPEN_TOOLS.RENDER_FINAL_TOP_VERILOG`, and stops there for `--run 0`. Otherwise it
builds with `verilator -cc ... --exe main.cpp` and runs `obj_dir/V<top>`. The Verilator
directory (`GET_VERILATOR_BIN_PATH`) is resolved on use, not at import, so it does not read
`OPEN_TOOLS` while the import cycle is still loading.

### CXXRTL (`CXXRTL.py`)

`DO_SIM` writes `cxxrtl/pipelinec_cxxrtl.h` (clock and debug-port `#define`s; more than one
clock prints a warning) and a default `main.cpp`, then a `cxxrtl.sh` that runs yosys with
the GHDL plugin (`ghdl --std=08 <top>; write_cxxrtl`) and compiles with clang++. It runs the
resulting binary and prints its output. It always uses its generated `main.cpp`.

### ModelSim (`MODELSIM.py`)

`DO_OPTIONAL_DEBUG` writes a ModelSim project (`pipelinc_proj.do`, `pipelinec_modelsim.ini`
from `src/text/model_sim_ini.txt`) over every file `GET_SIM_FILES` finds, compiling the
Vivado fixed/float packages into `ieee_proposed` when the tool is Vivado. It launches
`vsim` (from `PATH`, else a hardcoded path) and then exits the process: it is an interactive
debug entry, not a pass/fail simulation.

### EDA Playground (`EDAPLAY.py`)

`SETUP_EDAPLAY` copies every file `GET_SIM_FILES` finds into `all_vhdl_files/` and prints
the edaplayground.com link to drag them into. Nothing is simulated locally.

## 6. Waveforms

`--wave FILE` records a simulation's waveform; the user guide is
[Waveforms](pypeline_guide.md#waveforms).

- **Checking the request.** `CHECK_WAVE_ARGS(args)` exits with an error before anything is
  built or simulated when `--wave` lacks `--sim`, the simulator is neither the native one
  nor cocotb + GHDL, the extension is not one the simulator writes (`WAVE_FORMAT`: `.vcd`,
  `.fst`, `.ghw`), the file's directory does not exist, or `--wave` comes with
  `--makefile`; and when `--wave_signals` lacks `--wave` or goes to GHDL.
  `NATIVE_WAVE_PROBLEM` holds the native rules (`.vcd` or `.fst`, and `vcd2fst` on `PATH`
  for `.fst`); `pypeline_sim.py --wave` and `START_NATIVE_WAVES` check with it too. Both
  settings are in `_SETTINGS_OUTSIDE_BUILD_INPUTS`, so a waveform never makes a build run
  again.
- **GHDL.** `COCOTB.GHDL_WAVE_ARG` passes the file to GHDL's own writer (see
  [cocotb](#cocotb-cocotbpy)), which dumps the design's VHDL signals. Its VCD and FST
  writers skip records and arrays of vectors (`$comment <signal> is not handled`), which is
  most Pypeline data; its GHW keeps every VHDL type.
- **Native simulation.** `pypeline_sim.run_sim(..., wave=, wave_signals=)`, given `wave`
  by both of `DO_OPTIONAL_SIM`'s native calls (the comb and pipelined paths) and by
  `SIMULATE_BUILT_HARDWARE`, imports `SIM` only then. Before the first cycle it calls
  `START_NATIVE_WAVES(path, patterns, mains, design_wires)`, which makes a `WaveRecorder`
  and installs it as `pypeline._sim_wave_recorder` (`pypeline.SET_SIM_WAVE_RECORDER`;
  `pypeline` never imports `SIM`). In each cycle's final pass, `_run_clock_cycle` hands
  the recorder every MAIN's return (`main_return`) and `pypeline.sim_wave` hands it its
  values (`tap`); after the pass, also when a `sim_finish()` ends it, `end_cycle(cycle)`
  samples the ports and selected Wires from `pypeline._sim_wire_state` and writes the
  cycle. `STOP_NATIVE_WAVES()` closes the file in `run_sim`'s `finally`, after the
  `@final(sim)` hooks, however the run ended.

### What a native waveform holds

The top scope is `SYN.TOP_LEVEL_MODULE` (`--top`, default `top`), the top-level entity's
name. Below it:

| signal | path |
|---|---|
| the clock | `top/<port>`: `_Clock.port_name` of the MAINs' clock (`clk_80p0`), `clk` when no MAIN names one |
| each `Input` and `Output` | `top/<name>`, the port's name (`design_wires.ports`) |
| each `@MAIN`'s return | `top/<main>_return_output`, the return port, except a pipelined MAIN's (`pypeline._sim_pipelined_main_info`), whose return native simulation computes at stage 0; one NOTE names them |
| a global Wire matching a `--wave_signals` glob | `top/<module>/<wire>`, `<module>` the module's name with `.` as `_` (its hardware prefix, `PY_TO_LOGIC._discover_global_wires`); a Wire of the top-level file (`pypeline_sim.DESIGN_MODULE_NAME`) is `top/<wire>` |
| `sim_wave(name, value)` | `top/<MAIN>/<name>` (the running MAIN's hardware name), or `top/<name>` for a name starting with `/` or outside any MAIN; `/` and `.` separate scopes |
| stream perf probes | `sim_wave` signals of the probes (`<label>/<name>/valid`, ...): [stream perf guide](../include/pypeline/stream/pypeline_stream_perf_guide.md#waveforms) |

`add_wires` matches each Wire's path below the top scope with `fnmatch.fnmatchcase`, in
which `*` also matches `/`; a pattern that matches no Wire prints a WARNING. `_tap_path`
resolves a `sim_wave` name once per `(name, MAIN)`.

### Layout of a value

A signal's layout (`_wave_layout_of_ctype`, `_wave_layout_of_value`) is the tree a value
is flattened through to its leaves, which are its VCD variables:

- an integer type: a `wire` variable of the type's width, two's complement for a signed
  type;
- an `@struct`: a `$scope struct` holding its fields;
- an array: one signal per element, named `name[i]` (a struct element is a
  `$scope struct name[i]`);
- an `@enum`: a `string` variable holding the member's name, or the decimal value when no
  member has it;
- a `str`: a `string` variable, whitespace written as `_`;
- a plain `int` or `bool`, which has no type: a `wire` variable as wide as its widest
  value. A negative one raises.

A port, Wire or return takes its type's layout; a `sim_wave` signal takes its first
value's. Each sample is flattened to a tuple of leaf values (`_wave_flatten`), checked
cheaply: a value whose `_wave_shape_key` (its type's name, or a list's length and first
element's key) the signal has seen fits; a new key compares the layouts
(`_wave_layouts_match`), where an integer of no type fits a typed one (masked to its
width). Any other change raises a `ValueError` naming the signal. A signal sampled twice
in one cycle shows the last value, with one NOTE per signal.

### Timing

The timescale is 1 ps and one cycle is one clock period, `P = round(1e6 / MHz)` ps
(1000 without a rate):

- cycle N's values are written at time N·P, and a value changes exactly there;
- the clock rises at N·P for N ≥ 1, the commit that ends cycle N−1, falls half a period
  later, and is low through cycle 0;
- the file ends at (cycles written)·P. A `sim_finish()` cycle is written, but a MAIN after
  the finishing one in the final pass has no return and no `sim_wave` values that cycle.
  An error drops its incomplete cycle, so a failing run still leaves a valid file.

The cocotb testbench's first rising edge is at 1 ps, and then one per P, so GHDL's cycle N
(N ≥ 1) starts at 1 + (N−1)·P: P − 1 ps before native simulation's.

### The VCD writer and FST

`_VcdWriter` writes the header last, so a `sim_wave` signal first seen in a later cycle
still gets a variable, and an untyped integer's width is its widest value's: changes after
time 0 stream to `FILE.body.tmp`, and those at time 0 stay in memory. `close()` writes
`$version`, `$timescale 1ps`, the scope tree, `$enddefinitions`, the time-0 values as
`$dumpvars`, the body and the end time, then removes the temporary file. Identifier codes
are base 94 (`_vcd_code`). A variable has no value until its first sample. The file has no
`$date`, so the same run always writes the same bytes. `end_cycle` writes only the leaves
whose values changed: each signal's leaf tuple is compared with the last one written.

For `FILE.fst`, the VCD is written to `FILE.fst.vcd` and converted by GTKWave's
`vcd2fst -v`; the VCD is removed after a conversion and kept, with a WARNING, after a
failure. `vcd2fst` (GTKWave 3.3.104) keeps struct scopes and string variables, and ignores
`$attrbegin`, so an FST has no enum tables.

### Limitations

- `sim_wave` signals and probes exist in native simulation only: elaboration deletes the
  calls, so GHDL's dump has none of them, only the generated VHDL's signals.
- Registers appear only through `sim_wave` (a `Reg` read is its value), and MAIN
  arguments, which native simulation drives with zeros, not at all.
- Native simulation runs one clock, so a waveform has one.

## 7. Import structure

`SIM.py` imports every backend and `pypeline_sim` at module level, and the backends import
`SIM` back for `GET_SIM_GEN_INFO` / `GET_SIM_FILES`. This works because no module reads
another's attributes while being imported (`src_module_import_test.py` imports every src
module first in a fresh interpreter). `SIM.py` also imports `AUTO_PIPELINE`,
`AUTO_MULTI_CYCLE`, `LOGIC`, `SYN` and `VHDL` at module level, so importing `SIM` loads
the whole compiler; `VHDL.py` does not import `SIM`. `pypeline_sim.py` imports `SIM` only
inside `run_sim` and `main()`, when a waveform is asked for: plain native runs load no
compiler module, and `SIM` loads no `PY_TO_LOGIC`. Run as a script, `pypeline_sim.py` is
`__main__`, so `SIM`'s own `import pypeline_sim` loads a second, unused copy of it; the
two share `pypeline`, whose state the run uses.

## 8. Tests

- `waves_test.py` (`inst/`, one file of five registrations): `unit` checks the waveform
  block in-process (layouts, paths and source-text names, the sampled-twice NOTE, type
  changes, clock edges and end time, Wire globs, `CHECK_WAVE_ARGS`'s refusals,
  `pypeline_sim_debug.py`'s per-run files, `sim_wave`'s gating); `native_vcd` and
  `native_fst` (`native_sim`) check every signal of `waves_design.py` at every cycle time
  through `pypelinec --sim --comb --wave`, and that standalone `pypeline_sim.py` writes
  the same VCD (an FST read back by `fst2vcd`); `elab` checks that the fixture's taps and
  probes add no top-level port; `ghdl` (`build_report_device_models`) checks that GHDL
  writes the `.vcd`, `.fst` and `.ghw` asked for, and `cocotb/top.vcd` without `--wave`.
- `cocotb_verdict_test.py`: cocotb's `results.xml` verdict for a clean `sim_finish()` stop
  and for a real failure.
- `long_file_list_arg_len_test.py`: file lists longer than `MAX_ARG_STRLEN` reach GHDL and
  yosys.
- `src_module_import_test.py`: every src module, `SIM` and the backends included, imports
  first in a fresh interpreter.
- `built_hardware_sim_test.py` (build_report, sky130): a testbench simulated on the hardware
  built for its real top, and each refusal; the same build again is up to date, and
  `--rebuild` builds; see
  [`pypeline_TESTS.md`](pypeline_TESTS.md).
- `built_hardware_current_test.py` (unit): which build inputs make a recorded build current
  (not `--wave` and `--wave_signals`, among other operational settings).
- The `native_vs_vhdl_sim` category (`native_vs_vhdl_sim_tests.py`) runs designs through
  both the native simulator and cocotb + GHDL and diffs the cycle logs; see
  [`pypeline_TESTS.md`](pypeline_TESTS.md).
