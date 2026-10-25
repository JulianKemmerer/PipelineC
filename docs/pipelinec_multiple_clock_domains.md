# Multiple clock domains in the PipelineC C front end

This document describes how a C design gets more than one clock: how a function is given a
clock, how clocks are named and grouped, how data moves between functions on the same clock
and on different clocks, and what the compiler builds for all of it (IR, generated C, VHDL,
constraints, simulation files). It covers the C front end (`src/C_TO_LOGIC.py`) and the
shared back end it feeds. Sections 1 to 14 describe the current behavior.
[Section 15](#15-known-problems-and-fix-ideas) lists the known problems, each with an idea
for a fix. [Section 16](#16-ideas-for-multiple-clock-domains-in-pypeline) uses all of this
to suggest how the Python front end (Pypeline) could get multiple clock domains; apart from
that section, Pypeline is not covered.

The user-facing description lives on the wiki page
[Main Function Clock Crossings](https://github.com/JulianKemmerer/PipelineC/wiki/Main-Function-Clock-Crossings),
with related material on [Pragmas](https://github.com/JulianKemmerer/PipelineC/wiki/Pragmas),
[Global Variables](https://github.com/JulianKemmerer/PipelineC/wiki/Global-Variables),
[Modules, Hierarchy, Composability](https://github.com/JulianKemmerer/PipelineC/wiki/Modules,-Hierarchy,-Composability)
and [Automatically Generated Functionality](https://github.com/JulianKemmerer/PipelineC/wiki/Automatically-Generated-Functionality).
This document follows the code where the two differ. Generated-code excerpts come from
builds of the repository examples and small test designs.

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section, if it
> has one, rather than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## Table of Contents

- [1. The model](#1-the-model)
  - [Mechanisms at a glance](#mechanisms-at-a-glance)
  - [Terms](#terms)
- [2. Declaring clock domains](#2-declaring-clock-domains)
  - [MAIN pragmas](#main-pragmas)
  - [Clock names](#clock-names)
  - [Clock groups](#clock-groups)
  - [Synthesis-only targets: `MAIN_SYN_MHZ`](#synthesis-only-targets-main_syn_mhz)
  - [Clock domain inference](#clock-domain-inference)
  - [User clocks: `CLK_MHZ` and `CLK_MHZ_GROUP`](#user-clocks-clk_mhz-and-clk_mhz_group)
- [3. Same-domain communication: shared global variables](#3-same-domain-communication-shared-global-variables)
- [4. Clock crossing variables](#4-clock-crossing-variables)
  - [How a crossing is recognized](#how-a-crossing-is-recognized)
  - [Kinds of crossing](#kinds-of-crossing)
  - [The generated crossing header](#the-generated-crossing-header)
  - [Rules and checks](#rules-and-checks)
- [5. Async FIFOs](#5-async-fifos)
  - [Declaring a FIFO](#declaring-a-fifo)
  - [Write and read semantics](#write-and-read-semantics)
  - [Which FIFO hardware is generated](#which-fifo-hardware-is-generated)
  - [The built-in FIFOs](#the-built-in-fifos)
  - [Latency and capacity](#latency-and-capacity)
  - [Unused and one-sided FIFOs](#unused-and-one-sided-fifos)
  - [Stream FIFOs: `GLOBAL_STREAM_FIFO`](#stream-fifos-global_stream_fifo)
  - [FIFO calls inside auto-pipelined MAINs](#fifo-calls-inside-auto-pipelined-mains)
- [6. Integer-ratio volatile crossings](#6-integer-ratio-volatile-crossings)
- [7. Same-clock crossing wires and `wire.h`](#7-same-clock-crossing-wires-and-wireh)
  - [Arbitrated handshake crossings: `IO_PAIR`](#arbitrated-handshake-crossings-io_pair)
- [8. `ASYNC_WIRE`](#8-async_wire)
- [9. Libraries and examples](#9-libraries-and-examples)
  - [Synchronizer macros: `cdc.h`](#synchronizer-macros-cdch)
  - [Libraries that cross clock domains](#libraries-that-cross-clock-domains)
  - [Examples](#examples)
  - [Related issues and discussions](#related-issues-and-discussions)
- [10. IR: what the compiler records](#10-ir-what-the-compiler-records)
  - [`ParserState` fields](#parserstate-fields)
  - [Per-variable and per-crossing records](#per-variable-and-per-crossing-records)
  - [`Logic` flags and helpers](#logic-flags-and-helpers)
- [11. VHDL generation](#11-vhdl-generation)
  - [Global wire records](#global-wire-records)
  - [Function entities](#function-entities)
  - [The multi-MAIN top level](#the-multi-main-top-level)
  - [`clk_cross_entities.vhd`](#clk_cross_entitiesvhd)
  - [Output files](#output-files)
- [12. Synthesis tool support](#12-synthesis-tool-support)
  - [Clock constraints](#clock-constraints)
  - [Timing reports and the sweep](#timing-reports-and-the-sweep)
- [13. Simulation support](#13-simulation-support)
- [14. Compiler flow](#14-compiler-flow)
- [15. Known problems and fix ideas](#15-known-problems-and-fix-ideas)
  - [Crossing checks crash with `NameError`](#crossing-checks-crash-with-nameerror)
  - [Inference never ends when a crossing side spans two clocks](#inference-never-ends-when-a-crossing-side-spans-two-clocks)
  - [Unused and read-only FIFOs crash the top-level writer](#unused-and-read-only-fifos-crash-the-top-level-writer)
  - [Write-only FIFOs leave `ready` undriven](#write-only-fifos-leave-ready-undriven)
  - [XPM FIFO depths must be powers of two](#xpm-fifo-depths-must-be-powers-of-two)
  - [Errors that exit with status 0](#errors-that-exit-with-status-0)
  - [Quartus clock groups run together](#quartus-clock-groups-run-together)
  - [Quartus does not find user clocks](#quartus-does-not-find-user-clocks)
  - [Tools without multi-clock constraints](#tools-without-multi-clock-constraints)
  - [Vivado clock groups make every pair asynchronous](#vivado-clock-groups-make-every-pair-asynchronous)
  - [`MAIN_SYN_MHZ` on a shared clock depends on pragma order](#main_syn_mhz-on-a-shared-clock-depends-on-pragma-order)
  - [A clock passed as a MAIN argument is registered by itself](#a-clock-passed-as-a-main-argument-is-registered-by-itself)
  - [No CDC attributes or constraints](#no-cdc-attributes-or-constraints)
  - [`ASYNC_WIRE` is not a false path](#async_wire-is-not-a-false-path)
  - [FIFO restrictions](#fifo-restrictions)
  - [XPM wrapper assigns `rd_return_output.data` twice](#xpm-wrapper-assigns-rd_return_outputdata-twice)
  - [`ASYNC_WIRE` is ignored for `INST_ARRAY` globals](#async_wire-is-ignored-for-inst_array-globals)
  - [No multi-clock testbenches](#no-multi-clock-testbenches)
  - [Simulation clock list](#simulation-clock-list)
  - [Crossings are found by name](#crossings-are-found-by-name)
  - [Pipelined MAINs split FIFO handshakes across stages](#pipelined-mains-split-fifo-handshakes-across-stages)
  - [`MAIN_MHZ f other_main` copies only the MHz](#main_mhz-f-other_main-copies-only-the-mhz)
  - [Crossing tuple unpacked in the wrong order](#crossing-tuple-unpacked-in-the-wrong-order)
  - [CC tools report parser](#cc-tools-report-parser)
  - [Cross-clock paths are never reported](#cross-clock-paths-are-never-reported)
  - [No FIFO reset and no reset synchronizers](#no-fifo-reset-and-no-reset-synchronizers)
- [16. Ideas for multiple clock domains in Pypeline](#16-ideas-for-multiple-clock-domains-in-pypeline)
  - [What Pypeline has today](#what-pypeline-has-today)
  - [What to keep, what to leave behind](#what-to-keep-what-to-leave-behind)
  - [Recommended scope](#recommended-scope)
  - [Clock domains in the source](#clock-domains-in-the-source)
  - [Asynchronous wires](#asynchronous-wires)
  - [Synchronizer library](#synchronizer-library)
  - [Async FIFOs](#async-fifos)
  - [Native simulation with several clocks](#native-simulation-with-several-clocks)
  - [VHDL simulation and testbenches](#vhdl-simulation-and-testbenches)
  - [Constraints and timing](#constraints-and-timing)
  - [Resets](#resets)
  - [Related clocks (later)](#related-clocks-later)
  - [How C clock-domain code would translate](#how-c-clock-domain-code-would-translate)
  - [Suggested order of work and tests](#suggested-order-of-work-and-tests)
  - [Open questions](#open-questions)
- [History](#history)
  - [Shared globals replaced same-clock crossings](#shared-globals-replaced-same-clock-crossings)
  - [`ASYNC_WIRE` is a pragma, not a kind of crossing](#async_wire-is-a-pragma-not-a-kind-of-crossing)
  - [FIFO syntax: generated headers, then macros](#fifo-syntax-generated-headers-then-macros)
  - [FIFO implementations](#fifo-implementations)
  - [Clock inference](#clock-inference)
  - [Clock groups and user clocks](#clock-groups-and-user-clocks)
  - [Integer-ratio crossings](#integer-ratio-crossings)
  - [Synthesis-only targets](#synthesis-only-targets)
  - [Arbitrated crossings](#arbitrated-crossings)
  - [Where the code lives](#where-the-code-lives)

---

## 1. The model

- **A MAIN is one clock domain.** A function named by a `MAIN` pragma becomes one instance
  in the generated top level. Every function it calls, at any depth, runs on that MAIN's
  clock. MAIN instances are always enabled; a function called inside a condition is
  clock-enabled by its caller.
- **A clock domain is a (MHz, group) pair.** The pair becomes a clock name,
  `clk_<MHz>[_<group>]` (`clk_100p0`, `clk_25p0_xil_temac_rx`). MAINs with the same pair
  share one clock. MAINs with the same MHz but different groups get different clocks, and
  every pair of different clocks is treated as asynchronous.
- **Data moves between MAINs only through global variables.**
  - On one clock: a *shared global variable*, which is a plain wire or register.
  - Between clocks: a *clock crossing variable*, a global that is only touched through
    `<var>_WRITE...()` / `<var>_READ...()` functions. The compiler builds an async FIFO
    (flow controlled, the normal choice) or, for clocks whose frequencies are integer
    multiples, a "volatile" ratio crossing (old, experimental).
  - `#pragma ASYNC_WIRE` turns either kind into an unchecked direct connection.
- **A `uint1_t` global can be a clock.** `CLK_MHZ` names a global wire, generated inside
  the design or driven by a top-level input, as the clock of a given MHz and group.
- **Unspecified frequencies are inferred.** A `#pragma MAIN` without a frequency takes the
  clock of the MAINs it shares globals or crossings with.

The generated top level for a two-clock design with one FIFO looks like this (the names
are the ones `examples/async_clock_crossing.c` produces):

```
  clk_50p0                                                                         clk_25p0
     │                                                                                 │
     ▼                                                                                 ▼
 ┌────────┐  module_to_global.fast   ┌────────────────────────┐  global_to_module.slow  ┌────────┐
 │  fast  │── write_data, enable ───▶│ clk_cross_fast_to_slow │── data, valid ─────────▶│  slow  │
 │ (MAIN) │◀─ ready ─────────────────│  in_clk  => clk_50p0   │◀─ read_enable ──────────│ (MAIN) │
 └────────┘  global_to_module.fast   │  out_clk => clk_25p0   │  module_to_global.slow  └────────┘
                                     └────────────────────────┘
```

A MAIN entity that uses globals or crossings has a `module_to_global` output record and a
`global_to_module` input record. The top level connects record fields to each other
directly (shared globals) or through one generated `clk_cross_<var>` entity per crossing.

### Mechanisms at a glance

| Mechanism | How it is written | Clocks allowed | Flow control | Hardware generated | Status |
|---|---|---|---|---|---|
| Shared global variable | a global written by one function and read by others | one clock only | none | direct assignment between MAIN records | the normal same-clock connection |
| Async FIFO | `GLOBAL_FIFO*` / `ASYNC_CLK_CROSSING*` macros, or `T v[DEPTH];` + `#include "clock_crossing/v.h"`, accessed with `v_WRITE_<N>` / `v_READ_<N>` | any; one clock per side | write `ready`, read `valid` | `xpm_fifo_async` (Vivado), built-in `pipelinec_async_fifo_fwft` (other tools), built-in `pipelinec_fifo_fwft` (one clock) | the normal clock crossing |
| Stream FIFO | `GLOBAL_STREAM_FIFO*` macros | any | `stream(T)` valid plus `_ready` wires | an async FIFO plus two wiring MAINs | simplest syntax |
| Volatile ratio crossing | `volatile T v;` + generated header, `v_WRITE()` / `v_READ()` | integer MHz ratio, same group | none; invalid slots arrive as zeros | counters and shift registers in the fast domain | experimental, old |
| Same-clock crossing wire | `T v;` + generated header, `v_WRITE()` / `v_READ()` or `WIRE_WRITE` / `WIRE_READ` | one clock | none | holding register and mux | legacy; shared globals replace it |
| `ASYNC_WIRE` | `#pragma ASYNC_WIRE v` on a shared global or crossing variable | any | none, unsynchronized | direct assignment (shared global) or a holding register in the write domain (crossing variable) | the user owns the CDC |
| User clock | `CLK_MHZ` / `CLK_MHZ_GROUP` on a `uint1_t` global | — | — | an internal clock signal | |

### Terms

| Term | Meaning in this document |
|---|---|
| clock domain | the set of MAINs, and everything they call, that share one clock name |
| clock name | `clk_<MHz>[_<group>]`, the top-level port or internal signal of a domain ([Clock names](#clock-names)) |
| clock group | PipelineC's tag that makes two clocks of the same frequency distinct ([Clock groups](#clock-groups)). Not the same thing as an SDC `set_clock_groups` group, which is a set of clocks timed as asynchronous to the clocks in the other groups |
| shared global | a global variable used by more than one function; a wire between MAINs on one clock ([section 3](#3-same-domain-communication-shared-global-variables)) |
| crossing variable, crossing | a global used only through `<var>_WRITE...` / `<var>_READ...` functions; the compiler builds a `clk_cross_<var>` entity for it ([section 4](#4-clock-crossing-variables)) |
| write side, read side | the MAINs whose call trees call the write function, or the read function, of a crossing |
| wiring MAIN | a small `FUNC_WIRES` MAIN that a library macro declares to connect globals, usually without a frequency so that inference places it |
| user clock | a `uint1_t` global named as a clock with `CLK_MHZ` ([User clocks](#user-clocks-clk_mhz-and-clk_mhz_group)) |
| synchronizer | registers in the receiving domain that sample an asynchronous signal (the `CDC` macros, the pointer registers inside the async FIFOs) |
| synthesis top, final top | `top/top_<hash>.vhd`, written for PipelineC's own timing runs with IO registers, and `top/top.vhd`, written by `SYN.WRITE_FINAL_FILES` at the end of a build without them. A `--no_synth` build without fixed `AUTO_PIPELINE` latencies skips `WRITE_FINAL_FILES` and leaves only the synthesis top |

## 2. Declaring clock domains

### MAIN pragmas

`C_TO_LOGIC.APPEND_PRAGMA_INFO` reads every pragma in the parsed C file. The clock-related
ones:

| Pragma | Macro in [`include/compiler.h`](../include/compiler.h) | Effect |
|---|---|---|
| `#pragma MAIN f` | `MAIN(f)` | `f` is a top-level instance. MHz and group stay unknown until set elsewhere or inferred. |
| `#pragma MAIN_MHZ f 100.0` | `MAIN_MHZ(f, 100.0)` | Sets the MHz; also sets the synthesis MHz if that is still unknown. |
| `#pragma MAIN_MHZ f 100.0 grp` | `MAIN_MHZ_GROUP(f, 100.0, grp)` | Also sets the clock group. |
| `#pragma MAIN_MHZ f other_main` | `MAIN_MHZ(f, other_main)` | Copies the MHz and synthesis MHz of another MAIN (not its group). |
| `#pragma MAIN_SYN_MHZ f 147.0 [grp]` | `MAIN_SYN_MHZ(f, 147.0)` | Sets the synthesis-only target; also sets the MHz if that is still unknown. |
| `#pragma MAIN_GROUP f grp` | none | Sets the group only. |
| `#pragma CLK_MHZ w 25.0` | `CLK_MHZ(w, 25.0)` | Global `w` is a clock (see [User clocks](#user-clocks-clk_mhz-and-clk_mhz_group)). |
| `#pragma CLK_MHZ_GROUP w 25.0 grp` | `CLK_MHZ_GROUP(w, 25.0, grp)` | A clock with a group. |
| `#pragma ASYNC_WIRE v` | none | See [`ASYNC_WIRE`](#8-async_wire). |
| `#pragma ID_INST v path` | none | Picks one writer instance of crossing `v` (see [Rules and checks](#rules-and-checks)). |
| `#pragma IO_PAIR in out` | none (generated) | See [Arbitrated handshake crossings](#arbitrated-handshake-crossings-io_pair). |
| `#pragma INPUT w` / `#pragma OUTPUT w` | `DECL_INPUT` / `DECL_OUTPUT` | `w` is a top-level port. |

The macros exist because a `#pragma` cannot come out of a C macro; `PRAGMA_MESSAGE`
emits `_Pragma(...)` instead. `MAIN_MHZ_GROUP(f, mhz, grp)` expands to
`#pragma MAIN_MHZ f mhz grp`; there is no macro for `MAIN_GROUP`.

Details:

- The MHz token is parsed as a float. If that fails it must be the name of a MAIN whose
  own pragma came earlier in the preprocessed source, else the build stops with
  `Error in MAIN_MHZ: f tok`. [`include/uart/uart_msg_fifos.c`](../include/uart/uart_msg_fifos.c)
  uses this to put a FIFO wiring MAIN on the UART module's clock:
  `#pragma MAIN_MHZ uart_rx_msg_fifo_module uart_rx_msg`.
- The group token `None` means no group. Macros pass it as a default:
  [`include/shared_resource_bus_decl.h`](../include/shared_resource_bus_decl.h) defines
  `SHARED_RESOURCE_BUS_HOST_CLK_GROUP` as `None` unless the user set one.
- A later `MAIN_MHZ` or `MAIN_SYN_MHZ` without a group does not clear a group set earlier.
- Every MAIN gets an entry in `main_mhz`, `main_syn_mhz` and `main_clk_group`, `None`
  when unknown.
- With no MAIN pragma at all the build stops with `No main function specified?`. A
  pragma naming a function that does not exist stops it with
  `Main function: f does not exist?`.

### Clock names

`VHDL.CLK_MHZ_GROUP_TEXT(mhz, group)` builds the name; `VHDL.CLK_EXT_STR(main, ...)`
applies it to a MAIN's `main_mhz` and `main_clk_group`. The MHz is printed as a Python
float with `.` replaced by `p`. Below 1 MHz the unit becomes `khz`, below 1 kHz `hz`. A
group is appended after `_`.

| MHz, group | Clock name |
|---|---|
| 100.0 | `clk_100p0` |
| 166.66 | `clk_166p66` |
| 0.5 | `clk_500p0khz` |
| 100.0, `other_group` | `clk_100p0_other_group` |
| 25.0, `xil_temac_rx` | `clk_25p0_xil_temac_rx` |
| 0.00006 (60 Hz) | `clk_60p0hz` |
| 1000/7 | `clk_142p85714285714286` |
| unknown | `clk_None` |

The name always uses `MAIN_MHZ`, never `MAIN_SYN_MHZ`. It is the name of the top-level
clock port, of the clock in the generated constraints, and of the path group the
synthesis tool reports.

The number is printed with Python's `str(float)`, so a frequency that is not a short
decimal gives a long name, and two pragmas name the same clock only if their values are
equal as floats: `100` and `100.0` match, while `33.333` and `33.3333` do not. The group is
appended as written; group tokens come from the pragma text, so they are already legal
identifiers.

### Clock groups

A group separates clocks that have the same frequency but are not the same clock. Two
MAINs at 100 MHz with no group share `clk_100p0`; give one of them a group and it gets its
own port `clk_100p0_<group>`, a FIFO between them becomes an async FIFO, and the
constraints mark the two clocks as asynchronous.

Uses in the repository:

- [`include/dvi/dvi_pmod.c`](../include/dvi/dvi_pmod.c) runs
  `MAIN_MHZ_GROUP(dvi_pmod_shifted_clock, PIXEL_CLK_MHZ, delayed_146p25deg)`: a
  phase-shifted copy of the pixel clock.
- [`examples/stream_soc/eth/hardware/xil_temac.c`](../examples/stream_soc/eth/hardware/xil_temac.c)
  has two 25 MHz clocks from the Xilinx TEMAC, `CLK_MHZ_GROUP(xil_temac_rx_mac_aclk, 25.0, xil_temac_rx)`
  and `..._tx`, and MAINs on them with `MAIN_MHZ_GROUP(xil_temac_rx_module, 25.0, xil_temac_rx)`.
- [`examples/arty/src/eth/work_app.c`](../examples/arty/src/eth/work_app.c) uses
  `#pragma MAIN_GROUP rx_main xil_temac_rx` with no MHz; the MHz is inferred.
- The shared resource bus puts each host clock domain's wiring MAIN in a configurable
  group (`SHARED_RESOURCE_BUS_HOST_CLK_GROUP`).

### Synthesis-only targets: `MAIN_SYN_MHZ`

`SYN.GET_TARGET_MHZ(main)` returns the goal the tools and the throughput sweep use. When
the selected tool runs place and route (`SYN.TOOL_DOES_PNR()`), it returns `main_mhz`;
when only synthesis estimates are available it returns `main_syn_mhz`:

| Tool | Goal used |
|---|---|
| Quartus, open tools (nextpnr), Efinity, CC tools | `MAIN_MHZ` |
| Vivado, Gowin | `MAIN_MHZ` only with `DO_PNR == "all"`; the default (`None`) is synthesis only, so `MAIN_SYN_MHZ` |
| Diamond, PyRTL, DEVICE_MODELS | `MAIN_SYN_MHZ` |

`MAIN_SYN_MHZ` exists to ask synthesis for margin above the real clock.
[`examples/sdr/fm_radio.c`](../examples/sdr/fm_radio.c) sets `MAIN_MHZ sdr_wrapper 125.0`
and `MAIN_SYN_MHZ sdr_wrapper 147.0`: the clock port is `clk_125p0`, and a synthesis-only
Vivado run constrains it to 147 MHz.

The goal is kept per MAIN, but the constraint is per clock name.
`SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH` loops over the MAINs in pragma order and stores
each one's goal under its clock name, so when MAINs that share a clock have different
`MAIN_SYN_MHZ` values, the last one wins. Two MAINs on `clk_100p0`, one with
`MAIN_SYN_MHZ a 150.0`, give this for a synthesis-only Vivado run (*verified*, parsing only):

| Pragma order | `clocks.xdc` period for `clk_100p0` |
|---|---|
| `a` (150) first, then `b` | 100 MHz |
| `b` first, then `a` (150) | 150 MHz |

The sweep still judges each MAIN against its own goal (150 MHz for `a`) using the path the
tool reports for the clock. With place-and-route tools both orders give 100 MHz, because
`MAIN_MHZ` is used. See [section 15](#main_syn_mhz-on-a-shared-clock-depends-on-pragma-order).

The simulation backends take their clock periods from the same mapping (see
[section 13](#13-simulation-support)), so a synthesis-only tool also puts
`MAIN_SYN_MHZ` into generated testbench periods.

### Clock domain inference

`LOGIC.INFER_CLOCK_DOMAINS` fills in MAINs whose MHz is unknown. The C front end calls it
from `C_TO_LOGIC.GET_CLK_CROSSING_INFO`, during each code-generation pass of
`PARSE_FILE`. It repeats until nothing changes:

1. **Shared globals.** For each shared global (see
   [section 3](#3-same-domain-communication-shared-global-variables)) that is not an
   `ASYNC_WIRE`, it finds every MAIN whose call tree uses it
   (`LOGIC.RECURSIVE_FIND_MAIN_FUNCS`, walking the called-from graph up to a MAIN). It
   takes the first of those MAINs with a known MHz as the reference. Each other MAIN with
   no MHz, and with no group or the reference's group, gets the reference's MHz and group,
   and its synthesis MHz if that is unknown.
2. **Crossing variables**, only after a pass of step 1 changes nothing. For each crossing
   that is not an `ASYNC_WIRE`, a MAIN with no MHz on one side takes the other side's
   (MHz, group) when the other side has a known MHz. The group test compares against the
   groups of the MAINs on the same side that already have a MHz, not against the MAIN's
   own group, which is replaced.

Each assignment prints a line such as:

```
Matching clock domain: main function observer based on shared global variable last_value used with clock domain for main function consumer @ 100.0 MHz, Group: other_group
```

The line is not printed for MAINs marked `FUNC_WIRES`. Those are usually library wiring
MAINs, so their inference is silent.

Inference is what places most library MAINs, which are declared with a bare `MAIN(...)`:
the LED port modules in [`include/leds/led0_3_ports.c`](../include/leds/led0_3_ports.c),
the `GLOBAL_STREAM_FIFO` wiring MAINs, the `global_func_inst.h` pipeline instances, the
register MAINs of `DECL_INPUT_REG` / `DECL_OUTPUT_REG`, and the debug-probe processes.

Inference assigns; conflicts are reported elsewhere. Conflicting domains on one shared
global are caught later by the VHDL top-level writer (see
[section 3](#3-same-domain-communication-shared-global-variables)). A crossing written or
read from two different domains makes the loop run forever (see
[section 15](#inference-never-ends-when-a-crossing-side-spans-two-clocks)). A MAIN that nothing gives a clock keeps
`None`: its clock port is `clk_None`, the constraints give it `INF_MHZ` (1000 MHz) with
`WARNING: No frequency associated with clock clk_None. Missing MAIN_MHZ pragma? ...`, and
the sweep has no goal for it.

### User clocks: `CLK_MHZ` and `CLK_MHZ_GROUP`

`CLK_MHZ(w, mhz)` (`#pragma CLK_MHZ w mhz`) and `CLK_MHZ_GROUP(w, mhz, grp)` declare
that the global `uint1_t w` carries a clock. The compiler records `clk_mhz[w]` and
`clk_group[w]` and builds the clock name `clk_<mhz>[_<grp>]`. A MAIN whose own
(MHz, group) produces the same name runs on this signal instead of a top-level clock
port. The rules, all in `VHDL.WRITE_MULTIMAIN_TOP`:

- The clock becomes an internal signal with `syn_keep`, `keep` and `dont_touch`
  attributes, not a top-level input port.
- It is driven by the single function instance that writes `w`:
  `clk_1p0 <= module_to_global.clk_gen.the_slow_clock(0);`. If no function writes `w` and
  `w` is a top-level input (`DECL_INPUT`), the input drives it: `clk_25p0 <= pll_clk(0);`.
- Errors: a clock wire that is also a crossing variable (`User defined clock wire w should
  not be marked as clock crossing! Use simple global wires instead.`), more than one writer
  function or instance, or no driver at all (`User defined clock w is not driven/assigned
  anywhere?`).
- A clock wire always counts as shared (`LOGIC.GLOBAL_VAR_IS_SHARED`). It can also be
  read as data, but a reader in another domain fails the shared-global clock check
  unless the wire is an `ASYNC_WIRE`. The wiki's Pragmas page calls it a "Good idea to
  mark as `ASYNC_WIRE` as well unless otherwise needed."
- Constraints use `get_nets` instead of `get_ports` for these clocks (see
  [Clock constraints](#clock-constraints)).

Three common uses:

- **A divided clock generated in logic**, [`examples/internal_clocks.c`](../examples/internal_clocks.c):
  `clk_gen` at 100 MHz toggles `the_slow_clock`, declared `CLK_MHZ(the_slow_clock, 1.0)`,
  and `MAIN_MHZ(main, 1.0)` runs on it.
- **Renaming a board clock pin.** By default a clock port is named `clk_<MHz>`. To use a
  board's own pin name, declare the pin as an input and promote it, as in
  [`examples/pico-ice/ice_makefile_pipelinec/top.h`](../examples/pico-ice/ice_makefile_pipelinec/top.h):

  ```c
  DECL_INPUT(uint1_t, pll_clk)
  CLK_MHZ(pll_clk, PLL_CLK_MHZ)
  ```

  The top level then has `pll_clk : in unsigned(0 downto 0)` and no `clk_<MHz>` port.
  [`include/net/rmii_wires.c`](../include/net/rmii_wires.c) does the same through a wiring
  MAIN: `rmii_clk = RMII_CLK_WIRE;` with `CLK_MHZ(rmii_clk, 50.0)`.
- **Clocks produced by an IP block.** The TEMAC example writes the IP's `rx.mac_aclk` and
  `tx.mac_aclk` outputs to two `CLK_MHZ_GROUP` wires.

**A clock passed in as a MAIN argument.** Before `DECL_INPUT` existed, a clock pin was
brought in as an argument of a wiring MAIN and copied to the clock wire (the pattern in
[#137](https://github.com/JulianKemmerer/PipelineC/issues/137) and
[#138](https://github.com/JulianKemmerer/PipelineC/issues/138)):

```c
uint1_t the_clock;
CLK_MHZ(the_clock, 25.0)
MAIN_MHZ(test, 25.0)
#pragma FUNC_WIRES test
void test(uint1_t clock) { the_clock = clock; }
```

This builds, but the synthesis top registers every MAIN input on that MAIN's clock, and
that clock is the input itself (*verified*, ECP5 part, `--no_synth`):

```vhdl
clk_25p0 <= module_to_global.test.the_clock(0);
 process(clk_25p0) is
 begin
  if rising_edge(clk_25p0) then
   test_0CLK_de264c78_clock_input_reg <= test_clock;
```

so in PipelineC's own timing runs the clock goes through a register clocked by its own
output. Built with Quartus (*verified*, Quartus Prime Lite 20.1, Cyclone V, `--comb`), the
timing analyzer finds no user clock (next paragraph), derives one on that register and
warns about the loop:

```
Info (332105): create_clock -period 1.000 -name test_0CLK_de264c78_clock_input_reg[0] test_0CLK_de264c78_clock_input_reg[0]
Warning (332191): Clock target test_0CLK_de264c78_clock_input_reg[0] of clock test_0CLK_de264c78_clock_input_reg[0] is fed by another target of the same clock.
```

The final top has no IO registers, so the generated hardware is not affected.
`DECL_INPUT` + `CLK_MHZ`, as above, avoids the register.

**Quartus and `get_nets`.** For user clocks the constraint is `create_clock ... [get_nets
{clk_<...>}]`. Vivado finds the kept internal net. Quartus does not, for a clock generated
in logic or for one promoted from a `DECL_INPUT` pin (*verified*, both on Cyclone V with
Quartus Prime Lite 20.1):

```
Warning (332174): Ignored filter at clocks.sdc(1): clk_25p0 could not be matched with a net
Warning (332049): Ignored create_clock at clocks.sdc(1): Argument <targets> is an empty collection
Info (332142): No user constrained base clocks found in the design. Calling "derive_clocks -period 1.0"
    Info (332105): create_clock -period 1.000 -name pll_clk[0] pll_clk[0]
```

PipelineC's timing script (`report_timing -npaths 1 -from_clock <clock>` for each clock
name) then fails for that clock (`clk_25p0 could not be matched with a clock`). In both
test designs the user clock was the only clock, so the report held no paths and
`QUARTUS.ParsedTimingReport` stopped the build with `Bad synthesis log?` and exit status 255.
With other clocks present the build would continue without any path for the user clock's
domain. Either way PipelineC cannot time a user clock on Quartus
([#137](https://github.com/JulianKemmerer/PipelineC/issues/137), open; the thread's
workaround is the full hierarchical name of the register that drives the clock). See
[section 15](#quartus-does-not-find-user-clocks).

## 3. Same-domain communication: shared global variables

A global is *shared* when more than one function uses it, or when it is a top-level
`INPUT`/`OUTPUT` wire, a `CLK_MHZ` clock, or part of an `INST_ARRAY`
(`LOGIC.GLOBAL_VAR_IS_SHARED`). Shared globals are how MAINs on one clock talk to each
other:

- One function writes it, from one instance (`ERROR: Cannot write to global variable in
  more than one function!` from `PARSE_FILE`, `More than one instance trying to write to
  global` from the top-level writer). Readers see the value as it is at the end of the
  writer function's execution.
- In VHDL the writer's `module_to_global` field is assigned to each reader's
  `global_to_module` field, under `-- Directly connected global wires` in the top level.
- **All writer and reader instances must be on one clock.** `VHDL.WRITE_MULTIMAIN_TOP`
  collects the clock of every instance and raises, unless the global is an `ASYNC_WIRE`:

  ```
  Exception: Cannot have multiple clock domains for shared global the_global! {'50p0', '100p0'} {...instances...}
  ```

- `INST_ARRAY` globals (several writer instances gathered into an array, or one array
  fanned out to several readers) have the same rule, `Cannot have multiple clock domains
  for write shared instance array global ...`, and that check ignores `ASYNC_WIRE`.
- Top-level IO wires (`DECL_INPUT`, `DECL_OUTPUT`) have no clock of their own, but the
  same rule applies: every function that uses one must be on one clock. The registered
  versions, `DECL_INPUT_REG` and `DECL_OUTPUT_REG`, add a `FUNC_WIRES` MAIN holding the
  register, and inference puts that MAIN on its users' clock. Asynchronous inputs are
  usually registered through a synchronizer in the reading function (see
  [`cdc.h`](#synchronizer-macros-cdch)).

**Timing.** A shared global is a wire, not a register: the reader gets the writer's value
in the same clock cycle. The connection is taken from the input side of the writer's
registers ("D"), not their output ("Q"); [#73](https://github.com/JulianKemmerer/PipelineC/issues/73)
records that choice. With

```c
#pragma MAIN_MHZ write_main 100.0
#pragma MAIN_MHZ read_main 100.0
uint32_t the_global;
void write_main() { the_global += 1; }
uint32_t read_main() { static uint32_t acc; acc += the_global; return acc; }
```

`read_main` adds 1 in the first cycle, because it sees `the_global` after the increment.
Before shared globals, `the_global` was effectively private to `write_main`, and moving it
needed the crossing wires of section 7. In timing terms, the logic in front of the writer's
assignment and the logic behind the reader's use form one combinational path through two
MAIN entities. Synthesis times it as an ordinary path on the shared clock, and the sweep
can charge it to both MAINs (see [Timing reports and the sweep](#timing-reports-and-the-sweep)).

Moving data to another clock needs a crossing (section 4) or `ASYNC_WIRE` (section 8).

## 4. Clock crossing variables

A clock crossing variable is a global that the code never reads or writes directly. It is
used only through a write function and a read function named after it. The crossing
machinery is older than shared globals and also provides the same-clock wires of
[section 7](#7-same-clock-crossing-wires-and-wireh).

### How a crossing is recognized

`C_TO_LOGIC.GET_CLK_CROSSING_INFO` searches the preprocessed C text with regular
expressions for calls `\w+_WRITE\s?\(`, `\w+_WRITE_[0-9]+\s?\(`, `\w+_READ\s?\(` and
`\w+_READ_[0-9]+\s?\(`. The variable name is everything before the first `_READ`, or if
there is none the first `_WRITE` (`LOGIC.CLK_CROSS_FUNC_TO_VAR_NAME`), and the call
counts only if that name is a global variable. Consequences:

- Naming is load-bearing: a call `<global>_READ(...)` is taken as a crossing even if it was
  meant as an ordinary function, and a variable whose own name contains `_READ` or
  `_WRITE` is cut at the wrong place.
- If only the write function is called, a read function name is made up by replacing
  `_WRITE` with `_READ`, giving a crossing with an unconnected read side.
- The search also matches function *definitions*. The functions that `global_fifo.h`
  declares are therefore always found, so a declared FIFO is a crossing even if nothing
  calls it. If its write function is never called, writing the top level fails (see
  [Unused and one-sided FIFOs](#unused-and-one-sided-fifos)).
- The MAINs on each side are found from the functions that call the read and write
  functions, walking up the call graph. Functions that have an FSM-style `_FSM` copy are
  skipped; the copy is searched instead.

When a function definition with such a name is parsed, `GEN_CODE_POST_PARSE_LOGIC_ADJUST`
sets `is_clock_crossing` and `uses_nonvolatile_state_regs` on its `Logic`. Its C body is
never used: in VHDL, the call becomes connections to the crossing's entity in the top
level. Using the variable itself stops the build with
`Looks like you are using a clock crossing variable ' v ' directly instead of with READ and
WRITE functions?`.

### Kinds of crossing

`GET_CLK_CROSSING_INFO` picks the kind in this order and stores it in a
`LOGIC.ClkCrossVarInfo`:

| Condition | Write size, read size | `flow_control` | Result |
|---|---|---|---|
| `v` is an `ASYNC_WIRE` | 1, 1 | no | unsynchronized wire (section 8) |
| a read or write function name ends in `_<N>` | from the two `<N>` | yes | FIFO (section 5) |
| otherwise, same clock | 1, 1 | no | same-clock wire (section 7) |
| otherwise, different MHz | fast side 1, slow side `R = ceil(fast/slow)` | no | volatile ratio crossing (section 6) |

For the last two rows two checks follow. A non-`volatile` variable must have identical
MHz and group on both sides, and any such crossing must have an integer ratio and one
group (this second check is not limited to `volatile` variables). Both checks are meant to
print a warning and continue, but the warning text references an undefined variable, so a
failing check stops parsing with `NameError` (see
[section 15](#crossing-checks-crash-with-nameerror)).

### The generated crossing header

The original syntax declares the variable and includes a header named after it, which the
compiler writes:

```c
volatile uint64_s fast_to_slow;
#include "clock_crossing/fast_to_slow.h" // Auto generated
```

The output directory is on the preprocessor include path
(`C_TO_LOGIC.GET_CPP_INCLUDES_LIST`), so the include resolves to
`<out_dir>/clock_crossing/fast_to_slow.h`. `PARSE_FILE` builds the header in passes:

1. The header is missing, so `GEN_EMPTY_CLOCK_CROSS_HEADERS` writes a placeholder
   (`#define v_RATIO 0`, `typedef int v_write_t;`, `typedef int v_read_t;`) so the file
   can be preprocessed.
2. The pragmas, call graph and global variables are parsed, and
   `GET_CLK_CROSSING_INFO` decides the kind and sizes.
3. `GEN_CLOCK_CROSS_HEADERS` writes the real header for every crossing variable. A
   non-flow-control header may need `<T>_array_N_t.h`, which the array-type generator then
   writes. The loop repeats until no new file is needed.

For the 100 MHz / 25 MHz crossing of [`examples/clock_crossing.c`](../examples/clock_crossing.c)
the header is:

```c
#pragma once
#include "uintN_t.h"
#define fast_to_slow_RATIO 4
#include "uint64_s_array_N_t.h"
#define fast_to_slow_write_t uint64_s_array_1_t
#define fast_to_slow_read_t uint64_s_array_4_t

// Clock cross write
void fast_to_slow_WRITE(uint64_s_array_1_t in_data)
{
  // TODO
}

// Clock cross read
uint64_s_array_4_t fast_to_slow_READ()
{
  // TODO
}
```

`T_array_N_t` is a generated struct with one field, `T data[N]`, because C cannot return
arrays. For a flow-controlled variable, `uint8_t f2s[16];` used with `f2s_WRITE_2` and
`f2s_READ_2`, the header holds structs instead:

```c
#pragma once
#include "uintN_t.h"
#define f2s_RATIO 1
typedef struct f2s_write_t
{
uint1_t ready;
}f2s_write_t;
typedef struct f2s_read_t
{
uint8_t data[2];
uint1_t valid;
}f2s_read_t;

// Clock cross write
f2s_write_t f2s_WRITE_2(uint8_t write_data[2], uint1_t write_enable)
{
  // TODO
}

// Clock cross read
f2s_read_t f2s_READ_2(uint1_t read_enable)
{
  // TODO
}
```

The bodies are stubs; only the signatures matter. An include of the older form
`"<var>_clock_crossing.h"` (no directory) stops the build with instructions to switch to
`#include "clock_crossing/<var>.h"` and drop the `<type>_array_N_t.h` include.

[`include/global_fifo.h`](../include/global_fifo.h) avoids the generated header for FIFOs:
its macros declare the variable, the structs and the two functions themselves (see
[Declaring a FIFO](#declaring-a-fifo)). The compiler recognizes those functions by name
in the same way. `GEN_CLOCK_CROSS_HEADERS` still writes `clock_crossing/<name>.h` for
these FIFOs; nothing includes it.

The header generator's own checks stop the build: a FIFO variable with more than one
dimension prints `Only single dim in flow control crossing!` and exits with status 0, one
with no dimension prints `No async fifo depth provided for var?:` and exits with status
255.

### Rules and checks

- The variable must be a global.
- All write-side instances must be on one clock, and so must all read-side instances
  (`Cannot have multiple clock domains on the read side of clock crossing v!`, and the same
  for the write side, raised while writing the top level). If the conflict is already
  visible during inference, the build never gets that far (see
  [section 15](#inference-never-ends-when-a-crossing-side-spans-two-clocks)).
- One write instance, except for arbitrated pairs (section 7). With more, the build prints
  `More than one use of <write func>`, the instances and `Missing #pragma ID_INST?`, then
  stops. `#pragma ID_INST v path` keeps only the write instances whose instance path
  contains `path` (`/` separated, as in `my_inst[3]`).
- Flow-controlled crossings also allow only one read instance
  (`More than one use of flow controlled clock crossing func <read func>`). Other crossings
  may be read from several instances; each gets the same value.
- A crossing whose read function is never instantiated is not instantiated in the top
  level.
- FIFO variables must be one-dimensional arrays whose dimension is the depth, and the
  read and write sizes must be equal (`Only equal read and write sizes for async fifos for
  now, TODO!`).

## 5. Async FIFOs

### Declaring a FIFO

**`global_fifo.h` macros** (the normal way):

```c
#include "global_fifo.h"
GLOBAL_FIFO_WIDTH_DEPTH(uint8_t, fast_to_slow, 2, 4) // 4 entries of 2 x uint8_t
GLOBAL_FIFO(uint8_t, my_fifo, 16)                    // GLOBAL_FIFO_WIDTH_DEPTH(uint8_t, my_fifo, 1, 16)
```

`GLOBAL_FIFO_WIDTH_DEPTH(data_t, name, W, DEPTH)` expands to:

```c
data_t name[DEPTH];
typedef struct name_write_t { uint1_t ready; } name_write_t;
typedef struct name_read_t { data_t data[W]; uint1_t valid; } name_read_t;
#pragma FUNC_WIRES name_WRITE_W
name_write_t name_WRITE_W(data_t write_data[W], uint1_t write_enable) { ... }
#pragma FUNC_WIRES name_READ_W
name_read_t name_READ_W(uint1_t read_enable) { ... }
```

[`include/clock_crossing.h`](../include/clock_crossing.h) defines
`ASYNC_CLK_CROSSING_WIDTH_DEPTH` and `ASYNC_CLK_CROSSING` as aliases. The width is part
of the function names, so the examples define width-independent aliases such as
`#define fast_to_slow_WRITE_N fast_to_slow_WRITE_2`
([`examples/async_clock_crossing.c`](../examples/async_clock_crossing.c)).

**Generated header** (the older way): declare the array and include the header, then
call the sized functions. [`include/vga/vga_pmod_async_pixels_fifo.c`](../include/vga/vga_pmod_async_pixels_fifo.c):

```c
vga_fifo_word_t vga_async_fifo[VGA_ASYNC_FIFO_DEPTH];
#include "clock_crossing/vga_async_fifo.h"
...
vga_async_fifo_write_t async_fifo = vga_async_fifo_WRITE_1(async_fifo_wr_data, wr_en);
...
vga_async_fifo_read_t fifo_read = vga_async_fifo_READ_1(rd_en);
```

### Write and read semantics

```c
name_write_t name_WRITE_W(data_t write_data[W], uint1_t write_enable); // .ready
name_read_t  name_READ_W(uint1_t read_enable);                          // .data[W], .valid
```

- A write happens in a cycle where `write_enable` and `.ready` are both 1. `.ready` does
  not depend on `write_enable` in the same cycle, so `write_enable` may be computed from
  it.
- Reads are first-word-fall-through. `.data` and `.valid` show the head of the FIFO, and
  the head is removed in a cycle where `read_enable` and `.valid` are both 1. `.valid`
  does not depend on `read_enable`.
- Each entry holds `W` elements as one word; `DEPTH` counts entries.
- Both calls have a clock enable: a call inside an `if` only acts when the branch runs.
  The generated FIFO gates its inputs with them (`write_enable AND in_clk_en`,
  `read_enable AND out_clk_en`).
- The async FIFOs hold `.ready` and `.valid` low until their power-on reset clears, one
  edge after configuration in each domain (longer for XPM, which also waits for
  `wr_rst_busy` and `rd_rst_busy`). Nothing else resets a FIFO.
- The two calls may be in any functions under any MAINs, including the same MAIN.

### Which FIFO hardware is generated

`VHDL.WRITE_CLK_CROSS_ENTITIES` collects the clock names of every MAIN on both sides.
More than one distinct name makes the FIFO asynchronous. For an async FIFO the
implementation depends on `SYN.SYN_TOOL`, set from the part (`PART` pragma or `--part`)
and `--syn_tool`. If no tool is chosen yet, it calls `SYN.PART_SET_TOOL(part)`; a
design without a part then falls back to PyRTL when that is installed, which gives the
built-in FIFO.

| Clocks | Tool | Implementation | Minimum depth | Depth used |
|---|---|---|---|---|
| one clock | any | built-in `pipelinec_fifo_fwft` | 2 | `2**ceil(log2(DEPTH))` |
| different clocks | Vivado | `xpm_fifo_async` | 16 | `DEPTH` as given, as `FIFO_WRITE_DEPTH`; must be a power of two |
| different clocks | any other, or none | built-in `pipelinec_async_fifo_fwft` | 4 | `2**ceil(log2(DEPTH))` |

A smaller depth is raised with a warning, for example
`WARNING: fast_to_slow Xilinx async fifo depth increased to minimum allowed = 16`. The
FIFO word is the whole `W`-element array packed into one `std_logic_vector`
(`<type>_to_slv` / `slv_to_<type>` from `c_structs_pkg`).

The XPM depth is not rounded. A depth of 20 on an Artix-7 part (*verified*, Vivado
2019.2, `--comb`) generates `FIFO_WRITE_DEPTH => 20` and synthesis fails with
`ERROR: [Synth 8-6058] Synth Error: [XPM_FIFO 1-4] FIFO_WRITE_DEPTH (20) value specified
is non-power of 2, but this release of XPM_FIFO supports configurations having the fifo
write depth set to power of 2.` The same source builds with the built-in FIFOs, which
round up. So a non-power-of-two depth works or fails depending on the part.

The **XPM variant** adds `library xpm; use xpm.vcomponents.all;` and instantiates
`xpm_fifo_async` with `CDC_SYNC_STAGES => 2`, `FIFO_MEMORY_TYPE => "auto"`,
`READ_MODE => "fwft"`, `FIFO_READ_LATENCY => 0`, `USE_ADV_FEATURES => "1000"` (the
`data_valid` output), `RELATED_CLOCKS => 0` and `rst => '0'`. Around it, one power-on
register per domain (`wr_power_on_reset`, `rd_power_on_reset`, initialized to `'1'` and
cleared on the first edge) and the `*_rst_busy` outputs gate the write enable, read enable,
`ready` and `valid`. The XPM macros are SystemVerilog shipped with Vivado, so only Vivado,
or a simulator set up with Xilinx's libraries, can elaborate this variant. The wrapper
around the instance, from the Artix-7 build of `examples/async_clock_crossing.c`'s FIFOs
(two `uint8_t` per word):

```vhdl
    din_slv <= uint8_t_2_to_slv(write_data);
    rd_return_output.data <= slv_to_uint8_t_2(dout_slv);
wr_power_on_reset <= '0' when rising_edge(in_clk);
fifo_wr_en <= write_enable(0) and in_clk_en(0) and not wr_rst_busy and not wr_power_on_reset;
wr_return_output.ready(0) <= not full and not wr_rst_busy and not wr_power_on_reset;
rd_power_on_reset <= '0' when rising_edge(out_clk);
fifo_rd_enable <= read_enable(0) and not rd_rst_busy and not rd_power_on_reset and out_clk_en(0);
rd_return_output.valid(0) <= valid and not rd_rst_busy and not rd_power_on_reset;
rd_return_output.data <= slv_to_uint8_t_2(dout_slv);
```

The other generics are fixed: `DOUT_RESET_VALUE => "0"`, `ECC_MODE => "no_ecc"`,
`FULL_RESET_VALUE => 0`, `PROG_EMPTY_THRESH => 10`, `PROG_FULL_THRESH => 10`,
`RD_DATA_COUNT_WIDTH => 1`, `WR_DATA_COUNT_WIDTH => 1`, `SIM_ASSERT_CHK => 0`,
`WAKEUP_TIME => 0`, and both data widths are `<type>_SLV_LEN`. Only `data_valid`, `dout`,
`full`, `rd_rst_busy` and `wr_rst_busy` are connected; the almost-full, programmable and
count outputs are left in comments.

### The built-in FIFOs

The compiler copies [`src/vhdl/`](../src/vhdl/) to `<out_dir>/built_in/` on every build,
and `SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP` always lists both files first.

**`pipelinec_async_fifo_fwft`** ([source](../src/vhdl/pipelinec_async_fifo_fwft.vhd)), the
FIFO used for clock crossings on every tool except Vivado. It is adapted from Alex
Forencich's `axis_async_fifo`.

- Ports: `in_clk`, `valid_in`, `ready_out`, `data_in` on the write side; `out_clk`,
  `valid_out`, `ready_in`, `data_out` on the read side. Generics `DATA_WIDTH` and
  `DEPTH_LOG2`.
- Binary pointers with Gray-coded copies. Each Gray pointer crosses through two
  registers in the other domain (`rd_ptr_gray_sync1/2_reg`, `wr_ptr_gray_sync1/2_reg`).
  Full and empty compare the local Gray pointer with the synchronized one.
- One power-on reset register per domain (`in_por_rst`, `out_por_rst`), initialized to
  `'1'` and cleared on the first edge. There is no reset port, so the FIFO relies on
  register initial values.
- The output is registered (first word fall through, one output stage).
- No VHDL-2008 features (it uses `xor_reduce` and an internal copy of `ready_out`) so
  Quartus Lite can compile it.
- The synchronizer registers carry no attributes such as `ASYNC_REG` (the
  `SHREG_EXTRACT` attributes of the original are commented out), and PipelineC writes no
  CDC constraints for them.
- The memory is written in the `in_clk` process and read into the output register in
  the `out_clk` process, the shape synthesis tools infer as a dual-clock block or
  distributed RAM.
- Leftovers of the original's frame mode are still declared but unused or constant:
  `wr_ptr_commit_reg`, `wr_ptr_update_*`, `wr_ptr_conv_reg`, `rd_ptr_conv_reg`,
  `mem_read_data_valid_reg`.

**`pipelinec_fifo_fwft`** ([source](../src/vhdl/pipelinec_fifo_fwft.vhd)), the
single-clock FIFO, adapted from `axis_fifo`. It has one `clk`, `ready_out = not full`, a
registered first-word-fall-through output, and an optional `clock_enable` port that the
crossing does not use (it gates `valid_in` and `ready_in` instead). The same entity backs
`FIFO_FWFT` in [`include/fifo.h`](../include/fifo.h), the local (non-global) FIFO macro,
and Pypeline's `make_fifo` ([`include/pypeline/fifo.py`](../include/pypeline/fifo.py)).

### Latency and capacity

Measured with GHDL 4.0.0-dev (mcode) on the two built-in entities, 8-bit data, by a
scratch testbench that writes one word, stalls the reader to fill the FIFO, then pops one
word (*verified*):

| Entity | `DEPTH_LOG2` | Clocks (write → read) | `valid_out` rises after | Words held with the reader stalled | `ready_out` returns after a pop |
|---|---|---|---|---|---|
| `pipelinec_async_fifo_fwft` | 2 | 50 → 25 MHz | the 3rd read-clock edge after the write edge | 5 | the 2nd write-clock edge after the pop edge |
| `pipelinec_async_fifo_fwft` | 2 | 25 → 50 MHz | 3rd read-clock edge | 5 | 2nd write-clock edge |
| `pipelinec_async_fifo_fwft` | 2 | 50 → 50 MHz (two in-phase clocks) | 3rd read-clock edge | 5 | 2nd write-clock edge |
| `pipelinec_async_fifo_fwft` | 4 | 50 → 25 MHz | 3rd read-clock edge | 17 | 2nd write-clock edge |
| `pipelinec_fifo_fwft` | 2 | one clock | the 1st edge after the write edge | 5 | the 1st edge after the pop edge |
| `pipelinec_fifo_fwft` | 4 | one clock | 1st edge | 17 | 1st edge |

- **Write to valid:** two read-clock edges for the Gray pointer synchronizer, one more to
  load the output register. Counted in read-clock cycles from the write edge, the latency
  is 3 cycles plus the phase of the read clock at the write. The single-clock FIFO gives
  the familiar 2-cycle push-to-valid: write cycle, memory cycle, valid.
- **Capacity:** `2**DEPTH_LOG2` words in memory plus one in the output register, so one
  more than the "Depth used" column of [the table above](#which-fifo-hardware-is-generated).
- **Pop to ready:** the read pointer crosses back through two write-clock registers. A
  writer that keeps a full FIFO busy therefore sees `ready` low for two of its own cycles
  after each pop.
- **Power-on:** the async FIFO holds `ready_out` low until its write-side power-on
  register clears at the first write-clock edge, and `valid_out` low until the read-side
  one clears. The single-clock FIFO's `ready_out` is just `not full`; its power-on
  register does not gate it.
- Throughput is one word per cycle on each side.

The XPM FIFO was not measured; Xilinx's UG974 gives its FWFT latencies and how many words
it holds for a given `FIFO_WRITE_DEPTH`. Its synchronizers are `CDC_SYNC_STAGES => 2`
deep, like the built-in FIFO's.

### Unused and one-sided FIFOs

A FIFO declared with the `global_fifo.h` macros is a crossing even when nothing calls its
functions (see [How a crossing is recognized](#how-a-crossing-is-recognized)). What
happens depends on which side is called (*verified*, ECP5 part, `--no_synth`):

| Write function called | Read function called | Result |
|---|---|---|
| no | no | `KeyError: 'unused_fifo_WRITE_1'` from `VHDL.WRITE_MULTIMAIN_TOP` (`write_func_insts = parser_state.FuncToInstances[write_func]`) |
| no | yes | the same `KeyError` for the write function |
| yes | no | builds. `clk_cross_<name>` is written to `clk_cross_entities.vhd` but not instantiated, and nothing drives the writer's `global_to_module.<main>.<name>_WRITE_1_return_output`, so its `ready` is undriven |

Library code avoids these cases by always calling both sides from wiring MAINs
(`GLOBAL_STREAM_FIFO`).

### Stream FIFOs: `GLOBAL_STREAM_FIFO`

`GLOBAL_STREAM_FIFO(data_t, name, DEPTH)` in `global_fifo.h` wraps a width-1 FIFO in
valid/ready stream wires, so neither side calls the FIFO functions:

```c
#include "global_fifo.h"
DECL_STREAM_TYPE(uint8_t)            // stream(uint8_t) == uint8_t_stream_t {data, valid}
GLOBAL_STREAM_FIFO(uint8_t, my_fifo, 16)
// Globals for the user:
//   stream(uint8_t) my_fifo_in;       uint1_t my_fifo_in_ready;   (write side)
//   stream(uint8_t) my_fifo_out;      uint1_t my_fifo_out_ready;  (read side)
```

It expands to:

- `GLOBAL_FIFO(data_t, name_FIFO, DEPTH)`, so the FIFO is `name_FIFO`, with functions
  `name_FIFO_WRITE_1` and `name_FIFO_READ_1`. In VHDL the instance is labeled `name_FIFO`
  and its entity is `clk_cross_name_FIFO`.
- The four globals above.
- `MAIN(name_wr_stream_in)`, which writes `name_in` into the FIFO and drives
  `name_in_ready`, and `MAIN(name_rd_stream_out)`, which reads the FIFO with
  `name_out_ready` and drives `name_out`. Both are `FUNC_WIRES` and have no frequency:
  each takes its clock from the user MAINs that use its wires
  ([inference](#clock-domain-inference)). The FIFO is therefore asynchronous exactly when
  the writer and reader MAINs are on different clocks.

`stream(T)` and `DECL_STREAM_TYPE` come from [`include/stream/stream.h`](../include/stream/stream.h),
which predefines `stream(uint32_t)`.

Three variants add `SKID_BUF` registers (also from `stream.h`) to break the combinational
ready path. Each wraps an inner `GLOBAL_STREAM_FIFO` named `no_skid_name`, keeps the same
four user globals, and uses the wiring MAINs `name_wr_skid_in` and `name_rd_skid_out`:

| Macro | Skid buffer on |
|---|---|
| `GLOBAL_STREAM_FIFO_SKID_BUFF` | both sides |
| `GLOBAL_STREAM_FIFO_SKID_IN_BUFF` | write side only |
| `GLOBAL_STREAM_FIFO_SKID_OUT_BUFF` | read side only |

The skid registers run in the domain inference gives each wiring MAIN.

### FIFO calls inside auto-pipelined MAINs

A crossing function is never pipelined itself (`Logic.CAN_HAVE_ADDED_LATENCY` is false
for it, and `SWEEP.WHY_NOT_SLICEABLE` reports `"clock_crossing"`). It has zero delay in
the timing model (`SYN.LOGIC_IS_ZERO_DELAY`). The *calling* MAIN can still be
auto-pipelined if it is otherwise stateless: the crossing's state does not count against
its caller. Each call's connections then sit in the pipeline stage where its inputs are
ready. In a test design with a stateless 250 MHz MAIN between two FIFOs, the sweep added
one slice and the generated stage process contains:

```vhdl
   if STAGE = 0 then
     module_to_global.in_fifo_READ_1_CLOCK_ENABLE <= VAR_in_fifo_READ_1_..._CLOCK_ENABLE;
     module_to_global.in_fifo_READ_1_read_enable <= VAR_in_fifo_READ_1_..._read_enable;
     VAR_in_fifo_READ_1_..._return_output := global_to_module.in_fifo_READ_1_return_output;
   ...
   elsif STAGE = 1 then
     module_to_global.out_fifo_WRITE_1_CLOCK_ENABLE <= VAR_out_fifo_WRITE_1_..._CLOCK_ENABLE;
     module_to_global.out_fifo_WRITE_1_write_data <= VAR_out_fifo_WRITE_1_..._write_data;
     module_to_global.out_fifo_WRITE_1_write_enable <= VAR_out_fifo_WRITE_1_..._write_enable;
     VAR_out_fifo_WRITE_1_..._return_output := global_to_module.out_fifo_WRITE_1_return_output;
```

The read happens in stage 0 and the write in stage 1. Nothing relates the two
handshakes: the write's `.ready` is seen a cycle after the read has already consumed its
element. A MAIN whose read enable depends on the write side's ready needs state or
`FEEDBACK`, and then it is not pipelined. Library code keeps FIFO handshakes in small
wiring MAINs, as `GLOBAL_STREAM_FIFO` does, and puts pipelines behind the valid/ready
instance macros of [`include/global_func_inst.h`](../include/global_func_inst.h), which
sit on one clock.

## 6. Integer-ratio volatile crossings

The wiki marks this mechanism experimental and old. A `volatile` global without
flow control crosses between two clocks whose frequencies are integer multiples, with the
slow side moving `R` elements per cycle:

```c
#pragma MAIN_MHZ fast 100.0
#pragma MAIN_MHZ slow 25.0
volatile uint64_s fast_to_slow;               // R = 4
#include "clock_crossing/fast_to_slow.h"

// in fast():  one element per fast cycle
fast_to_slow_write_t to_slow_array;          // uint64_s_array_1_t
to_slow_array.data[0] = to_slow;
fast_to_slow_WRITE(to_slow_array);

// in slow():  four elements per slow cycle
fast_to_slow_read_t from_fast_array = fast_to_slow_READ();   // uint64_s_array_4_t
for(i=0;i<fast_to_slow_RATIO;i+=1) { ... from_fast_array.data[i] ... }
```

([`examples/clock_crossing.c`](../examples/clock_crossing.c).) The sizes come from the
`MAIN_MHZ` values: `R = ceil(fast/slow)`, the fast side moves 1 element and the slow side
`R`. The header defines `v_RATIO`.

Semantics: an element the writer did not provide, because its write call was
clock-disabled, arrives as all zeros (`T_NULL`). That is the "volatile" part, and why
the example's `uint64_s` carries its own `valid` bit. The read side has no clock
enable.

Hardware (`clk_cross_<v>` in `clk_cross_entities.vhd`, constants `CLK_RATIO` and
`CLK_RATIO_MINUS1`):

- **Fast to slow.** In the fast domain, a shift register (`slow_array_r`,
  `slow_array_valids_r`) takes one element per fast edge, valid when `in_clk_en` was set.
  A counter `fast_clk_counter_r`, initialized to `R-1`, copies the `R` collected elements
  to `o_fast_r` on each rollover, zeroing invalid ones. The slow domain registers
  `o_fast_r` into `o_slow_r`.
- **Slow to fast.** The slow domain registers the input array and its valid
  (`i_slow_r`, `i_slow_valid_r`). In the fast domain the counter reloads `slow_array_r`
  from it on each rollover and shifts one element out per fast edge into `o_fast_r`.

The fast-domain process of `clk_cross_fast_to_slow` for the example (`R` = 4, from
`examples/clock_crossing.c`):

```vhdl
      constant CLK_RATIO : integer := 4;
      constant CLK_RATIO_MINUS1 : integer := 3;
      signal fast_clk_counter_r : integer range 0 to CLK_RATIO_MINUS1 := CLK_RATIO_MINUS1;
      ...
      process(in_clk) is
      begin
      if rising_edge(in_clk) then
        -- Always shifting in serial fast data
        for i in 0 to 2 loop
          slow_array_r.data(i) <= slow_array_r.data(i+1);
          slow_array_valids_r(i) <= slow_array_valids_r(i+1);
        end loop;
        slow_array_r.data(CLK_RATIO_MINUS1) <= in_data.data(0);
        slow_array_valids_r(CLK_RATIO_MINUS1) <= in_clk_en(0);
        -- Counter roll over is slow clk enable logic in fast domain
        if fast_clk_counter_r = CLK_RATIO_MINUS1 then
          fast_clk_counter_r <= 0;
          -- Output datas null by default
          for i in 0 to CLK_RATIO_MINUS1 loop
            o_fast_r.data(i) <= uint64_s_NULL;
            -- If valid data then output data
            if slow_array_valids_r(i) = '1' then
              o_fast_r.data(i) <= slow_array_r.data(i);
            end if;
          end loop;
        else
          fast_clk_counter_r <= fast_clk_counter_r + 1;
        end if;
      end if;
      end process;

      -- output reg on slow output clock
      process(out_clk) is
      begin
      if rising_edge(out_clk) then
        o_slow_r <= o_fast_r;
      end if;
      end process;
      rd_return_output <= o_slow_r;
```

`o_fast_r` changes on the fast edges where the counter rolls over, once every `R` fast
cycles, and the slow domain samples it on every slow edge. This works only when the
rollover edges line up with the slow edges, so that each value is stable for a whole slow
period before it is sampled: clocks from one source that start together. Nothing in the
generated design checks or establishes that alignment. The counter starts at `R-1` (its
initial value) and runs freely.

There are no synchronizers, and nothing aligns the counter with the slow clock. The
design relies on edge-aligned clocks from one source (for example two outputs of one PLL)
and on register initial values; the example was confirmed in hardware on an Arty board.
The generated constraints still declare the two clocks asynchronous (section 12), so
PipelineC's own timing runs ignore these paths.

Requirements: an integer ratio, one group on both sides, and the `volatile` qualifier.
The wiki says `R` can be rounded for non-integer ratios. The code computes a rounded `R`,
but its check for non-integer ratios, different groups, and non-`volatile` variables used
across clocks stops parsing with a `NameError`
([section 15](#crossing-checks-crash-with-nameerror)).

## 7. Same-clock crossing wires and `wire.h`

A non-`volatile` crossing variable whose two sides are on the same clock gets sizes 1 and
1, and its entity holds the last enabled value:

```vhdl
      -- Same clock with clock disabled past value holding reg
      process(in_clk, in_clk_en) is
      begin
        if rising_edge(in_clk) and in_clk_en(0) = '1' then
          clock_disabled_value_r <= in_data;
        end if;
      end process;

      -- Mux current in value or past value
      process(in_data,in_clk_en,clock_disabled_value_r) is
      begin
        if in_clk_en(0) = '1' then
          rd_return_output <= in_data;
        else
          rd_return_output <= clock_disabled_value_r;
        end if;
      end process;
```

The reader sees the writer's value in the same cycle while the write call is enabled, and
the last enabled value otherwise.

[`include/wire.h`](../include/wire.h) hides the array structs of this kind:

```c
#define WIRE_READ(type, lhs, clk_cross_name)  // lhs = clk_cross_name_READ().data[0];
#define WIRE_WRITE(type, clk_cross_name, rhs) // clk_cross_name_WRITE({.data[0] = rhs});
```

Without `__PIPELINEC__` (which the compiler passes as `-D__PIPELINEC__`) they become plain
assignments, so the same source compiles as ordinary C. The UART, VGA and DVI libraries
still use these wires (`include/uart/*.c`, `include/vga/vga_pmod.c`,
`include/dvi/dvi_pmod.c`); new code uses shared globals.
[`include/dvi/dvi_pmod.c`](../include/dvi/dvi_pmod.c) declares its output module as
`#pragma MAIN dvi // No associated clock domain yet`, and inference gives it the clock of
the MAIN that writes `app_to_dvi`.

### Arbitrated handshake crossings: `IO_PAIR`

FSM-style code can share one instance of a function among several callers by including
`<f>_SINGLE_INST.h`. The generated header (`C_TO_LOGIC.GEN_POST_PREPROCESS_SINGLE_INST_HEADERS`)
declares two crossing variables, `<f>_arb_inputs` and `<f>_arb_outputs`, includes their
`clock_crossing/` headers, adds `#pragma IO_PAIR <f>_arb_inputs <f>_arb_outputs`, and
defines `#pragma MAIN <f>_arb`, which reads the inputs with `WIRE_READ`, calls `<f>_FSM`
and writes the outputs with `WIRE_WRITE`. The callers' generated FSM code writes the
inputs and reads the outputs with the same macros
([`examples/fsm_style.c`](../examples/fsm_style.c) includes `atomic_add_SINGLE_INST.h`).

`DERIVE_ARB_CLK_CROSSING_INFO` turns each `IO_PAIR` of two crossing variables into a
`LOGIC.ArbHandshakeInfo` and marks both variables `is_part_of_arb_handshake`, which takes
them out of the ordinary crossings. `WRITE_CLK_CROSS_ENTITIES` writes one
`arb_clk_cross_<in>_<out>` entity per pair. It has one `clk`, numbered ports per caller,
and a round-robin arbiter (`priority_func`) that holds the chosen caller until the output
handshake completes (`arb_state_waiting_for_done_r`). Every MAIN involved must be on one
clock (`Cannot have multiple clock domains on the arbitrated clock crossing pair ...`).

## 8. `ASYNC_WIRE`

`#pragma ASYNC_WIRE v` turns off clock-domain handling for `v`:

1. `v` is skipped by [inference](#clock-domain-inference).
2. On a shared global, the multiple-clock-domains check is skipped and the top level
   assigns the writer's field to each reader's field across clocks.
   [`examples/shared_globals.c`](../examples/shared_globals.c) reads a 100 MHz writer's
   global from a 50 MHz MAIN:

   ```vhdl
   global_to_module.not_same_clk_read_main.read_func_shared_globals_c_l71_c10_7493.the_global <= module_to_global.write_main.write_func_shared_globals_c_l35_c3_038b.the_global;
   ```

3. On a crossing variable, the crossing becomes the same-clock holding-register entity
   of section 7 with `in_clk` and `out_clk` on different clocks. The read domain uses the
   write domain's register and mux output directly ([`examples/async_wires.c`](../examples/async_wires.c),
   166.66 MHz and 25 MHz).

Nothing synchronizes the signal and no constraint covers it beyond the blanket
asynchronous clock groups of section 12. A multi-bit value may be sampled while it
changes. The reverse also holds: `ASYNC_WIRE` on a global whose users are all on one clock
only skips the checks. The path is timed like any other path on that clock, so the pragma
cannot be used as a false path ([#222](https://github.com/JulianKemmerer/PipelineC/discussions/222)
asks for real false-path support). Uses in the repository:

| Use | Example |
|---|---|
| Slowly changing control flags | `frame_buffer_read_port_sel` in [`dual_frame_buffer.c`](../examples/shared_resource_bus/axi_frame_buffer/dual_frame_buffer.c); `next_screen_state` in the Mandelbrot demos |
| Reset and calibration done flags | `xil_mem_rst_done` in [`examples/axi/axi_xil_mem.c`](../examples/axi/axi_xil_mem.c); `cam_init_done` in the camera examples |
| Signals already synchronous to the reader | the TEMAC wires in `xil_temac.c`: the IP instance sits in the reference-clock MAIN, but its I/O belongs to the RX and TX clocks |
| Monitor flags | `i2s_rx_descriptors_out_monitor_overflow` ("Disable timing checks") |

A common pattern pairs an `ASYNC_WIRE` flag with a synchronizer in the reading function:
`uint1_t init_done = xil_cdc2_bit(cam_init_done);` in
[`examples/stream_soc/dvp/hardware/device.c`](../examples/stream_soc/dvp/hardware/device.c)
(see [`cdc.h`](#synchronizer-macros-cdch)).

`INST_ARRAY` globals ignore `ASYNC_WIRE` (section 3).

## 9. Libraries and examples

### Synchronizer macros: `cdc.h`

[`include/cdc.h`](../include/cdc.h) has:

- `CDC(type, name, num_regs, lhs, rhs)`: a shift register of `num_regs` static registers
  in the calling function. `rhs` shifts in, `lhs` gets the oldest. `CDC2` uses two
  registers. It synchronizes asynchronous inputs into the calling function's clock:
  `CDC2(uint4_t, btn_cdc, registered, btn)` in [`include/buttons/buttons.c`](../include/buttons/buttons.c),
  likewise in `switches.c`, `uart.c` and `uart_ports.c`. These are plain registers with no
  attributes or constraints.
- `xil_cdc2_bit(uint1_t)`: a `FUNC_WIRES` function whose `__vhdl__` body instantiates
  Xilinx `xpm_cdc_array_single` (`DEST_SYNC_FF => 2`, `SRC_INPUT_REG => 0`, `WIDTH => 1`,
  `dest_clk => clk`, `src_clk => '0'`), so the bit is synchronized into the calling
  function's clock. Xilinx only. Examples use it on `ASYNC_WIRE` flags and reset inputs:
  `cam_init_done` (camera and `stream_soc/dvp`), `areset` (`stream_soc/cpu/hardware/top.c`,
  `risc-v/fft_risc-v.c`), `frame_buffer_read_port_sel` (`ddr_dual_frame_buffer.c`).

The file ends with `// TODO ADD CDC handshake`.

### Libraries that cross clock domains

| Library | Clock-domain mechanisms |
|---|---|
| [`shared_resource_bus.h`](../include/shared_resource_bus.h), [`shared_resource_bus_decl.h`](../include/shared_resource_bus_decl.h) | Five `ASYNC_CLK_CROSSING` FIFOs per host port (write request, write data, write response, read request, read data), depth `SHARED_RES_CLK_CROSS_FIFO_DEPTH` 16 ("min is 16 due to Xilinx XPM FIFO"). Host-side wiring MAIN `MAIN_MHZ_GROUP(<bus>_host_side_fifo_wiring, HOST_CLK_MHZ, HOST_CLK_GROUP)`, device side `MAIN_MHZ(<bus>_dev_side_fifo_wiring, DEV_CLK_MHZ)`. The pipelined host wiring limits requests in flight to the FIFO depth. The decl header is included repeatedly with different `#define`s, unrolled up to 128 host ports. A comment notes `INST_ARRAY` cannot carry async FIFOs. |
| [`multi_host_clk_shared_resource_bus_decl.h`](../include/multi_host_clk_shared_resource_bus_decl.h) | One shared bus per host clock domain (`HOST0`, `HOST1`, each with optional group), joined into one array in the device domain by `MAIN_MHZ(<bus>_dev_side_multi_host_domain_wiring, DEV_CLK_MHZ)`. |
| `shared_resource_bus_pipeline.h` | `MAIN_MHZ(<name>_dev_arb_connect, DEV_CLK_MHZ)`: the pipeline runs on the device clock, its hosts on theirs. |
| [`vga/vga_pmod_async_pixels_fifo.c`](../include/vga/vga_pmod_async_pixels_fifo.c), [`vga/vga_pmod_async_fifo.c`](../include/vga/vga_pmod_async_fifo.c) | Generated-header FIFO `vga_async_fifo` (depth 256 for pixels, 16 for full VGA signals): written from any domain, read by `MAIN_MHZ(pmod_async_fifo_reader, PIXEL_CLK_MHZ)`. |
| [`uart/uart_msg_fifos.c`](../include/uart/uart_msg_fifos.c) | Generated-header FIFOs `uart_rx_msg_fifo[1]` and `uart_tx_msg_fifo[1]` (depth raised to the minimum), wiring MAINs on the UART clock by naming another MAIN in `MAIN_MHZ`, `WIRE_READ`/`WIRE_WRITE` to the message modules. |
| [`debug_probes/uart_probes.c`](../include/debug_probes/uart_probes.c) | Per probe, `GLOBAL_FIFO(uint8_t, probeN_fifo, 2)` and `GLOBAL_FIFO(uint1_t, probeN_rd_en_fifo, 2)`. `MAIN(probeN_process)` has no MHz; inference puts it in the probed signal's domain, and the bytes cross to the UART domain. |
| [`net/rmii_eth_mac.c`](../include/net/rmii_eth_mac.c), [`net/rmii_wires.c`](../include/net/rmii_wires.c) | `CLK_MHZ(rmii_clk, 50.0)` for the RMII clock pin; optional `GLOBAL_STREAM_FIFO_SKID_IN_BUFF` / `_SKID_OUT_BUFF` between the MAC and the user's domain. |
| [`dvi/dvi_pmod.c`](../include/dvi/dvi_pmod.c) | Phase-shifted clock group (section 2). |
| [`global_func_inst.h`](../include/global_func_inst.h) | `GLOBAL_FUNC_INST`, `GLOBAL_PIPELINE_INST*` and `GLOBAL_VALID_READY_PIPELINE_INST` declare `MAIN(inst)` without a frequency, connected to the user through globals, so the instance takes its user's clock. `GLOBAL_VALID_READY_PIPELINE_INST` adds a local `FIFO_FWFT` for backpressure, on one clock. |
| `compiler.h` | `DECL_INPUT_REG`, `DECL_OUTPUT_REG`, `GLOBAL_*_WIRE_CONNECT` and `MAIN_SPLIT2/3` declare MAINs without a frequency. |

### Examples

| Example | Shows |
|---|---|
| [`async_clock_crossing.c`](../examples/async_clock_crossing.c) | `GLOBAL_FIFO_WIDTH_DEPTH` FIFOs in both directions between 50 MHz and 25 MHz, two elements per transfer (wiki Example 1) |
| [`global_fifo.c`](../examples/global_fifo.c) | the same macros between two 100 MHz MAINs, giving single-clock FIFOs |
| [`clock_crossing.c`](../examples/clock_crossing.c) | volatile 100 MHz / 25 MHz ratio crossings, `R` = 4 (wiki Example 2) |
| [`async_wires.c`](../examples/async_wires.c) | `ASYNC_WIRE` crossing variables with `WIRE_READ`/`WIRE_WRITE` |
| [`shared_globals.c`](../examples/shared_globals.c) | a shared global read on another clock, allowed by `ASYNC_WIRE` |
| [`internal_clocks.c`](../examples/internal_clocks.c) | a 1 MHz clock generated by a 100 MHz MAIN with `CLK_MHZ` |
| [`stream_soc/eth/hardware/xil_temac.c`](../examples/stream_soc/eth/hardware/xil_temac.c) | IP-generated clocks with `CLK_MHZ_GROUP`, `MAIN_MHZ_GROUP`, `ASYNC_WIRE` |
| [`arty/src/eth/work_app.c`](../examples/arty/src/eth/work_app.c) | `MAIN_GROUP` with the MHz inferred, `ASYNC_CLK_CROSSING` |
| [`stream_soc/fft/hardware/device.c`](../examples/stream_soc/fft/hardware/device.c) and the other `stream_soc` devices | `GLOBAL_STREAM_FIFO` between a device's clock domains |
| [`risc-v/fft_2pt_2x_clk.c`](../examples/risc-v/fft_2pt_2x_clk.c) | `GLOBAL_STREAM_FIFO` between a clock and its double |
| [`sdr/fm_radio.c`](../examples/sdr/fm_radio.c) | `MAIN_SYN_MHZ` |
| [`pico-ice/ice_makefile_pipelinec/top.h`](../examples/pico-ice/ice_makefile_pipelinec/top.h) | a PLL clock pin promoted with `DECL_INPUT` + `CLK_MHZ` |

[`src/tests/c_tests/test_builds.sh`](../src/tests/c_tests/test_builds.sh) builds
`global_fifo.c`, `clock_crossing.c`, `async_clock_crossing.c` and `internal_clocks.c`.

### Related issues and discussions

GitHub threads about clock domains, with where each one stands. Issues converted to
discussions are listed under their discussion number.

| Thread | Kind, state | Subject | Where it stands |
|---|---|---|---|
| [#68](https://github.com/JulianKemmerer/PipelineC/issues/68) | issue, closed | "always a wire" crossings | became the `ASYNC_WIRE` pragma: an override of the default crossing logic, so a pragma rather than a new kind of crossing |
| [#73](https://github.com/JulianKemmerer/PipelineC/issues/73) | issue, closed | globals used directly between functions | became shared globals, taken from the writer's register input (same-cycle wires) |
| [#119](https://github.com/JulianKemmerer/PipelineC/issues/119) | issue, closed | debug port wires | moved debug ports from crossing-style globals to single-domain global wires |
| [#137](https://github.com/JulianKemmerer/PipelineC/issues/137) | issue, open | user clock nets not found by every timing tool | Quartus does not find `get_nets` user clocks; PipelineC builds fail ([section 15](#quartus-does-not-find-user-clocks)) |
| [#138](https://github.com/JulianKemmerer/PipelineC/issues/138) | issue, closed | globals as top-level clock inputs | done through `DECL_INPUT` + `CLK_MHZ`; tool-specific parts moved to #137 |
| [#142](https://github.com/JulianKemmerer/PipelineC/issues/142) | issue, closed | `FIFO_FWFT` pausing after flow control | led to the raw-VHDL `pipelinec_fifo_fwft` that the same-clock crossings now use |
| [#176](https://github.com/JulianKemmerer/PipelineC/issues/176) | issue, closed (duplicate of #174, now [#328](https://github.com/JulianKemmerer/PipelineC/discussions/328)) | Verilator with several clock domains | needed a VHDL async FIFO (now `pipelinec_async_fifo_fwft`) and clocks generated in HDL |
| [#222](https://github.com/JulianKemmerer/PipelineC/discussions/222) | discussion (was #66) | false paths | notes that `ASYNC_WIRE` is not a false path on one clock |
| [#225](https://github.com/JulianKemmerer/PipelineC/discussions/225) | discussion (was #72) | make the crossing kind explicit in its declaration | proposes `clock_crossing_buffer/` and `clock_crossing_fifo/` headers, and `ASYNC_WIRE` as a kind |
| [#232](https://github.com/JulianKemmerer/PipelineC/discussions/232) | discussion (was #118) | several clock domains inside one function | sketches a `RATE` pragma for integer-ratio ("double-pumped") code blocks, and relative clocks per function |
| [#254](https://github.com/JulianKemmerer/PipelineC/discussions/254) | discussion | using an N-times faster clock | resource reduction by running a pipeline on a faster clock |
| [#255](https://github.com/JulianKemmerer/PipelineC/discussions/255), [#266](https://github.com/JulianKemmerer/PipelineC/discussions/266) | discussions | reset pragmas; a reset module demo | clock-domain-aware resets, PLL lock |
| [#269](https://github.com/JulianKemmerer/PipelineC/discussions/269) | discussion | MAIN pragmas with hierarchy | `#pragma MAIN top.clk_domain_A` |
| [#327](https://github.com/JulianKemmerer/PipelineC/discussions/327) | discussion (was #171) | ratio crossings as macros | generate a struct type instead of `<T>_array_N_t` so the ratio crossing can use `clock_crossing.h`-style macros |
| [#328](https://github.com/JulianKemmerer/PipelineC/discussions/328) | discussion (was #174) | generate clocks in the HDL testbench | would make several clocks easy to simulate |
| [#340](https://github.com/JulianKemmerer/PipelineC/discussions/340) | discussion (was #83) | a zero-depth, same-clock handshake crossing | a FIFO-like interface with combinational pass-through; noted as applying to Pypeline FIFOs too |
| [#342](https://github.com/JulianKemmerer/PipelineC/discussions/342) | discussion | Pypeline: crossing between clock domains | open questions: annotation, library factory, or both; how native simulation schedules several rates ([section 16](#16-ideas-for-multiple-clock-domains-in-pypeline)) |
| [#346](https://github.com/JulianKemmerer/PipelineC/discussions/346) | discussion | multi-cycle constraints on tools other than Vivado | the same per-tool question CDC constraints raise |
| [#349](https://github.com/JulianKemmerer/PipelineC/discussions/349) | discussion | clearing a FIFO on reset | no FIFO has a clear input |
| [#354](https://github.com/JulianKemmerer/PipelineC/issues/354) | issue, open | Pypeline native simulation runs different rates in lockstep; it now refuses such designs, and closing the issue is recommended | [section 16](#native-simulation-with-several-clocks) |

## 10. IR: what the compiler records

The shared IR is described in [LOGIC_DESIGN.md](LOGIC_DESIGN.md#3-parserstate--the-global-compiler-context).
These are the parts that carry clock domains.

### `ParserState` fields

| Field | Contents | Filled by |
|---|---|---|
| `main_mhz` | MAIN name → MHz or `None` | `APPEND_PRAGMA_INFO`, `INFER_CLOCK_DOMAINS` |
| `main_syn_mhz` | MAIN name → synthesis MHz or `None` | same |
| `main_clk_group` | MAIN name → group string or `None` | same |
| `clk_mhz`, `clk_group` | user clock wire → MHz, group | `CLK_MHZ`, `CLK_MHZ_GROUP` |
| `async_wires` | names from `ASYNC_WIRE` | pragma |
| `input_wires`, `output_wires` | top-level port globals | `INPUT`, `OUTPUT` |
| `inst_array_dict` | instance variable → array variable | `INST_ARRAY` |
| `io_pairs` | (input var, output var) pairs | `IO_PAIR` |
| `clk_cross_var_info` | crossing variable → `ClkCrossVarInfo` | `GET_CLK_CROSSING_INFO` |
| `arb_handshake_infos` | set of `ArbHandshakeInfo` | `DERIVE_ARB_CLK_CROSSING_INFO` |
| `global_vars` | name → `VariableInfo` | `GET_GLOBAL_VAR_INFO` |
| `func_marked_wires` | `FUNC_WIRES` functions (inference messages are silent for them) | pragma |
| `func_name_to_calls`, `func_names_to_called_from` | call graph used to find the MAINs on each side | `GET_FUNC_NAME_TO_FROM_FUNC_CALLS_LOOKUPS` |

### Per-variable and per-crossing records

`LOGIC.VariableInfo`, for each global: `is_volatile` (the C `volatile` qualifier, which
selects ratio-crossing semantics), `path_id` (from `ID_INST`) and `used_in_funcs`.

`LOGIC.ClkCrossVarInfo`, for each crossing. All three tuples are ordered (write, read):

| Field | Contents |
|---|---|
| `write_read_funcs` | (write function name, read function name) |
| `write_read_main_funcs` | (set of write-side MAINs, set of read-side MAINs) |
| `write_read_sizes` | (elements per write, elements per read) |
| `flow_control` | FIFO or not |
| `is_part_of_arb_handshake` | set by `DERIVE_ARB_CLK_CROSSING_INFO` |

`LOGIC.ArbHandshakeInfo`: `input_var_name`, `output_var_name` and their
`ClkCrossVarInfo` objects.

Inside `GET_CLK_CROSSING_INFO` the same data passes through working dictionaries that use
the opposite order, which matters when reading the code:

| Dictionary | Key → value | Order |
|---|---|---|
| `var_to_write_func`, `var_to_read_func` | variable → function name found by the regular expressions | — |
| `var_to_rw_main_funcs` | variable → (read-side MAINs, write-side MAINs) | (read, write) |
| `var_to_rw_mhz_groups` (returned by `INFER_CLOCK_DOMAINS`) | variable → ((read MHz, read group), (write MHz, write group)) | (read, write) |
| `ClkCrossVarInfo` tuples | built from the above | (write, read) |

`INFER_CLOCK_DOMAINS` unpacks `var_to_rw_main_funcs` as (read, write) consistently, so the
reversal is only a reading hazard. `VHDL.WRITE_CLK_CROSS_ENTITIES` is the one place that
unpacks a `ClkCrossVarInfo` tuple in the wrong order (see
[section 15](#crossing-tuple-unpacked-in-the-wrong-order)).

`LOGIC.CLK_CROSS_FUNC_TO_VAR_NAME` is the inverse lookup used by the back end: it cuts a
function name at its first `_READ`, or else at its first `_WRITE`. Every helper that needs
the `ClkCrossVarInfo` of a crossing call (`LOGIC_NEEDS_CLOCK_ENABLE`,
`LOGIC_NEEDS_GLOBAL_TO_MODULE`, `LOGIC_NEEDS_MODULE_TO_GLOBAL`, the VHDL connection text)
goes through it, so the naming convention is part of the back end's interface, not only
of the C front end.

### `Logic` flags and helpers

- `Logic.is_clock_crossing` is set on the read and write function definitions.
  `uses_nonvolatile_state_regs` is set on them too, so they are never sliced.
- `LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(crossing function)` is true for every `_WRITE` function
  and for both functions of a FIFO, so a non-FIFO `_READ` has no clock enable.
- `LOGIC.LOGIC_NEEDS_GLOBAL_TO_MODULE(f)` is true when some submodule, at any depth, is a
  crossing `_READ` or a FIFO function, or when `f` reads a shared global.
  `LOGIC_NEEDS_MODULE_TO_GLOBAL(f)` is the same for `_WRITE` functions, FIFO functions and
  written shared globals. They decide which entities get the record ports.
- `LOGIC.GLOBAL_VAR_IS_SHARED`, `LOGIC.RECURSIVE_FIND_MAIN_FUNCS` (function → MAINs) and
  `LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST` (instance → its MAIN) are the lookups the
  checks use.
- `Logic.WIRE_DO_NOT_COLLAPSE` keeps wires into crossing submodules, whose outputs are
  used in another domain, and `TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE` does not descend into
  crossing functions.
- `SYN.LOGIC_IS_ZERO_DELAY` is true for crossing functions ("For now? How to handle paths
  through clock cross logic?"), and `Logic.CAN_HAVE_ADDED_LATENCY` is false.

## 11. VHDL generation

See also [VHDL_DESIGN.md](VHDL_DESIGN.md#top-level-clocks-and-records).

### Global wire records

`VHDL.WRITE_GLOBAL_WIRES_VHDL_PACKAGE` writes `global_wires_pkg.pkg.vhd` when the design
has a shared global or a crossing. For each function that needs them it declares
`<func>_global_to_module_t` and `<func>_module_to_global_t`:

- one field per port of each crossing submodule, named `<crossing function>_<port>`:
  inputs and `CLOCK_ENABLE` in `module_to_global`, `return_output` in `global_to_module`;
- one field per shared global the function writes or reads;
- one nested field per submodule instance that needs the records, named after the
  instance.

The top-level `global_to_module_t` and `module_to_global_t` have one field per MAIN. From
`examples/async_clock_crossing.c` (excerpt):

```vhdl
  type fast_global_to_module_t is record
     fast_to_slow_WRITE_2_return_output : fast_to_slow_write_t;
     slow_to_fast_READ_2_return_output : slow_to_fast_read_t;
  end record;

  type fast_module_to_global_t is record
     fast_to_slow_WRITE_2_CLOCK_ENABLE : unsigned(0 downto 0);
     fast_to_slow_WRITE_2_write_data : uint8_t_2;
     fast_to_slow_WRITE_2_write_enable : unsigned(0 downto 0);
     slow_to_fast_READ_2_CLOCK_ENABLE : unsigned(0 downto 0);
     slow_to_fast_READ_2_read_enable : unsigned(0 downto 0);
     led0 : unsigned(0 downto 0);
     led1 : unsigned(0 downto 0);
  end record;

  type global_to_module_t is record
    ...
    fast : fast_global_to_module_t;
    slow : slow_global_to_module_t;
  end record;
```

Fields are named after the crossing function, not the call instance, so two calls of one
crossing function inside one function would produce duplicate field names. Identical
calls (same inputs) are merged by logic trimming before the package is written.

### Function entities

A function entity's ports come in this order, each of the first four only when needed:
`clk`, `CLOCK_ENABLE`, `global_to_module : in <func>_global_to_module_t`,
`module_to_global : out <func>_module_to_global_t`, then its inputs and outputs. A
crossing call has no entity of its own; `GET_CLOCK_CROSS_ENTITY_CONNECTION_TEXT` turns it
into assignments in the pipeline process (`module_to_global.<func>_<port> <= ...;` for
inputs and clock enable, `... := global_to_module.<func>_return_output;` for the result).
The excerpt in [FIFO calls inside auto-pipelined MAINs](#fifo-calls-inside-auto-pipelined-mains)
shows them. Submodule instances that need the records get `global_to_module.<inst>` and
`module_to_global.<inst>` in their port maps.

### The multi-MAIN top level

`VHDL.WRITE_MULTIMAIN_TOP` writes, in order:

1. **Clock ports** under `-- All clocks`, one `clk_<...> : in std_logic` per distinct
   clock name of the MAINs, sorted, except user clocks.
2. Ports for `INPUT`/`OUTPUT` globals, then each MAIN's inputs and outputs as
   `<main>_<port>`.
3. **User clocks** as internal signals (section 2).
4. `signal module_to_global : module_to_global_t;` and
   `signal global_to_module : global_to_module_t;`, plus one `clk_cross_<var>_<port>`
   signal per crossing read output.
5. **IO registers**, synthesis tops only: each MAIN's inputs and outputs registered on its
   own clock. The final top (`is_final_top`, `top/top.vhd`) connects MAINs to the ports
   directly.
6. **MAIN instances**, positional: the clock and clock enable when the entity has them
   (the enable is `to_unsigned(1,1)`: "main functions are always clock enabled, always
   running"), records, inputs, outputs.
7. **Arbitrated crossings** (`-- Instantiate each arbitrated handshake clock crossing`).
8. **Unidirectional crossings** (`-- Instantiate each unidirectional data clock crossing`).
   Each `clk_cross_<var>` gets `in_clk` from the write side's clock and `out_clk` from the
   read side's clock. Its read output goes through the `clk_cross_<var>_<port>` signal to
   every read instance.
9. **Shared globals** (`-- Directly connected global wires`) and `INST_ARRAY` wiring.

From `examples/async_clock_crossing.c`:

```vhdl
fast_0CLK_07f48f10 : entity work.fast_0CLK_07f48f10 port map (
clk_50p0,
to_unsigned(1,1),
global_to_module.fast,
module_to_global.fast);

-- Instantiate each unidirectional data clock crossing
fast_to_slow : entity work.clk_cross_fast_to_slow port map
(
in_clk => clk_50p0,
in_clk_en => module_to_global.fast.fast_to_slow_WRITE_2_CLOCK_ENABLE,
write_data => module_to_global.fast.fast_to_slow_WRITE_2_write_data,
write_enable => module_to_global.fast.fast_to_slow_WRITE_2_write_enable,
wr_return_output => global_to_module.fast.fast_to_slow_WRITE_2_return_output,
out_clk => clk_25p0,
out_clk_en => module_to_global.slow.fast_to_slow_READ_2_CLOCK_ENABLE,
read_enable => module_to_global.slow.fast_to_slow_READ_2_read_enable,
rd_return_output => clk_cross_fast_to_slow_return_output
);
global_to_module.slow.fast_to_slow_READ_2_return_output <= clk_cross_fast_to_slow_return_output;
```

A crossing nested below a MAIN is addressed through the nested records, for example
`module_to_global.<main>.<inst>.<crossing function>_<port>`.

### `clk_cross_entities.vhd`

`VHDL.WRITE_CLK_CROSS_ENTITIES` writes one file with an `arb_clk_cross_<in>_<out>` entity
per `IO_PAIR` and a `clk_cross_<var>` entity per other crossing. The ports:

| Kind | Ports |
|---|---|
| FIFO | `in_clk`, `in_clk_en`, `write_data` (`T[W]`), `write_enable`, `wr_return_output` (`<v>_write_t`), `out_clk`, `out_clk_en`, `read_enable`, `rd_return_output` (`<v>_read_t`) |

The FIFO's two `*_return_output` types are those of its crossing functions' return values
(`VHDL.CLK_CROSS_RETURN_VHDL_TYPE`). For C they are `<v>_write_t` and `<v>_read_t`; a
Pypeline async global FIFO's are its stubs' return structs. A read side that is never
called keeps the `<v>_read_t` text.
| ratio, same-clock and `ASYNC_WIRE` | `in_clk`, `in_clk_en`, `in_data` (`T_array_<W>_t`), `out_clk`, `rd_return_output` (`T_array_<R>_t`) |

The architectures are those of sections 5, 6 and 7. For the built-in async FIFO:

```vhdl
    din_slv <= uint8_t_2_to_slv(write_data);
    rd_return_output.data <= slv_to_uint8_t_2(dout_slv);
pipelinec_fifo_fwft_inst : entity work.pipelinec_async_fifo_fwft
generic map (
    DEPTH_LOG2 => 2,
    DATA_WIDTH => uint8_t_2_SLV_LEN
)
port map
(
    in_clk => in_clk,
    valid_in  => write_enable(0) and in_clk_en(0),
    ready_out => wr_return_output.ready(0),
    data_in   => din_slv,
    out_clk => out_clk,
    valid_out => rd_return_output.valid(0),
    ready_in  => read_enable(0) and out_clk_en(0),
    data_out  => dout_slv
);
```

### Output files

| File | Contents |
|---|---|
| `clock_crossing/<var>.h` | generated crossing headers |
| `type_array_N_t.h/<T>_array_N_t.h/...` | array structs used by non-FIFO crossings |
| `global_wires_pkg.pkg.vhd` | the records |
| `clk_cross_entities.vhd` | crossing entities, listed only for whole-design (multi-MAIN) synthesis |
| `built_in/pipelinec_fifo_fwft.vhd`, `built_in/pipelinec_async_fifo_fwft.vhd` | copied from `src/vhdl/`, always listed first |
| `top/top_<hash>.vhd`, `top/top.vhd` | synthesis tops and the final top |
| `clocks.xdc` / `.sdc` / `.ldc` / `.py` / `.ccf` | constraints for PipelineC's own synthesis runs |
| `vhdl_files.txt` (and `read_vhdl.tcl` for Vivado) | final file list, without clock constraints |

## 12. Synthesis tool support

See also [SYN_DESIGN.md](SYN_DESIGN.md#7-constraints-and-output-files).

### Clock constraints

Every whole-design synthesis writes a constraints file with
`SYN.WRITE_CLK_CONSTRAINTS_FILE`. `SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH` maps each MAIN's
clock name to `GET_TARGET_MHZ`; MAINs that share a name share one entry. Each clock gets
`create_clock -add -name <clk> -period <1000/MHz> -waveform {0 <half>} [get_ports {<clk>}]`,
with `get_nets` for user clocks (which Quartus does not match, see
[section 15](#quartus-does-not-find-user-clocks)). A clock with no MHz gets 1000 MHz and a warning, and
Quartus periods are clipped at 80000 ns. With more than one clock, each tool does this
(output of the real function for the two-clock example, and with a third clock added):

| Tool | File | More than one clock |
|---|---|---|
| Vivado | `clocks.xdc` | `set_clock_groups -name async_clks_group -asynchronous -group [get_clocks *] -group [get_clocks *]` |
| Quartus | `clocks.sdc` | `set_clock_groups -asynchronous -group [get_clocks a] -group [get_clocks b]` for each pair, written without newlines, so with three or more clocks they run together on one line, which Quartus ignores with warnings ([section 15](#quartus-clock-groups-run-together)) |
| Diamond | `clocks.sdc` (Synplify) or `.ldc` (LSE) | nothing ("rely on clock cross path detection error in timing report") |
| open tools (nextpnr) | `clocks.py` | `ctx.addClock("clk_50p0", 50.0)` per clock and nothing else ("All clock assumed async in nextpnr constraints") |
| CC tools | `clocks.ccf` | the file holds only `#TODO` |
| Gowin, Efinity, PyRTL, DEVICE_MODELS | `clocks.sdc` | raises `Exception: How does tool <TOOL> deal with async clocks?` |

So a design with more than one clock cannot run whole-design synthesis with Gowin,
Efinity, PyRTL or DEVICE_MODELS. Per-module synthesis runs use one `clk` at 1000 MHz, and
crossing functions are never synthesized on their own.

How each backend uses the file matters for any fix, because two of the four that raise
never read it:

| Tool | How the file reaches the tool | Report parser and clocks |
|---|---|---|
| Vivado | `read_xdc` in the generated Tcl | per clock path group, plus per-MAIN and per-MCP queries |
| Quartus | `read_sdc` / `SDC_FILE` assignment | per clock; a path whose launch and latch clocks differ stops the build |
| Diamond | `prj_src add` | per clock (Synplify); LSE reports everything as `clk` |
| open tools (nextpnr) | `--pre-pack clocks.py` | per clock, `(posedge -> posedge)` sections only |
| Gowin | `add_file -type sdc` | the first path of each clock group |
| Efinity | `<efx:sdc_file>` in the project XML | the launch clock of each path, against the clock table in the report |
| CC tools | `-ccf` to `p_r` (pin constraints, not timing) | the last `Maximum Clock Frequency` line of the log, under path group `None` (the parser sets `"clk"` and then overwrites it) |
| PyRTL | not read; listed in the synthesis-cache identity only | one `Fmax (MHz):` for the whole netlist, path group `None`, no register names |
| DEVICE_MODELS | not read; its own static timing has one ideal clock | worst path of the whole netlist, path group `clk` |

When a report carries no register names (PyRTL), `SWEEP.GET_MAIN_INSTS_FOR_PATH_REPORT`
prints `WARNING: No start/end reg name in timing report! Assuming all clock domains had
critical paths...` and gives the path to every MAIN.

The same file also receives the multi-cycle path constraints (`AUTO_MULTI_CYCLE.GET_MCP_PATH_CONSTRAINTS`,
for `Logic.mcp_tuples`) after the clock lines. Those are Vivado-only, and other tools stop
with `Multi cycle paths have only been tested with Vivado!` (see
[AUTO_MULTI_CYCLE_DESIGN.md](AUTO_MULTI_CYCLE_DESIGN.md#2-constraints)).

These constraints exist only for PipelineC's own timing measurement. The comment in
`SYN.py` reads "All clock assumed async? Doesnt matter for internal syn. Rely on
generated/board provided constraints for real hardware". The final `vhdl_files.txt` and
Vivado `read_vhdl.tcl` carry no clock constraints; the board project supplies clocks and
any CDC constraints. With Vivado the XPM FIFO brings Xilinx's own CDC logic: its
`xpm_cdc_gray` synchronizers carry `ASYNC_REG` (visible in the synthesis log). The
built-in async FIFO, `CDC2` registers and `ASYNC_WIRE` paths get nothing from PipelineC.

### Timing reports and the sweep

Each backend's report parser returns the worst path per path group, which is a clock
name. Cross-clock paths are left out: nextpnr prints `Critical path report for
cross-domain path ...` sections, but `OPEN_TOOLS` reads only the `(posedge -> posedge)`
per-clock reports. With Vivado's blanket clock groups, cross-clock paths are not timed at
all. Quartus and Diamond stop the build with `Multiple clocks in path report?` if a
reported path's launch and latch clocks differ. Diamond's LSE parser prints `TODO multiple
clock domains for LSE!!` and reports every path as `clk`.

A `--comb` build prints one line per clock, for example from the ECP5 build of
`examples/async_clock_crossing.c`:

```
PASS Clock clk_25p0 FMAX: 202.470 MHz (4.939 ns)
PASS Clock clk_50p0 FMAX: 231.320 MHz (4.323 ns)
```

The sweep (`SWEEP.GET_MAIN_INSTS_FOR_PATH_REPORT`, then
`SYN.GET_MAIN_INSTS_FROM_PATH_REPORT`) gives each path to MAINs by matching register and
netlist names against MAIN entity names. As a fallback, a path that starts and ends in
crossing instances (whose top-level labels are the variable names) goes to the MAINs that
both read the first crossing and write the second. A path group that matches no MAIN, usually
a path inside a FIFO, is skipped with
`Path group: clk_50p0 is likely only limited by built in FIFO implementations...`. Each
MAIN is judged against its own `GET_TARGET_MHZ`; MAINs on one clock share that clock's
reported path.

## 13. Simulation support

The C front end has no native simulator; simulation runs the generated VHDL. See
[SIM_DESIGN.md](SIM_DESIGN.md#5-backends) for the backends. `SIM.GET_SIM_GEN_INFO` builds
their clock list from the constraint mapping: clocks driven by a user clock wire are
removed, and user clocks that are top-level inputs are listed under the input's name. That
lookup builds the name without the group, so `CLK_MHZ_GROUP` clocks are not matched.

Because the list comes from `SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH`, its frequencies are
`GET_TARGET_MHZ` values: `MAIN_SYN_MHZ` whenever the selected tool only synthesizes (see
[`MAIN_SYN_MHZ`](#synthesis-only-targets-main_syn_mhz)). The cocotb template uses that
number for its clock period.

The cocotb template drives its one clock from Python: it sets the clock to `0`, waits 1 ps
(so that VHDL's `rising_edge` sees a `'0'` to `'1'` transition), then toggles it with
`Timer` waits of half the period and prints `Clock: <n>` once per cycle. That per-cycle
print is what the native-versus-VHDL comparison tools key on, so it assumes one clock.

| Backend | With more than one clock |
|---|---|
| cocotb (`--cocotb`) | The template testbench supports one clock: otherwise `NotImplementedError: Only single clock designs supported for cocotb template testbench gen!`. With `--makefile` the user's own Makefile and testbench are used and nothing is checked. |
| Verilator (`--verilator`) | `pipelinec_verilator.h` defines each clock (`#define clk_50p0 clk_50p0`; a clock with no MHz becomes `clk`). The default `main.cpp` keeps its cycle loop inside a comment headed `User needs to specify how to drive clock(s)`, so the run does nothing; pass a `--main_cpp` that toggles the clocks. |
| CXXRTL (`--cxxrtl`) | Prints `WARNING: Multiple clocks for CXXRTL probably won't work!` and defines each clock; the default `main.cpp` toggles only `clk`. |
| ModelSim (`--modelsim`) | Builds a project; the user drives the clocks. |
| EDA Playground (`--edaplay`) | Copies the files. |

The GHDL-based flows (cocotb with GHDL, Verilator, CXXRTL, `--verilog`) handle the
built-in FIFOs: the two-clock ECP5 build converted to Verilog with GHDL and Yosys and
built with Verilator. A design whose synthesis tool is Vivado gets `xpm_fifo_async` for
its async FIFOs, which those flows cannot elaborate.

## 14. Compiler flow

The clock-domain steps of a C build, in order:

1. **`C_TO_LOGIC.PARSE_FILE`**, code-generation loop, repeated until no new header is
   needed:
   - `GEN_EMPTY_CLOCK_CROSS_HEADERS` writes placeholders for missing
     `clock_crossing/<var>.h` headers;
   - `WRITE_POST_PREPROCESS_GEN_CODE` writes text-pattern headers, including
     `<f>_SINGLE_INST.h` (`GEN_POST_PREPROCESS_SINGLE_INST_HEADERS`);
   - the file is preprocessed (with `-D__PIPELINEC__` and the output directory on the
     include path) and parsed: `APPEND_PRAGMA_INFO`,
     `GET_FUNC_NAME_TO_FROM_FUNC_CALLS_LOOKUPS`, `GET_GLOBAL_VAR_INFO`,
     `GET_CLK_CROSSING_INFO` (which runs `LOGIC.INFER_CLOCK_DOMAINS`),
     `DERIVE_ARB_CLK_CROSSING_INFO`;
   - `WRITE_POST_PREPROCESS_WITH_NONFUNCDEFS_GEN_CODE` runs `GEN_CLOCK_CROSS_HEADERS`.
2. **Function parsing**: `GEN_CODE_POST_PARSE_LOGIC_ADJUST` tags crossing functions; direct
   use of a crossing variable is rejected.
3. **Elaboration**: the multiple-writer check for globals runs, then
   `RECURSIVE_ADD_LOGIC_INST_LOOKUP_INFO` records instances (and so `FuncToInstances` for
   the crossing checks); trimming skips crossing functions.
4. **Part and tool**: `SYN.RESOLVE_PART_AND_TOOL` settles `SYN_TOOL`, which decides XPM
   versus built-in async FIFOs.
5. **First VHDL** (`AUTO_PIPELINE.WRITE_0_ADDED_CLKS_INIT_FILES`): function entities
   (crossing functions skipped), `VHDL.WRITE_MULTIMAIN_TOP` (all top-level clock checks),
   `VHDL.WRITE_CLK_CROSS_ENTITIES`, the struct package, `VHDL.WRITE_GLOBAL_WIRES_VHDL_PACKAGE`,
   and the copy of `src/vhdl/` to `built_in/`.
6. **Synthesis runs**: `SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP`, `SYN.WRITE_CLK_CONSTRAINTS_FILE`,
   the tool, the report parser, then the sweep's attribution of paths to MAINs. The sweep
   rewrites the top level and crossing entities as pipelining changes.
7. **Final files**: `SYN.WRITE_FINAL_FILES` writes `top/top.vhd` without IO registers and
   `vhdl_files.txt`.
8. **Simulation**: `SIM.GET_SIM_GEN_INFO` and the selected backend.

## 15. Known problems and fix ideas

Each entry gives what happens, where the code is, an idea for a fix, and a test that would
catch a regression. *Verified* entries were reproduced with small scratch designs (built
with `--no_synth` unless the entry says otherwise) or by calling the compiler function
directly; the others are read from the code. None of the fix ideas has been tried.

C front-end regression tests live in two places: `src/tests/c_tests/test_builds.sh` builds
the clock examples, and `src/tests/pypeline_tests/inst/` pairs a `<name>_design.c` with a
driver script that runs `pypelinec` and checks the output
(`auto_pipeline_c_pragma_test.py` is one). The test ideas below assume one of those.

| Problem | Verified | Size of the fix |
|---|---|---|
| [Crossing checks crash with `NameError`](#crossing-checks-crash-with-nameerror) | yes | small |
| [Inference never ends when a crossing side spans two clocks](#inference-never-ends-when-a-crossing-side-spans-two-clocks) | yes | small; medium for the rewrite |
| [Unused and read-only FIFOs crash the top-level writer](#unused-and-read-only-fifos-crash-the-top-level-writer) | yes | small |
| [Write-only FIFOs leave `ready` undriven](#write-only-fifos-leave-ready-undriven) | yes | small |
| [XPM FIFO depths must be powers of two](#xpm-fifo-depths-must-be-powers-of-two) | yes, Vivado 2019.2 | small |
| [Errors that exit with status 0](#errors-that-exit-with-status-0) | from the code | small |
| [Quartus clock groups run together](#quartus-clock-groups-run-together) | yes | trivial |
| [Quartus does not find user clocks](#quartus-does-not-find-user-clocks) | yes, Quartus Lite 20.1 | small for input pins, medium for generated clocks |
| [Tools without multi-clock constraints](#tools-without-multi-clock-constraints) | yes | small, plus per-tool checks |
| [Vivado clock groups make every pair asynchronous](#vivado-clock-groups-make-every-pair-asynchronous) | yes | small |
| [`MAIN_SYN_MHZ` on a shared clock depends on pragma order](#main_syn_mhz-on-a-shared-clock-depends-on-pragma-order) | yes | small |
| [A clock passed as a MAIN argument is registered by itself](#a-clock-passed-as-a-main-argument-is-registered-by-itself) | yes | small |
| [No CDC attributes or constraints](#no-cdc-attributes-or-constraints) | from the code and a Vivado log | medium |
| [`ASYNC_WIRE` is not a false path](#async_wire-is-not-a-false-path) | from the code | medium |
| [FIFO restrictions](#fifo-restrictions) | partly | medium |
| [XPM wrapper assigns `rd_return_output.data` twice](#xpm-wrapper-assigns-rd_return_outputdata-twice) | yes | trivial |
| [`ASYNC_WIRE` is ignored for `INST_ARRAY` globals](#async_wire-is-ignored-for-inst_array-globals) | from the code | small |
| [No multi-clock testbenches](#no-multi-clock-testbenches) | yes | medium |
| [Simulation clock list](#simulation-clock-list) | from the code | small |
| [Crossings are found by name](#crossings-are-found-by-name) | from the code | medium |
| [Pipelined MAINs split FIFO handshakes across stages](#pipelined-mains-split-fifo-handshakes-across-stages) | yes | small for a warning |
| [`MAIN_MHZ f other_main` copies only the MHz](#main_mhz-f-other_main-copies-only-the-mhz) | from the code | small |
| [Crossing tuple unpacked in the wrong order](#crossing-tuple-unpacked-in-the-wrong-order) | from the code | trivial |
| [CC tools report parser](#cc-tools-report-parser) | from the code | small, needs a log |
| [Cross-clock paths are never reported](#cross-clock-paths-are-never-reported) | yes, nextpnr | medium |
| [No FIFO reset and no reset synchronizers](#no-fifo-reset-and-no-reset-synchronizers) | from the code | medium |

### Crossing checks crash with `NameError`

*Verified* (`nonvolatile_cross.c`: a non-`volatile` crossing between 100 and 50 MHz;
`volatile_nonint.c`: a `volatile` crossing between 100 and 30 MHz).

**What happens.** For a crossing without flow control, `GET_CLK_CROSSING_INFO` runs two
checks. A non-`volatile` variable must have the same MHz and group on both sides, and the
ratio must be an integer with one group. Both are meant to print a message and continue
(the `sys.exit(-1)` after each is commented out), but the messages print `write_main_func`
and `read_main_func`, which do not exist in that function; it has the sets
`write_main_funcs` and `read_main_funcs`. Parsing stops with
`NameError: name 'write_main_func' is not defined`. The second check is not limited to
`volatile` variables, so a non-`volatile` crossing between two clocks would fail both.

**Where.** `C_TO_LOGIC.GET_CLK_CROSSING_INFO`, the branch that computes `ratio` for
crossings without `_<N>` sizes.

**Fix idea.** Print `sorted(write_main_funcs)` and `sorted(read_main_funcs)`, put the
second check under `is_volatile`, and make both checks errors. Continuing is worse than
stopping. A non-`volatile` variable between two clocks would get the ratio hardware of
[section 6](#6-integer-ratio-volatile-crossings) between clocks that need not be related.
A non-integer ratio would get a rounded `R` whose counter drifts against the slow clock. A
message along the lines of "Clock crossing `v` goes from `fast` (100.0 MHz) to `slow`
(30.0 MHz). Use a FIFO (`global_fifo.h`), or mark `v` `ASYNC_WIRE` and synchronize it
yourself. Ratio crossings need `volatile`, an integer frequency ratio and one clock group."
tells the user what to do.

**Test.** Build both scratch designs; expect exit status 1 and the message.

### Inference never ends when a crossing side spans two clocks

*Verified* (`two_domain_writers.c`: one FIFO written by MAINs at two frequencies). The
build was stopped by `timeout` after 60 s, with a 652 MB log holding about 5.6 million
copies of the warning.

**What happens.** In the crossing pass of `LOGIC.INFER_CLOCK_DOMAINS`, a write side (or
read side) whose MAINs with known clocks have more than one (MHz, group) prints
`WARNING: Cannot use clock crossing v written from multiple clock domains (mhz,group) {...}!`
and sets `inferring = True`. Nothing changes between passes, so the `while inferring`
loop never exits.

**Where.** `LOGIC.INFER_CLOCK_DOMAINS`, the two `len(..._mhz_group_tuples) > 1` branches.

**Fix idea.** Raise instead of looping, naming the MAINs on each (MHz, group). The check
that `VHDL.WRITE_MULTIMAIN_TOP` already has (`Cannot have multiple clock domains on the
write side of clock crossing v!`) shows the intended error; today it is only reached when
inference does not see the conflict.

A larger cleanup replaces the fixed-point loop with a union-find over MAINs:

1. Put two MAINs in one set when they use the same shared global that is not an
   `ASYNC_WIRE`, or sit on the same side of one crossing.
2. Each set may hold at most one known (MHz, group); more is an error that can name the
   chain of globals that joined the conflicting MAINs. Copy the known clock to the rest
   of the set.
3. For each crossing whose side still has no clock, give it the other side's clock (the
   current default), and repeat step 3 until nothing changes. This step only fills
   unknowns, so it cannot loop.

That also catches shared-global conflicts at parse time, with the names of the globals,
instead of in the VHDL writer.

**Test.** Build the scratch design under a short `timeout`; expect a prompt error.

### Unused and read-only FIFOs crash the top-level writer

*Verified* (`unused_fifo.c`: a `GLOBAL_FIFO` nothing calls; `read_only_fifo.c`: only its
read function is called).

**What happens.** `KeyError: '<name>_WRITE_1'` (see
[Unused and one-sided FIFOs](#unused-and-one-sided-fifos)). A library header that declares
a FIFO for an optional feature breaks every design that does not use the feature.

**Where.** `VHDL.WRITE_MULTIMAIN_TOP`, `write_func_insts = parser_state.FuncToInstances[write_func]`
in the crossing loop.

**Fix idea.** Decide once, right after elaboration, which crossings exist: drop from
`parser_state.clk_cross_var_info` every crossing whose functions have no instances, so
that the top-level writer, `WRITE_CLK_CROSS_ENTITIES`, the global-wires package and the
file list all agree. For a crossing with only a read side, either stop with "FIFO `v` is
read but never written" or keep it and tie the write side off (`write_enable => "0"`,
`in_clk` from the read clock), so that the reader sees `valid = 0`.

**Test.** Build both scratch designs: the unused FIFO should build, the read-only one
should give the message or a tied-off FIFO.

### Write-only FIFOs leave `ready` undriven

*Verified* (`write_only_fifo.c`).

**What happens.** No FIFO instance is written and nothing drives the writer's `ready`.
VHDL simulation sees `'U'`; synthesis picks a constant.

**Where.** `VHDL.WRITE_MULTIMAIN_TOP` skips crossings whose read function has no instances
(`# Do not even write instance if dont have read side func`).

**Fix idea.** Instantiate the FIFO with the read side tied off (`read_enable => "0"`,
`out_clk` from the write clock) and print a warning. The writer then sees a FIFO that
fills and stays full, as it would in hardware with no reader. Driving `ready` with a
constant `'0'` is the smaller alternative.

**Test.** Build the scratch design and check that the top level drives
`<main>.<name>_WRITE_1_return_output`.

### XPM FIFO depths must be powers of two

*Verified* (`async_xil_depth20.c`, Vivado 2019.2, Artix-7, `--comb`).

**What happens.** `FIFO_WRITE_DEPTH => 20` fails synthesis with
`[XPM_FIFO 1-4] FIFO_WRITE_DEPTH (20) value specified is non-power of 2`
([Which FIFO hardware is generated](#which-fifo-hardware-is-generated)). The built-in FIFOs
round the same depth up to 32.

**Where.** `VHDL.WRITE_CLK_CROSS_ENTITIES`, the `depth` written into the XPM generics.

**Fix idea.** Round up with `2**ceil(log2(depth))`, as for the built-in FIFOs, and print
the depth used. Optionally, use the built-in FIFO for depths below XPM's minimum of 16
instead of raising them to 16.

**Test.** A Vivado `--comb` build of a depth-20 FIFO (runs only where Vivado is
installed).

### Errors that exit with status 0

From the code.

**What happens.** Two error paths call `sys.exit(0)`, so scripts and CI see a success:

- `C_TO_LOGIC.GEN_CLOCK_CROSS_HEADERS`: a FIFO variable with more than one dimension
  prints `Only single dim in flow control crossing!`.
- *Fixed.* `VHDL.WRITE_CLK_CROSS_ENTITIES` called `SYN.PART_SET_TOOL(parser_state.part)`
  without `allow_fail` when a crossing had two clock names and no tool was chosen yet. With
  no part and no PyRTL, `PART_SET_TOOL` printed `Need to set FPGA part somewhere in the
  code to continue with synthesis tool support!` and exited with status 0. The FIFO choice
  is now `VHDL.CLK_CROSS_USES_XPM`, which picks the built-in FIFO when no tool is known.

**Fix idea.** Exit with a nonzero status in the first (or raise).

**Test.** `async_fifo_path_unit_test.py` checks the built-in choice with no tool.

### Quartus clock groups run together

*Verified* (the constraint writer called once per tool, with two and with three clocks;
`quartus_three_clocks.c`, three MAINs at 100, 50 and 25 MHz on a Cyclone V part, built
with Quartus Prime Lite 20.1 and `--comb`).

**What happens.** One `set_clock_groups` per pair of clocks, written without a newline.
With three clocks (the Quartus build's 100, 50 and 25 MHz) the file ends in one line:

```
set_clock_groups -asynchronous -group [get_clocks clk_100p0] -group [get_clocks clk_50p0]set_clock_groups -asynchronous -group [get_clocks clk_100p0] -group [get_clocks clk_25p0]set_clock_groups -asynchronous -group [get_clocks clk_50p0] -group [get_clocks clk_25p0]
```

Quartus reads the line as one command with extra arguments and ignores all of it:

```
Warning (332174): Ignored filter at clocks.sdc(4): _col4set_clock_groups could not be matched with a clock
Warning (332049): Ignored set_clock_groups at clocks.sdc(4): Argument -group with value _col4set_clock_groups could not match any element of the following types: ( clk )
Warning (332049): Ignored set_clock_groups at clocks.sdc(4): The clock clk_100p0 was found in more than one -group argument. A clock cannot be in a different group from itself.
```

So with three or more clocks no clock is asynchronous to any other in Quartus. The test
design has no paths between its clocks and still builds. In a design with crossings,
Quartus times the cross-clock paths, and if one of them is the worst path of a clock,
`QUARTUS.py` stops the build with `Multiple clocks in path report?`.

**Where.** `SYN.WRITE_CLK_CONSTRAINTS_FILE`, the `QUARTUS` branch.

**Fix idea.** Add the newline. Better, write the single command of the next-but-one entry,
which needs no pairs.

**Test.** An in-process test that loads a parsed two-clock design, adds a third clock to
`parser_state` and calls `WRITE_CLK_CONSTRAINTS_FILE` with `SYN.SYN_TOOL` set to each
backend module; no tools need to be installed.

### Quartus does not find user clocks

*Verified* ([#137](https://github.com/JulianKemmerer/PipelineC/issues/137), open;
`quartus_user_clock.c`, the issue's example, and `quartus_input_clock.c`, a `DECL_INPUT`
pin promoted with `CLK_MHZ`; both on Cyclone V with Quartus Prime Lite 20.1, `--comb`).

**What happens.** User clocks are constrained with `create_clock ... [get_nets
{clk_<...>}]`. Quartus does not match the kept internal signal name
(`clk_25p0 could not be matched with a net`), ignores the `create_clock`, and derives a
1 GHz clock on whatever it finds driving clock pins: the input register in the first
design, the port `pll_clk[0]` in the second. PipelineC's `report_timing -from_clock
clk_25p0` then fails, and with no other clock both builds stop with `Bad synthesis log?`
(exit status 255). See [User clocks](#user-clocks-clk_mhz-and-clk_mhz_group) for the log
lines.

**Where.** `SYN.WRITE_CLK_CONSTRAINTS_FILE`, `get_thing_cmd = "get_nets"` for names in
`GET_ALL_USER_CLOCKS`; `QUARTUS.py`, the per-clock `report_timing` lines and
`ParsedTimingReport`.

**Fix idea.** Two cases.

- A user clock driven by a top-level input (`DECL_INPUT` + `CLK_MHZ`): constrain the port,
  which every tool accepts. The input's name is in `parser_state.input_wires`, and the top
  level already assigns `clk_25p0 <= pll_clk(0);`. The port is a one-bit
  `unsigned(0 downto 0)`, so Quartus names it `pll_clk[0]` (as its derived clock shows):
  `create_clock -name clk_25p0 ... [get_ports {pll_clk[0]}]`. Keeping `-name clk_25p0`
  keeps the clock name the report parsers and the sweep expect. Tried by hand on a copy of
  the `quartus_input_clock.c` project: with only that line changed, rerunning
  `quartus_sta` on the generated script finds the clock, and
  `report_timing -from_clock clk_25p0` returns a path whose launch and latch clocks are
  `clk_25p0` (slack 35.611 ns at 25 MHz), the shape `QUARTUS.py` parses. The fitter reads
  the same file. nextpnr's `clocks.py` names nets rather than ports, so this change belongs
  in the SDC-style branch only.
- A clock generated in logic: Quartus accepts the full hierarchical name of the register
  that drives it (per the issue). `WRITE_MULTIMAIN_TOP` already builds the driver's
  instance path (`module_to_global.<main>.<inst>....<wire>`), and the entity names are
  known when constraints are written, so the constraint writer can produce that name.
  `create_generated_clock -source <parent clock> -divide_by <n>` would also tell the tool
  that the two clocks are related; PipelineC knows both declared frequencies, so `n` is
  known when the ratio is an integer.

**Test.** Needs Quartus: the two scratch designs above, built with `--comb`, should finish
and print an `FMAX` line for `clk_25p0`. The in-process constraint test can check the text
without Quartus.

### Tools without multi-clock constraints

*Verified* (constraint writer per tool, two and three clocks).

**What happens.** Gowin, Efinity, PyRTL and DEVICE_MODELS raise `How does tool <TOOL> deal
with async clocks?` for any whole-design run with two or more clocks. CC tools write
`#TODO`. Diamond writes no clock groups and stops on the first cross-clock critical path
(`Multiple clocks in path report?`).

**Where.** `SYN.WRITE_CLK_CONSTRAINTS_FILE`, the `len(clock_name_to_mhz) > 1` branch.

**Fix idea.** One branch in `SYN.py` for every SDC-style tool, with no backend edits: a
single command with one group per clock,

```
set_clock_groups -asynchronous -group [get_clocks {clk_10p0}] -group [get_clocks {clk_25p0}] -group [get_clocks {clk_50p0}]
```

declares every pair asynchronous without listing pairs, and it avoids the error the
Quartus branch's comment quotes ("The clock clk_100p0 was found in more than one -group
argument"), which came from putting every clock in both groups. Vivado (UG835), Quartus
and Efinity document `set_clock_groups -asynchronous` with any number of `-group` lists;
Gowin and Diamond have not been checked. For the tools that do not read the file:

- PyRTL and DEVICE_MODELS: skip the clock groups. Their one whole-netlist path is then
  given to every MAIN by the sweep's existing fallback (`WARNING: No start/end reg name in
  timing report! ...`). That over-constrains the slower domains but builds.
- CC tools: nothing useful can be written (`p_r` takes pin constraints only); the report
  parser is the problem (see [CC tools report parser](#cc-tools-report-parser)).
- Diamond with LSE (`.ldc`): try the same line once a license is available.

The report parsers must then return one path group per clock. Gowin and Efinity already
key their results by clock name.

**Test.** The same in-process constraint test as above, for every backend module.

### Vivado clock groups make every pair asynchronous

*Verified* (constraint writer; the `async_xil_comb` Vivado run accepts the file).

**What happens.** `-group [get_clocks *] -group [get_clocks *]` puts every clock in both
groups. Vivado accepts it and treats every pair of clocks as asynchronous. That is right
for FIFOs and `ASYNC_WIRE`, and wrong for the clocks of a ratio crossing
([section 6](#6-integer-ratio-volatile-crossings)), whose paths only work if they are
timed as paths between related clocks. PipelineC's own runs never time those paths, so a
ratio crossing that fails timing is invisible until hardware.

**Where.** `SYN.WRITE_CLK_CONSTRAINTS_FILE`, the `VIVADO` branch.

**Fix idea.** Use the one-group-per-clock command above, and put the two clocks of each
ratio crossing in one group (or leave both out of `set_clock_groups`) so that Vivado times
the paths between them. The board project must do the same for real hardware; a final
constraints file (see [No CDC attributes or constraints](#no-cdc-attributes-or-constraints))
could carry the groups there.

**Test.** The in-process constraint test, with a ratio crossing in the design.

### `MAIN_SYN_MHZ` on a shared clock depends on pragma order

*Verified* (`syn_mhz_shared_clock.c` and `syn_mhz_shared_clock_rev.c` through
`harness/syn_mhz_per_clock.py`, which parses the design and prints the clock map for
Vivado and nextpnr).

**What happens.** See [Synthesis-only targets](#synthesis-only-targets-main_syn_mhz): the
constraint for a clock takes the goal of the last MAIN on it in pragma order.

**Where.** `SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH`, `clock_name_to_mhz[clk_name] = clock_mhz`.

**Fix idea.** Keep the highest goal per clock name (the maximum over its MAINs, ignoring
`None`), and warn when MAINs on one clock disagree.

**Test.** The harness as an in-process test, in both pragma orders.

### A clock passed as a MAIN argument is registered by itself

*Verified* (`clock_as_main_arg.c`, the #137 example on an ECP5 part).

**What happens.** See [User clocks](#user-clocks-clk_mhz-and-clk_mhz_group): the synthesis
top's input register for the clock argument is clocked by the clock that comes out of it.
The final top is not affected.

**Where.** `VHDL.WRITE_MULTIMAIN_TOP`, `-- IO regs`.

**Fix idea.** When a user clock wire is written by a MAIN that has inputs, stop with a
message that points to `DECL_INPUT` + `CLK_MHZ`. Detecting exactly which input reaches the
wire needs a walk of the MAIN's logic; the simple test covers the known pattern, and the
replacement exists.

**Test.** Build the scratch design; expect the message.

### No CDC attributes or constraints

From the code; the Vivado synthesis log of the XPM build shows `ASYNC_REG` on Xilinx's own
synchronizers.

**What happens.** The synchronizer registers of the built-in async FIFO, the `CDC`/`CDC2`
registers of `cdc.h` and the first register behind an `ASYNC_WIRE` carry no `ASYNC_REG`
style attributes, and no constraint limits the delay into them. Under blanket clock groups
the Gray-coded pointer bits of the built-in FIFO have no skew limit, and a Gray-code
crossing depends on its bits arriving within about one period of each other. Only
`xpm_fifo_async` and `xil_cdc2_bit` bring Xilinx's CDC handling. The final outputs carry
no constraints at all.

**Fix ideas.**

- In `pipelinec_async_fifo_fwft.vhd`, set Vivado's `ASYNC_REG` attribute on
  `wr_ptr_gray_sync1_reg`, `wr_ptr_gray_sync2_reg`, `rd_ptr_gray_sync1_reg` and
  `rd_ptr_gray_sync2_reg`, and the matching Quartus synchronizer identification
  (an `altera_attribute`). Tools that do not know an attribute ignore it. The commented
  `SHREG_EXTRACT` lines can come back the same way.
- Constrain the pointer crossings with `set_max_delay -datapath_only` equal to the
  smaller of the two clock periods, from the Gray pointer register to the first
  synchronizer register. That is the usual constraint for Gray-coded crossings. The
  register names are fixed inside the entity, so the constraint can be written per
  crossing instance from the instance label. In Vivado, `set_clock_groups` takes priority
  over timing exceptions such as `set_max_delay` (UG903, "Asynchronous Clock Groups"), so
  this only works if the blanket clock groups are replaced: `set_max_delay -datapath_only`
  on the synchronized paths and `set_false_path` (or nothing) for the rest.
- Mark the `cdc.h` registers: a pragma on a function-local static (for example
  `#pragma ASYNC_REG regs`) that the VHDL writer turns into the attribute, or a
  vendor-neutral raw-VHDL synchronizer that `CDC` calls, as `xil_cdc2_bit` does for
  Xilinx.
- Give the user one constraints file. `SYN.WRITE_FINAL_FILES` writes `vhdl_files.txt` and,
  for Vivado, a `read_vhdl.tcl` that keeps only `read_vhdl`, `add_files` and
  `set_property` lines. A `pipelinec_final.xdc` / `.sdc` with the clock groups, the
  max-delay lines and the multi-cycle constraints would let a board project include
  everything with one line. The comment above the multi-cycle loop in
  `WRITE_CLK_CONSTRAINTS_FILE` asks the same question ("should mcps be in separate file? -
  how will user consume").

**Test.** For the attributes, grep the built-in FIFO's VHDL and the synthesis log (Vivado
reports `ASYNC_REG` cells). For the constraints, the in-process constraint test.

### `ASYNC_WIRE` is not a false path

From the code ([section 8](#8-async_wire)).

**What happens.** On a global whose users share one clock, `ASYNC_WIRE` only skips the
checks; the path is timed like any other. There is no way to say "this path does not need
to meet timing" ([#222](https://github.com/JulianKemmerer/PipelineC/discussions/222)).

**Fix idea.** A separate pragma (`FALSE_PATH v`) that writes `set_false_path` from the
writer's registers to the reader's, using the same cell-name machinery the multi-cycle
constraints use (`AUTO_MULTI_CYCLE.GET_MCP_PATH_CONSTRAINTS`), and that tells the sweep to
ignore those paths. Pypeline's `MULTI_CYCLE` tags cover the related case of a path that
has more than one cycle.

### FIFO restrictions

Partly verified (depth minimums and rounding in the generated VHDL; widths and instance
counts from the code).

**What happens.** Equal read and write widths (`Only equal read and write sizes for async
fifos for now, TODO!`), one write and one read instance, a one-dimensional array, minimum
depths of 2, 4 and 16, and power-of-two rounding in the built-in FIFOs only.

**Fix ideas.**

- Width ratios: when the read width is a multiple of the write width, collect writes into
  one wide word in the write domain (a small gearbox register) in front of a wide FIFO;
  for the opposite case, unpack after the FIFO in the read domain. `xpm_fifo_async`
  supports some width ratios itself, but not with `FIFO_MEMORY_TYPE => "auto"` (the
  generated instance's own comment says the widths must then be equal). This could live in
  the `global_fifo.h` macros rather than the compiler.
- More than one writer: a FIFO has one write port, so several writers need an arbiter in
  front of it. `ID_INST` already picks one instance. An `INST_ARRAY` of FIFOs (one crossing
  per array element) would let the shared resource bus stop unrolling up to 128 copies
  with the preprocessor.
- Print the size actually built: the depth after rounding and the number of words it
  holds (`2**DEPTH_LOG2 + 1` for the built-in FIFOs, see
  [Latency and capacity](#latency-and-capacity)).

### XPM wrapper assigns `rd_return_output.data` twice

*Verified* (generated `clk_cross_entities.vhd` of the XPM build).

**What happens.** The XPM branch emits `rd_return_output.data <= slv_to_<type>(dout_slv);`
twice (see [The XPM variant](#which-fifo-hardware-is-generated)). The record field is an
array of `std_logic`, which is resolved, and both drivers carry the same value, so
simulation and Vivado 2019.2 accept it without a warning.

**Where.** `VHDL.WRITE_CLK_CROSS_ENTITIES`, the two `rd_return_output.data <=` lines of the
XPM text.

**Fix idea.** Delete one.

### `ASYNC_WIRE` is ignored for `INST_ARRAY` globals

From the code.

**What happens.** The two `INST_ARRAY` clock checks in `VHDL.WRITE_MULTIMAIN_TOP`
(`Cannot have multiple clock domains for write shared instance array global ...` and the
read variant) do not consult `parser_state.async_wires`, so an instance array cannot cross
clocks even when marked. FIFOs cannot be `INST_ARRAY` members either (the comment in the
shared resource bus).

**Fix idea.** Skip both checks for globals in `parser_state.async_wires`, as the plain
shared-global check does.

### No multi-clock testbenches

*Verified* (the cocotb and Verilator flows on the two-clock ECP5 build of
`examples/async_clock_crossing.c`).

**What happens.** cocotb template generation raises `NotImplementedError`; the Verilator
`main.cpp` leaves its loop commented out; CXXRTL toggles only `clk` (see
[section 13](#13-simulation-support)).

**Fix ideas.**

- cocotb: start one `cocotb.clock.Clock(dut.<clock>, <period>, units="ps")` per clock with
  `cocotb.start_soon(...)`, and count the cycles of one reference clock for `--run N` and
  the `Clock: <n>` lines. The reference can be the fastest clock or one named on the
  command line. Keep the template's first-edge handling for `rising_edge`.
- Verilator and CXXRTL: generate a `main.cpp` that keeps the time in picoseconds, finds the
  next edge among all clocks (each clock's half period, rounded to whole picoseconds),
  sets every clock that toggles at that time, and calls `eval()` once per time step.
  [#328](https://github.com/JulianKemmerer/PipelineC/discussions/328) proposes generating
  the clocks in an HDL testbench instead; with Verilator 5's `--timing`, a SystemVerilog
  wrapper with one `always #<half period>` per clock around the converted top is the
  HDL-side version of the same loop.
- One helper that returns the clock schedule (names, periods from `MAIN_MHZ`, phases) and
  is used by every backend.

**Test.** The two-clock FIFO example with `--sim --cocotb --ghdl` and with `--sim
--verilator`, checking that both clocks advance and the test pattern arrives.

### Simulation clock list

From the code.

**What happens.** *Partly fixed.* `SIM.GET_SIM_GEN_INFO` built user clock names without
the group, so a `CLK_MHZ_GROUP` clock that is a top-level input was not removed and
renamed; it now builds them with `VHDL.CLK_MHZ_GROUP_TEXT(clk_mhz,
parser_state.clk_group.get(user_clk_name))`. Its frequencies are still `GET_TARGET_MHZ`
values, so with a synthesis-only tool the testbench period comes from `MAIN_SYN_MHZ`
instead of the real clock.

**Fix idea.** Take frequencies from `main_mhz`.

**Test.** An in-process test of `GET_SIM_GEN_INFO` on a design with a grouped input clock
and a `MAIN_SYN_MHZ`.

### Crossings are found by name

From the code.

**What happens.** See [How a crossing is recognized](#how-a-crossing-is-recognized). Any
call `<global>_READ(` or `<global>_WRITE(` (with or without `_<N>`) is a crossing, a
variable whose name contains `_READ` or `_WRITE` is cut at the wrong place by
`CLK_CROSS_FUNC_TO_VAR_NAME`, and the kind of a crossing follows from its function names,
the `volatile` qualifier and the two clock frequencies rather than from a declaration.
Because the back end also maps function names to variables with
`CLK_CROSS_FUNC_TO_VAR_NAME`, the convention binds any other front end too.

**Fix idea.** Record crossings when they are declared. The `global_fifo.h` macros already
emit `FUNC_WIRES` pragmas; they could also emit `#pragma CLK_CROSS_FIFO <name> <W>`, and
`GET_CLK_CROSSING_INFO` would read `parser_state` instead of searching text. A dictionary
filled by the front end, function name → crossing variable, would replace
`CLK_CROSS_FUNC_TO_VAR_NAME` in the back end. The text search can stay for the
generated-header syntax, with a deprecation warning.
[#225](https://github.com/JulianKemmerer/PipelineC/discussions/225) asks for the same
explicit kinds.

### Pipelined MAINs split FIFO handshakes across stages

*Verified* (`pipelined_between_fifos.c`: a stateless 250 MHz MAIN between two FIFOs,
nextpnr sweep).

**What happens.** See
[FIFO calls inside auto-pipelined MAINs](#fifo-calls-inside-auto-pipelined-mains): the
read lands in stage 0 and the write in stage 1, and nothing relates the two handshakes.
The cause is the one behind [#122](https://github.com/JulianKemmerer/PipelineC/issues/122):
handshake signals are sampled at the start of the pipeline and delayed with the data.

**Fix idea.** At least warn when the sweep adds stages to a MAIN whose crossing calls end
up in different stages, naming the calls and stages. The full fix is a credit or skid
structure around the pipeline, which is what `GLOBAL_VALID_READY_PIPELINE_INST` (C) and
`make_stream_auto_pipeline` (Pypeline) provide by hand; doing it automatically for any
MAIN is the #122 problem.

### `MAIN_MHZ f other_main` copies only the MHz

From the code.

**What happens.** The group of `other_main` is not copied, and `other_main`'s own pragma
must come earlier in the preprocessed text.

**Where.** `C_TO_LOGIC.APPEND_PRAGMA_INFO`, the `MAIN_MHZ` branch.

**Fix idea.** Resolve references after all pragmas are read, copy the group unless the
pragma gives one, and report reference cycles.

### Crossing tuple unpacked in the wrong order

From the code.

**What happens.** `WRITE_CLK_CROSS_ENTITIES` unpacks `write_read_main_funcs`, which is
stored (write, read), as `read_mains, write_mains`. Only the union is used, so the output
is correct.

**Fix idea.** Swap the names, or give `ClkCrossVarInfo` named fields (`write_mains`,
`read_mains`, `write_func`, ...) so that the order cannot be confused; the working
dictionaries in `GET_CLK_CROSSING_INFO` use the opposite order (see
[Per-variable and per-crossing records](#per-variable-and-per-crossing-records)).

### CC tools report parser

From the code.

**What happens.** `CC_TOOLS.PathReport` sets `path_group = "clk"` and then `None`, and keeps
the last `Maximum Clock Frequency` line of the log. A multi-clock design gets one number
under no clock name.

**Fix idea.** Parse the clock name from each frequency line, if `p_r` prints one line per
clock, and key the reports by clock name; drop the stray `None`. Needs a multi-clock
GateMate log to confirm the format.

### Cross-clock paths are never reported

*Verified* for nextpnr (the `Critical path report for cross-domain path` sections in the
log of the ECP5 `--comb` build).

**What happens.** No report parser reads cross-clock paths. Vivado does not time them
(blanket clock groups), and Quartus and Diamond stop if one is the worst path. For FIFO
pointers that is acceptable. For ratio crossings, `ASYNC_WIRE` flags between related
clocks, and logic in front of a synchronizer (which can glitch), it hides real problems.

**Fix idea.** Print the cross-domain sections nextpnr already writes, as information and
not as sweep input. Once targeted max-delay constraints exist (above), report their slack
the same way.

### No FIFO reset and no reset synchronizers

From the code.

**What happens.** The FIFOs reset only at power-on, through register initial values;
nothing can clear them later ([#349](https://github.com/JulianKemmerer/PipelineC/discussions/349)
asks the same for Pypeline's `make_fifo`). Resets are ordinary data
([#255](https://github.com/JulianKemmerer/PipelineC/discussions/255)), so a reset that
reaches several domains has to be synchronized by the user (`xil_cdc2_bit` in the RISC-V
examples).

**Fix idea.** Clearing an async FIFO must reset both pointers consistently: a clear request
synchronized into the other domain and acknowledged back, with `ready` and `valid` held
low until both sides are done. `xpm_fifo_async`'s `rst` does this and reports progress on
`wr_rst_busy`/`rd_rst_busy`, which the wrapper already uses, so connecting `rst` (which
must be synchronous to the write clock) to a write-domain clear signal is the smaller
step for Vivado. A per-domain reset synchronizer in `cdc.h` (with the attributes above)
covers the rest.

## 16. Ideas for multiple clock domains in Pypeline

This section is a set of proposals, not a description of existing behavior, apart from
[What Pypeline has today](#what-pypeline-has-today). It uses the
C front end's design (sections 1 to 14) and its problems ([section 15](#15-known-problems-and-fix-ideas))
to suggest how the Python front end could support more than one clock. The open questions
come from [#342](https://github.com/JulianKemmerer/PipelineC/discussions/342) ("an
annotation for asynchronous wires, a library function such as an async FIFO factory, or
both?" and "how should native simulation schedule several clock rates?") and
[#354](https://github.com/JulianKemmerer/PipelineC/issues/354).

### What Pypeline has today

From [pypeline_DESIGN.md](pypeline_DESIGN.md#main--mainfn--registering-mains),
[PY_TO_LOGIC_DESIGN.md](PY_TO_LOGIC_DESIGN.md#pypeline-pragmas-part--main_mhz) and the
code:

| Feature | Pypeline today | C equivalent |
|---|---|---|
| One clock per top-level function | `@MAIN`, `@MAIN(100.0)`, `@MAIN(mhz=100.0)`, `@MAIN(clk)`, `@MAIN(clock=clk)`, `MAIN(fn, clock=clk, name=...)`; `_register_main` stores the clock in the MAIN's record, `wrapped._pypeline_main.clock` | `#pragma MAIN`, `MAIN_MHZ` |
| Clocks | `make_clock(mhz, name=None, syn_mhz=None)` returns a clock value, identified by rate and name | `MAIN_MHZ`, `CLK_MHZ` |
| Synthesis-only target | `make_clock(..., syn_mhz=)`, written to `main_syn_mhz` | `MAIN_SYN_MHZ` |
| Clock groups | a clock's `name`, written to `main_clk_group` and `clk_group`; the port is `clk_<rate>_<name>` | `MAIN_MHZ_GROUP`, `MAIN_GROUP` |
| Inference for bare `@MAIN` | `PY_TO_LOGIC._assign_clocks`: a search from MAINs with clocks and stated-clock pins through plain wires and global instances, never through async wires or global FIFOs; a bare MAIN reached by two clocks is an error, an unreached one gets the default clock | `LOGIC.INFER_CLOCK_DOMAINS`, plus crossings |
| Named or generated clock | a clock bound to an `Input[uint1_t]` pin or a `Wire[uint1_t]`, written to `parser_state.clk_mhz` and `clk_group`; it must be some `@MAIN`'s clock, with one pin or wire per clock | `CLK_MHZ`, `CLK_MHZ_GROUP` |
| Same-clock wires between MAINs | `Wire[T]`, `Input[T]`, `Output[T]`, with multi-writer splitting and pipeline alignment (`VOLATILE` turns alignment off); each leaf is checked against its writer's clock (`_check_clock_crossings`) | shared globals |
| Crossing between clocks | `Wire[T, ASYNC]` (and async pins) with no added logic; a leaf read on another clock without one is an error naming both ends | `ASYNC_WIRE` |
| Native simulation | one loop, every `@MAIN` once per cycle; a design whose `@MAIN`s name more than one clock is refused with the clocks and their `@MAIN`s ([#354](https://github.com/JulianKemmerer/PipelineC/issues/354)) | none |
| VHDL simulation | the same cocotb template: one clock only | the same |
| Single-clock FIFO | `make_fifo` / `make_stream_fifo` over `pipelinec_fifo_fwft`, with a `@sim_model` | `FIFO_FWFT` |
| Global instance | `name: Inst[f]`: `f`'s ports as one global wire, and a compiler-made MAIN `<key>_INST` holding `f`, on the clock its users' MAINs infer through the wire ([guide](pypeline_guide.md#instf--global-instances)) | `GLOBAL_FUNC_INST`, `GLOBAL_PIPELINE_INST*`, `GLOBAL_VALID_READY_*_INST` |
| Global FIFO | `name: Fifo[T] = global_fifo(n)` (or `global_sync_fifo(n)`, `global_async_fifo(n)`, or a stream module) with `.wr` / `.rd` ends. On one clock, a global instance of the FIFO hardware, whose MAIN `<key>_FIFO` is added on its ends' clock. On two clocks, a `clk_cross_<key>_FIFO` crossing like `GLOBAL_STREAM_FIFO`'s, with two wiring MAINs `<key>_FIFO_wr` and `<key>_FIFO_rd`; `impl="builtin"` picks the built-in FIFO on Vivado ([guide](pypeline_guide.md#clock-crossing-fifos)) | `GLOBAL_FIFO`, `GLOBAL_STREAM_FIFO` |
| Crossing report | `clock_crossings.log` and `.json`: every async wire leaf and global FIFO, with clocks, kind, hardware and depth | none |

Everything below the front end is shared, so the back end handles several clocks for
Pypeline designs as it does for C: clock ports, user clocks, constraints, crossing entities
and the sweep's per-MAIN goals work as described in sections 11 and 12. The proposals
below were written before Pypeline had a way to say how data crosses or to name two clocks
of one rate; the syntax built from them is in
[pypeline_multiple_clock_domains.md](pypeline_multiple_clock_domains.md) and the guide's
[Part IV](pypeline_guide.md#part-iv--multiple-clock-domains). A simulation that runs clocks
at their own rates is still missing.

Two restrictions of the Pypeline language shape the proposals:

- Global wires are module-level declarations, found by scanning the module's source
  (`_discover_global_wires`). A library factory cannot create a new global wire per call.
  A crossing built from two halves, one function in each domain, therefore cannot be a
  pure library feature unless the user declares the wires between the halves.
- A raw-VHDL function (`vhdl(...)`) gets exactly one clock, its caller's `clk`. A
  dual-clock primitive such as an async FIFO or a dual-clock RAM cannot be a raw-VHDL
  library function.

### What to keep, what to leave behind

Keep, because it worked:

- **One clock per MAIN.** It keeps every function single-clocked, so the elaborator, the
  sweep and the native simulator stay single-clock inside a domain.
- **Clock names `clk_<MHz>[_<group>]`.** Report parsers, path groups and the sweep's
  attribution all key on them; the back end is front-end agnostic as long as Pypeline
  fills `main_mhz`, `main_clk_group`, `clk_mhz` and `clk_group`.
- **Inference for library MAINs.** Board modules such as the VGA PMOD drivers
  (`board_vga.vga_to_pmod8`) are written once with a bare `@MAIN` and take the user's
  clock. Pypeline already relies on this.
- **The async FIFO entity and its implementation choice.** `clk_cross_<var>` with
  `xpm_fifo_async` on Vivado and `pipelinec_async_fifo_fwft` elsewhere, power-on gating,
  and first-word-fall-through valid/ready semantics that match `make_fifo`.
- **An unsynchronized escape hatch** (`ASYNC_WIRE`) for flags and quasi-static values, with
  the user owning the synchronization.

Leave behind, because each one is a source of problems in section 15 or has a simpler
replacement:

| C mechanism | Why not port it | Replacement |
|---|---|---|
| Crossing detection by `_READ` / `_WRITE` names and regular expressions | silent misdetection, name restrictions, the back end bound to a naming convention | an explicit registry filled by the declaring call |
| Generated `clock_crossing/<var>.h` headers and `<T>_array_N_t` | needed only because C cannot declare functions from a pragma | Python factories |
| Integer-ratio `volatile` crossings | experimental, untimed under the blanket clock groups, alignment assumed and never checked, crashes for non-integer ratios | later, related clocks with ordinary timed wires (see [Related clocks](#related-clocks-later)) |
| Same-clock crossing wires, `wire.h` | replaced by shared globals in C already | `Wire[T]` |
| `IO_PAIR` arbitrated crossings | single-clock FSM machinery | Pypeline's `AUTO_FSM` and stream libraries |
| `ID_INST` | needed to pick one of several write instances by path | Python object identity: each factory call is one crossing |
| `MAIN_MHZ f other_main` | order-dependent string reference that drops the group | sharing one clock object |
| Wiring MAINs around FIFOs (`GLOBAL_STREAM_FIFO`'s `name_wr_stream_in` / `name_rd_stream_out`) | needed because C crossing functions are global functions; they add MAINs whose clocks must be inferred | call the FIFO's halves directly from any function in the right domain |
| The word "volatile" for crossings | Pypeline's `VOLATILE` already means "not pipeline-aligned" | a separate `ASYNC` marker |

### Recommended scope

The smallest useful version, in order of value:

1. **Refuse what is wrong today.** Native simulation of a design with more than one clock
   rate should stop with a clear message until it can schedule clocks
   ([#354](https://github.com/JulianKemmerer/PipelineC/issues/354) suggests this first
   step). Shared wires between clocks should fail at elaboration with the Python source
   line, not in the VHDL writer.
2. **Name domains**, including two clocks at one rate (clock objects with an optional
   group).
3. **Schedule clocks in native simulation** (an event loop over clock edges).
4. **`ASYNC` wires plus a small synchronizer library** for flags and quasi-static values.
5. **An async FIFO factory** that reuses the C back end's crossing entity, with a
   simulation model matching the measured latencies of
   [Latency and capacity](#latency-and-capacity).
6. **Multi-clock cocotb testbenches** and a clock-group fix in the constraint writer.

Things that sound useful but should wait until a design needs them: related clocks
(integer ratios timed as related), FIFO clear across domains, CDC lint beyond the simple
checks, vendor CDC primitives, per-path CDC constraints. Each is described below so the
first steps do not rule them out.

### Clock domains in the source

Two options; the second is recommended.

**Option A: extend the existing arguments.** `@MAIN(25.0, group="eth_rx")` and
`make_clock(25.0, group="eth_rx")`, written straight into `main_clk_group` and
`clk_group`. This is a direct port of `MAIN_MHZ_GROUP` / `CLK_MHZ_GROUP`, and it lifts
today's "two clocks at the same rate would collide" error. Functions in two places must
still agree on the same `(MHz, group)` strings.

**Option B: clock objects.** `make_clock` returns an object that names a domain, and
`@MAIN` accepts it:

```python
from pypeline import *

sys_clk = make_clock(100.0)                  # clock name clk_100p0
rx_clk = make_clock(25.0, group="eth_rx")    # clk_25p0_eth_rx
tx_clk = make_clock(25.0, group="eth_tx")    # clk_25p0_eth_tx: same rate, different clock

# Bind a clock to a top-level pin or a generated wire, as make_clock does today:
eth_rx_clk_pin: Input[uint1_t] = rx_clk

@MAIN(clock=rx_clk)
def rx_main(): ...

@MAIN(clock=sys_clk)
def app(): ...

@MAIN(100.0)              # still allowed: an unnamed clock at 100 MHz, same as sys_clk
def other(): ...
```

- One object replaces `MAIN_MHZ`, `MAIN_GROUP`, `CLK_MHZ`, `CLK_MHZ_GROUP` and
  `MAIN_MHZ f other_main`. Functions that must share a clock share the object, so there is
  nothing to match by string and no order dependence.
- It maps onto the same `ParserState` fields: the object's MHz and group become
  `main_mhz` / `main_clk_group` for each `@MAIN` that uses it, and `clk_mhz` / `clk_group`
  for a wire it is bound to. The back end needs no change.
- Today's rule that a `make_clock` rate must match some `@MAIN` rate becomes "a clock bound
  to a wire must be used by some `@MAIN`", checked by identity.
- `make_clock(mhz, syn_mhz=...)` can carry the synthesis-only target, which Pypeline lacks
  today. The constraint writer should then keep the highest goal per clock (see
  [section 15](#main_syn_mhz-on-a-shared-clock-depends-on-pragma-order)).
- A bare `@MAIN` still gets its clock by inference, so board modules keep working.
- The group defaults to `None`; two unnamed clocks at one rate stay one clock, as in C.
  Giving a clock a `name=` that becomes the group, instead of a separate `group=`, is a
  matter of taste.

Native simulation needs the same information. In a `pypelinec --sim` run the build can
pass a map of MAIN to clock, the way `SIM.DO_OPTIONAL_SIM` already passes MAIN latencies to
`pypeline_sim.run_sim`. A standalone native run has only the registries, so a bare
`@MAIN` there either needs the same inference (it only needs the call graph and the wire
users, both available after import) or is placed on the design's only clock.

### Asynchronous wires

Add an `ASYNC` marker next to `VOLATILE`: `Wire[T, ASYNC]` and `Input[T, ASYNC]`.

```python
from cdc import make_sync_bits    # library sketch below
sync_bit = make_sync_bits(uint1_t)

cam_init_done: Wire[uint1_t, ASYNC]

@MAIN(clock=cam_clk)
def camera():
    done: Reg[uint1_t]
    ...
    cam_init_done = done          # driven straight from a register

@MAIN(clock=sys_clk)
def app():
    init_done = sync_bit(cam_init_done)   # two synchronizer registers in this domain
```

- **Hardware for free.** `_discover_global_wires` adds the name to
  `parser_state.async_wires`. The back end then skips inference through the wire and the
  shared-global clock check, and connects writer to readers across clocks, exactly as
  for C's `ASYNC_WIRE` on a shared global ([section 8](#8-async_wire)).
- **Alignment.** An asynchronous value has no stage in a pipeline of another clock, so
  `ASYNC` implies `VOLATILE`'s "read where used, drive when ready".
- **Checks C does not have.** The elaborator knows each wire's driver:
  - The writer should drive the wire directly from a `Reg`, with no logic between them.
    Logic in front of a crossing can glitch, and a glitch can be captured. This can be
    an error.
  - Each read should go straight into the first register of a synchronizer (see the
    library below). This is a warning, because quasi-static configuration values are
    sometimes read directly on purpose.
  - A multi-bit `ASYNC` wire read through a plain bit synchronizer is a classic bug
    (bits can be captured in different cycles). Warn unless the value is Gray-coded or
    held stable by a handshake, which the library functions declare.
- **Inputs.** `Input[T, ASYNC]` marks a pin that is not synchronous to any domain, such as
  a button. Plain `Input[T]` keeps today's meaning: synchronous to the domain that reads
  it.
- **Constraints.** Clock groups (or per-path exceptions, see
  [Constraints and timing](#constraints-and-timing)) keep these paths out of the sweep.

`Wire[T, ASYNC]` between functions of one domain has no meaning and should be an error, or
a warning that the marker does nothing (unlike C, where it quietly skips the checks).

### Synchronizer library

With `ASYNC` wires and one register tag, synchronizers are ordinary single-domain
functions and can be pure Pypeline (an `include/pypeline/cdc.py`, say):

```python
def make_sync_bits(t, stages=2):
    @hw_func
    def sync_bits(x: t) -> t:
        s: Reg[t[stages], SYNC_REG]     # tag: synchronizer flip-flops
        out = s[stages - 1]
        for i in range(stages - 1, 0, -1):
            s[i] = s[i - 1]
        s[0] = x
        return out
    return sync_bits
```

- `SYNC_REG` is a new `Reg` tag, like `MULTI_CYCLE[n].start`. The VHDL writer turns it
  into vendor attributes on the register signal (`ASYNC_REG` for Vivado, synchronizer
  identification for Quartus; others ignore unknown attributes) and a `dont_touch`, the
  way multi-cycle tags already get `dont_touch`
  ([AUTO_MULTI_CYCLE_DESIGN.md](AUTO_MULTI_CYCLE_DESIGN.md#2-constraints)). The constraint
  writer can find the cells the same way the multi-cycle code does.
- Two-sided helpers need a wire between their halves, and a factory cannot declare one
  (see [What Pypeline has today](#what-pypeline-has-today)). Either the user declares the
  `ASYNC` wires and passes them in, or Pypeline gets factory-created global wires (a
  `make_wire(T, ASYNC)` returning an object that elaborates like a module-level wire),
  which would help other libraries too. With that:
  - `make_pulse_sync()`: a toggle register in the source domain, `sync_bits` and an edge
    detector in the destination.
  - `make_handshake_sync(T)`: a multi-bit value held stable by a request/acknowledge pair,
    for slow configuration data ([#340](https://github.com/JulianKemmerer/PipelineC/discussions/340)
    asks for a FIFO-like handshake interface between functions).
  - `make_reset_sync()`: a reset level synchronized into each domain.
- Each gets a native simulation model that is exact at the register level, so the
  synchronizer latency shows up in simulation as in hardware.

### Async FIFOs

A FIFO needs a dual-clock memory, which neither a raw-VHDL function nor two single-clock
halves can provide. The C back end already has the primitive, so the proposal is a
factory that registers a crossing the back end knows:

```python
from pypeline import *
from async_fifo import make_async_fifo, make_async_stream_fifo

pixels = make_async_fifo(pixel_t, 256, name="pixels")

@MAIN(clock=sys_clk)
def producer():
    p: Reg[pixel_t]
    w = pixels.write(p, 1)        # -> .ready
    if w.ready:
        p = next_pixel(p)

@MAIN(clock=pixel_clk)
def consumer():
    r = pixels.read(1)            # -> .data, .valid (first word fall through)
    if r.valid:
        drive(r.data)
```

What the front end would do, in terms of existing structures:

1. The factory returns an object with two `@hw_func` halves and records the crossing in a
   module-level registry (like `_main_registry`): name, element type, depth, the two
   functions.
2. `PARSE_FILE` creates the `ParserState` entries the C front end creates: a global
   `<name>` of type `T[depth]` in `global_vars`, a `ClkCrossVarInfo` with
   `flow_control=True`, sizes `(1, 1)` and the write and read MAINs (the MAINs above the two
   functions), and `is_clock_crossing` on both functions.
3. The back end then writes `clk_cross_<name>`, picks XPM or the built-in FIFO, routes the
   record fields and adds the file to the file list, unchanged. The one coupling to
   remove first is `LOGIC.CLK_CROSS_FUNC_TO_VAR_NAME`: either name the halves
   `<name>_WRITE_1` / `<name>_READ_1`, or replace that function with a dictionary filled
   by both front ends (which also fixes [Crossings are found by name](#crossings-are-found-by-name)
   for C).
4. The C checks carry over with Python source locations: one write instance and one read
   instance (two calls of `pixels.write` in different places is an error that names
   both), each side on one clock, and the [unused and one-sided](#unused-and-one-sided-fifos)
   cases handled on purpose instead of by a `KeyError`.
5. `make_async_stream_fifo(T, depth)` is pure Pypeline on top, like `make_stream_fifo`
   on `make_fifo`, and replaces `GLOBAL_STREAM_FIFO` without wiring MAINs.

Improvements over the C FIFO, all small:

- Round the XPM depth to a power of two, and expose `.capacity_beats` (memory plus output
  register) as `make_stream_fifo` does.
- A same-clock FIFO from this factory should build `pipelinec_fifo_fwft`, as C does, so a
  design can move a FIFO between domains without changing code.
- The simulation model follows the measured latencies: `valid` three read-clock edges after
  the write edge, `ready` back two write-clock edges after a pop, `2**DEPTH_LOG2 + 1` words.
  The model keeps the words in a queue with the write-domain edge count at which each was
  written, and the read side makes a word visible only after enough read-domain edges.
  With the clock scheduler below, that is exact for the built-in FIFO.
- A FIFO call inside an `AUTO_PIPELINE`d function should either be refused or come
  through a credit-based wrapper like `make_stream_auto_pipeline`, instead of C's silent
  split of the handshake over two stages
  ([section 15](#pipelined-mains-split-fifo-handshakes-across-stages)).

### Native simulation with several clocks

Today `_run_clock_cycle` evaluates every MAIN and commits every register once per step.
A multi-clock version can keep that machinery and change what a step is:

1. **Time.** Each domain has a period from its MHz, kept exactly as a fraction
   (`1 / fractions.Fraction(str(mhz))` microseconds) so that coincident edges compare
   equal; floating-point periods would drift apart. Rising edges are at
   `phase + k * period`, with a default phase of 0 for every clock.
2. **Events.** The loop jumps from one edge time to the next. At each time, the active
   domains are those with an edge there.
3. **Evaluate all, commit some.** Run the existing convergence loop over all MAINs, so that
   every wire, including `ASYNC` ones, has the value it has just before the edge. Then
   commit only the registers written by MAINs of active domains, and run the final pass
   (`@sim_output`, `sim_print`) only for those MAINs. Register writes already go through
   `_sim_reg_write_buffer` while `_sim_current_main` is set, so tagging each buffered write
   with its MAIN's domain is enough to commit selectively.
4. **Coincident edges** commit together: every domain samples the values from before the
   edge. That matches related clocks exactly, and for unrelated clocks it is one valid
   outcome of a real race.
5. **Per-domain state.** The pipelined-MAIN write queues (`_sim_pipelined_main_info`),
   AUTO_PIPELINE delay lines, `@sim_input` caches and cycle counters advance only for
   active domains.
6. **Cost.** Evaluating every MAIN at every event costs about as much as running all
   MAINs at the fastest rate. The convergence loop's reader tracking can later limit the
   evaluation to active MAINs plus the readers of wires that changed.

Decisions to make:

- **What `--run N` counts.** The edges of one reference domain: the fastest, the domain of
  the first `@MAIN`, or one named with an option. A `--run_ns` option is the unambiguous
  alternative.
- **Generated clocks.** A clock that a design generates in logic (`examples/internal_clocks.c`
  in C, `make_clock` on a `Wire` in Pypeline) can be simulated from its declared MHz
  (ideal, simple) or from the wire's actual rising transitions (exact, and it catches a
  divider that does not toggle as declared). The second needs the scheduler to create
  edge events from wire changes, after the generating domain commits.
- **Phases and CDC testing.** All clocks starting at 0 is deterministic but tests only one
  phase relationship. A seeded random phase per clock, or an option on the synchronizer
  models to add a random extra cycle, exercises the crossing logic the way real
  metastability resolution varies.
- **Output.** `sim_print` lines need the domain and that domain's cycle (or the time), and
  native-versus-VHDL comparison has to compare per domain, because the order of prints
  from different domains at one time is not defined.

### VHDL simulation and testbenches

- **cocotb.** Start one `cocotb.clock.Clock` per clock with the periods from `MAIN_MHZ` (not
  the synthesis target), with the same phase convention as the native scheduler, and
  count edges of the reference domain. This is the fix for
  [No multi-clock testbenches](#no-multi-clock-testbenches) and serves both front ends.
- **GHDL directly.** A generated VHDL testbench with one clock process per domain
  ([#328](https://github.com/JulianKemmerer/PipelineC/discussions/328)) avoids cocotb's
  per-edge Python overhead for long runs.
- **The XPM FIFO** cannot be elaborated by GHDL, so VHDL simulation of a Vivado-targeted
  design needs either Xilinx's simulation libraries or a switch that builds the built-in
  FIFO for simulation. The second is a one-line decision in `WRITE_CLK_CROSS_ENTITIES`
  (simulation build: built-in FIFO), at the price of simulating a different FIFO than
  the one synthesized. The native model can match one of the two exactly, not both.

### Constraints and timing

- **Clock groups.** Use the one-command-per-design form
  (`set_clock_groups -asynchronous -group [get_clocks {a}] -group [get_clocks {b}] ...`) on
  every SDC-style tool ([Tools without multi-clock constraints](#tools-without-multi-clock-constraints)).
  That removes the exception that stops multi-clock builds on Gowin and Efinity, and the
  run-together lines Quartus ignores, with no front-end work. Gowin's support for the
  command has not been checked.
- **Synchronizers and `ASYNC` wires.** For PipelineC's own timing runs, clock groups are
  enough: the paths are not part of any MAIN's timing. For real hardware, emit a final
  constraints file with the same groups. If per-path limits are wanted later
  (`set_max_delay -datapath_only` for Gray-coded or multi-bit crossings), the groups must be
  replaced by per-path exceptions in Vivado, because groups take priority there (UG903).
- **The sweep.** Each MAIN is judged against its own clock already. Crossing paths should
  never be pipelined: the FIFO and synchronizer functions must keep
  `CAN_HAVE_ADDED_LATENCY` false (C's crossing functions already do), and `SYNC_REG`
  registers must never be retimed (`dont_touch`).

### Resets

PipelineC has no reset concept beyond power-on initial values; resets are data
([#255](https://github.com/JulianKemmerer/PipelineC/discussions/255),
[#266](https://github.com/JulianKemmerer/PipelineC/discussions/266)). With several clocks:

- A reset from a pin or a PLL lock signal must be synchronized into each domain before
  use: `make_reset_sync()` above, or a `make_sync_bits(uint1_t)` function on an
  `Input[uint1_t, ASYNC]`.
- Clearing an async FIFO needs a handshake between domains (see
  [No FIFO reset and no reset synchronizers](#no-fifo-reset-and-no-reset-synchronizers)).
  A `clear` argument on the write half of `make_async_fifo`, connected to `xpm_fifo_async`'s
  `rst` and to a new clear path in the built-in FIFO, with `ready` and `valid` low until
  both sides finish, covers it. [#349](https://github.com/JulianKemmerer/PipelineC/discussions/349)
  asks for the single-clock version for `make_fifo`.

### Related clocks (later)

Clocks from one PLL with an integer ratio can exchange data through ordinary wires if the
timing tools know they are related; that is what C's ratio crossings tried to do without
telling the tools. A Pypeline version:

- `make_clock(200.0, related_to=sys_clk)` (the ratio follows from the MHz, which must be an
  integer multiple). Related domains go in one SDC clock group, so the tool times paths
  between them; for real hardware they must come from one PLL or MMCM.
- A plain `Wire[T]` between related domains is then legal and timed. The user's logic
  decides which fast cycle lines up with a slow edge; a library phase counter
  (`make_phase_counter(sys_clk, fast_clk)`) can provide it.
- The native scheduler handles related clocks exactly: their edges coincide every
  `ratio` fast edges.
- This is the clean form of [#232](https://github.com/JulianKemmerer/PipelineC/discussions/232)
  (several rates within one function, "double pumping") and
  [#254](https://github.com/JulianKemmerer/PipelineC/discussions/254) (running a pipeline
  on a faster clock to share resources).

### How C clock-domain code would translate

Under these proposals (option B for clocks), the C constructs of sections 2 to 9 map like
this. [pipelinec_to_pypeline.md](pipelinec_to_pypeline.md) would gain these rows once
they exist.

| C | Pypeline under the proposal |
|---|---|
| `#pragma MAIN_MHZ f 100.0` | `@MAIN(100.0)` (as today) or `@MAIN(clock=clk_100)` |
| `MAIN_MHZ_GROUP(f, 25.0, rx)`, `#pragma MAIN_GROUP f rx` | `rx = make_clock(25.0, group="rx")`, `@MAIN(clock=rx)` |
| `#pragma MAIN_MHZ f other_main` | the same clock object on both `@MAIN`s |
| `#pragma MAIN_SYN_MHZ f 147.0` | `make_clock(125.0, syn_mhz=147.0)` |
| `DECL_INPUT(uint1_t, pll_clk)` + `CLK_MHZ(pll_clk, 25.0)` | `pll_clk: Input[uint1_t] = clk_25` (today: `make_clock(25.0)`) |
| a `CLK_MHZ` wire written by a clock-divider MAIN | `slow_clk_wire: Wire[uint1_t] = slow`, written by a `@MAIN(clock=fast)` |
| shared global between MAINs on one clock | `Wire[T]` (as today) |
| `#pragma ASYNC_WIRE v` on a shared global | `v: Wire[T, ASYNC]` |
| `CDC2(type, name, regs, lhs, rhs)`, `xil_cdc2_bit(x)` | a function from `make_sync_bits(T)`, whose registers carry the `SYNC_REG` tag |
| `GLOBAL_FIFO(T, name, DEPTH)`, `ASYNC_CLK_CROSSING(...)` | `name = make_async_fifo(T, DEPTH)`; `name.write(...)`, `name.read(...)` |
| `GLOBAL_FIFO_WIDTH_DEPTH(T, name, W, DEPTH)` | `make_async_fifo(T[W], DEPTH)` (one word holds `W` elements) |
| `GLOBAL_STREAM_FIFO(T, name, DEPTH)` and its skid variants | `make_async_stream_fifo(T, DEPTH)`, with the existing skid buffer library around it |
| `volatile` ratio crossing | not ported; related clocks later |
| same-clock crossing wires, `WIRE_READ` / `WIRE_WRITE` | `Wire[T]` |
| `IO_PAIR`, `ID_INST` | not needed |

### Suggested order of work and tests

| Step | Work | Size | Test |
|---|---|---|---|
| 1 | Native sim refuses designs with more than one clock name; Pypeline elaboration rejects a shared wire used on two clocks, with the source line | small | native run of #354's two-rate example expects the refusal; a two-clock shared `Wire` expects the elaboration error |
| 2 | Clock objects (`make_clock(mhz, group=..., syn_mhz=...)`, `@MAIN(clock=...)`) | small | two clocks at 25 MHz build with two ports; the constraint file lists both |
| 3 | Clock groups in the constraint writer for every SDC tool (C fix as well) | small | the in-process constraint test from section 15 |
| 4 | Multi-clock native scheduler | medium | #354's example: the 50 MHz counter advances once per two 100 MHz cycles; coincident edges commit together |
| 5 | `Wire[T, ASYNC]`, `SYNC_REG`, `make_sync_bits` | small to medium | build, native sim and GHDL agree on a flag crossing from 100 to 33 MHz; the `ASYNC_REG` attribute is in the VHDL |
| 6 | `make_async_fifo` on the crossing back end, with its model | medium | the C `async_clock_crossing.c` test pattern rewritten in Python: native sim and GHDL (built-in FIFO) give the same cycle-by-cycle trace per domain |
| 7 | Multi-clock cocotb template | medium | step 6's design runs under `--sim --cocotb --ghdl` without a hand-written testbench |
| 8 | Later: factory-created wires, pulse and handshake syncs, FIFO clear, related clocks, CDC lint, per-path constraints | — | — |

Step 3 helps C designs too. Steps 4 to 7 are where Pypeline would go beyond the C front
end: crossings that simulate natively at the right rates, with the same FIFO hardware.

### Open questions

- Clock objects (option B) or extra arguments (option A)? B is a little more work and
  removes a class of string-matching mistakes.
- Should `ASYNC` reads outside a synchronizer be errors or warnings?
- Should native simulation model `xpm_fifo_async` (what Vivado builds) or the built-in FIFO
  (what GHDL can simulate) when the two differ in latency?
- Is the per-domain cycle count or the simulation time the key for comparing native and
  VHDL simulation output?
- Are factory-created global wires wanted for other reasons? If yes, more of the CDC
  library can be pure Pypeline.

## History

Why things are the way they are. Entries are keyed by topic, not date; when something
changes, revise the entry that owns the topic. Commit hashes point at the change that
introduced each behavior.

### Shared globals replaced same-clock crossings

Globals were first private to one function, like `static` locals, and moving a value
between MAINs on one clock needed a crossing variable with `WIRE_WRITE` / `WIRE_READ`
(`wire.h`, `1b262201`). [#73](https://github.com/JulianKemmerer/PipelineC/issues/73) made
globals usable directly between functions. Two semantics were weighed there: readers see
the writer's register output (one cycle later, no combinational path between MAINs), or
readers see the value the writer computes in the same cycle. The second was chosen ("wire
going into D, not wire from Q"), so shared globals behave like the old wires; the cost is
that combinational paths can span MAINs. The same-clock crossing machinery stayed for the
libraries that still use it.

### `ASYNC_WIRE` is a pragma, not a kind of crossing

[#68](https://github.com/JulianKemmerer/PipelineC/issues/68) asked for crossings that are
always plain wires. Because it overrides what the compiler would otherwise build, it
became a pragma on an existing variable rather than a new declaration syntax (`6f79b91a`,
together with `CLK_MHZ` user clocks in `4cc20c21`).
[#225](https://github.com/JulianKemmerer/PipelineC/discussions/225) still proposes making
every crossing kind explicit in its declaration, with `ASYNC_WIRE` as one of them.

### FIFO syntax: generated headers, then macros

Flow-controlled crossings began as XPM async FIFOs declared with `T v[DEPTH];` and a
generated `clock_crossing/v.h` (`d38fed85`, example in `c73577de`). `clock_crossing.h`
and `global_fifo.h` (`71da067e`) replaced the generated header for FIFOs with macros that
declare the functions directly; `GLOBAL_STREAM_FIFO` (`b34d3c5a`) and its skid-buffer
variants (`db23de97`) added valid/ready stream wires on top. Ratio crossings still need
the generated header; [#327](https://github.com/JulianKemmerer/PipelineC/discussions/327)
proposes generated struct types so that they can use macros too.

### FIFO implementations

The first FIFOs were `xpm_fifo_async` only, so they needed Vivado for synthesis and
Xilinx libraries for simulation. Same-clock FIFOs moved to the built-in synchronous FIFO
(`e72adb1d`: "Makes simulating shared bus easier and not device specific for cdc prims").
A vendor-independent async FIFO followed for every tool other than Vivado (`fba3c867`), and
it was rewritten without VHDL-2008 features so Quartus Lite can compile it (`da987bdb`,
[#293](https://github.com/JulianKemmerer/PipelineC/issues/293)). Vivado keeps XPM, which
brings Xilinx's own CDC constraints and attributes. The single-clock entity
`pipelinec_fifo_fwft` comes from [#142](https://github.com/JulianKemmerer/PipelineC/issues/142),
where the earlier primitive-based `FIFO_FWFT` paused for two cycles after one cycle of
backpressure.

### Clock inference

`#pragma MAIN` without a frequency, inferred from the globals and crossings a MAIN shares,
and `MAIN_MHZ` naming another MAIN, came in `ab8c5d4b`. Library MAINs (LED ports, wiring
MAINs, register MAINs, debug probes) depend on it.

### Clock groups and user clocks

Clock groups (`7df8ec46`) were added for the TEMAC example, whose RX and TX clocks share a
frequency but are not the same clock. User clock wires came with `CLK_MHZ` (`4cc20c21`);
`17f1a772` fixed the VHDL for user clocks that are also shared global wires, and
`8dbaed0a` added groups to them (`CLK_MHZ_GROUP`). Bringing a clock pin in through
`DECL_INPUT` + `CLK_MHZ` closed [#138](https://github.com/JulianKemmerer/PipelineC/issues/138);
the Quartus constraint problem moved to [#137](https://github.com/JulianKemmerer/PipelineC/issues/137).

### Integer-ratio crossings

The ratio crossing was confirmed in hardware on an Arty board (`5bf314c7`), and
`3a1ae904` made functions with state that are called conditionally get clock enables,
which the crossing examples use. It has stayed experimental: it depends on related,
aligned clocks that nothing checks, and PipelineC's own constraints treat its clocks as
asynchronous.

### Synthesis-only targets

`MAIN_SYN_MHZ` (`db27593c`) separates the real clock, which names the port, from the
target given to synthesis-only runs, so a design can ask synthesis for margin.

### Arbitrated crossings

Single-instance FSM functions shared by several callers, with N-way arbitration and the
`IO_PAIR` pragma, came in `de8c2b42`. They reuse the crossing machinery on one clock.

### Where the code lives

`9def28f4` folded `SW_LIB.py` into `C_TO_LOGIC.py` and moved the shared IR to `LOGIC.py`.
Older commits and issues refer to `SW_LIB.py`; crossing detection and header generation
are now in `C_TO_LOGIC.py`, inference and the crossing records in `LOGIC.py`.
