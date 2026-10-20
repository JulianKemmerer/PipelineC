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
- [4. The backend contract](#4-the-backend-contract)
- [5. Backends](#5-backends)
  - [cocotb (`COCOTB.py`)](#cocotb-cocotbpy)
  - [Verilator (`VERILATOR.py`)](#verilator-verilatorpy)
  - [CXXRTL (`CXXRTL.py`)](#cxxrtl-cxxrtlpy)
  - [ModelSim (`MODELSIM.py`)](#modelsim-modelsimpy)
  - [EDA Playground (`EDAPLAY.py`)](#eda-playground-edaplaypy)
- [6. Import structure](#6-import-structure)
- [7. Tests](#7-tests)

---

## 1. Who does what

| module | role |
|---|---|
| `src/SIM.py` | selects the simulator (`SET_SIM_TOOL`), decides whether a native run needs a build (`NATIVE_SIM_SKIPS_BUILD`, `SIM_AT_COMB_STAGE`), runs it (`DO_OPTIONAL_SIM`, and `DO_COMB_STAGE_SIM` after a `--comb` build's final files) and gathers what every backend needs (`GET_SIM_GEN_INFO`, `GET_SIM_FILES`, `GET_MAIN_FUNC_LATENCIES`) |
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
replace the generated driver files.

## 3. When simulation runs

`src/pipelinec` (see [The build driver](SYN_DESIGN.md#the-build-driver-srcpipelinec))
calls `SIM` at three points:

- **Right after tool selection.** `NATIVE_SIM_SKIPS_BUILD(args)` is true when `SIM_TOOL is
  pypeline_sim` and comb simulation was requested (`--sim --comb`, `--sim_comb`, or
  `--no_synth`). The driver then calls `DO_OPTIONAL_SIM` and exits: no VHDL elaboration or
  synthesis happens, exactly like running `pypeline_sim.py` standalone.

  ```
  python3 src/pipelinec my_design.py --sim --run 1000
  ```

  is therefore `python3 src/pypeline_sim.py my_design.py --run 1000` **plus a full build
  first when `--comb` is absent**.
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
params exist, `DO_OPTIONAL_SIM` passes `pypeline_sim.run_sim`:

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

Before that, `CHECK_PIPELINED_NATIVE_SIM_SUPPORTED` exits with an error if a pipelined
region (a pure `@MAIN` with latency, or an AUTO_PIPELINE call site with latency) uses a
`VOLATILE` global wire in its own body, or any global wire in a function called inside
the region: the native model cannot place those in time. `pypeline._sim_region_for` is
its runtime twin for plain native runs with no build. The native path always runs at the
default `strict` accuracy; `pipelinec` has no equivalent of `pypeline_sim.py`'s `--mode`.

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
  names), the `*_DEBUG` input and output ports, and each MAIN's latency. Backends turn this
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
  `Clock: 0` is a real edge, then runs `--run N` cycles;
- a `Makefile` from `GET_MAKEFILE_TEXT`. GHDL is the only supported simulator (`--ghdl`,
  `--std=08`, plus `-frelaxed` when `AUTO_PIPELINE.RAM_REQUIRES_RELAXED_VHDL`).

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

## 6. Import structure

`SIM.py` imports every backend and `pypeline_sim` at module level, and the backends import
`SIM` back for `GET_SIM_GEN_INFO` / `GET_SIM_FILES`. This works because no module reads
another's attributes while being imported (`src_module_import_test.py` imports every src
module first in a fresh interpreter). `SIM.py` also imports `AUTO_PIPELINE`,
`AUTO_MULTI_CYCLE`, `LOGIC`, `SYN` and `VHDL` at module level, so importing `SIM` loads
the whole compiler; `VHDL.py` does not import `SIM`.

## 7. Tests

- `cocotb_verdict_test.py`: cocotb's `results.xml` verdict for a clean `sim_finish()` stop
  and for a real failure.
- `long_file_list_arg_len_test.py`: file lists longer than `MAX_ARG_STRLEN` reach GHDL and
  yosys.
- `src_module_import_test.py`: every src module, `SIM` and the backends included, imports
  first in a fresh interpreter.
- The `native_vs_vhdl_sim` category (`native_vs_vhdl_sim_tests.py`) runs designs through
  both the native simulator and cocotb + GHDL and diffs the cycle logs; see
  [`pypeline_TESTS.md`](pypeline_TESTS.md).
