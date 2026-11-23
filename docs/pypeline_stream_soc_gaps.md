# Pypeline Gaps for Recreating StreamSoC

What Pypeline HDL ([pypeline_guide.md](pypeline_guide.md)) is missing before it can
recreate the PipelineC StreamSoC design
([examples/stream_soc/cpu/hardware/top.c](../examples/stream_soc/cpu/hardware/top.c),
[wiki page](https://github.com/JulianKemmerer/PipelineC/wiki/Example:-StreamSoC)), ranked
from the largest missing effort to the smallest. Hardware and software are both covered.

Multiple clock domains are left out on purpose. Pypeline supports them
([Part IV of the guide](pypeline_guide.md#part-iv--multiple-clock-domains)), with the
limits that guide lists, but every gap below is described as if the SoC ran on one clock.
The CPU part (gaps 4, 8 and 9) has its own plan, [cpu_planning.md](cpu_planning.md).
Statements rechecked against commit `b88f7600` say so.

## Table of Contents

- [Summary ranking](#summary-ranking)
- [What already maps](#what-already-maps)
- [1. Python software on the CPU](#1-python-software-on-the-cpu)
- [2. Shared resource bus and AXI memory-mapped library](#2-shared-resource-bus-and-axi-memory-mapped-library)
- [3. Generating module-level hardware from Python code](#3-generating-module-level-hardware-from-python-code)
- [4. RISC-V CPU, memory map and firmware memories](#4-risc-v-cpu-memory-map-and-firmware-memories)
- [5. Dataflow device libraries](#5-dataflow-device-libraries)
- [6. Functions shared by hardware and software](#6-functions-shared-by-hardware-and-software)
- [7. Simulating a whole SoC](#7-simulating-a-whole-soc)
- [8. Register map builder](#8-register-map-builder)
- [9. Exporting the hardware interface to C software](#9-exporting-the-hardware-interface-to-c-software)
- [10. Board support and vendor IP](#10-board-support-and-vendor-ip)
- [11. Small language gaps and bugs](#11-small-language-gaps-and-bugs)
- [Suggested order of work](#suggested-order-of-work)

## Summary ranking

Sizes are rough estimates of one person's effort, not measurements:
**XL** more than 6 weeks, **L** 3 to 6 weeks, **M** 1 to 3 weeks, **S** a few days to a
week, **XS** hours. "Required" means StreamSoC cannot be rebuilt in Pypeline without it;
"No" means there is a workaround or it is an improvement over what the C version does.

| Rank | Gap | Kind | Size | Required |
|---|---|---|---|---|
| 1 | [Python software on the CPU](#1-python-software-on-the-cpu) (MicroPython-like) | Software + hardware | XL | No: C firmware keeps working |
| 2 | [Shared resource bus and AXI memory-mapped library](#2-shared-resource-bus-and-axi-memory-mapped-library) | Library | L to XL | Yes |
| 3 | [Generating module-level hardware from Python code](#3-generating-module-level-hardware-from-python-code) (library-made wires and instances, instance arrays; factory MAINs are done) | Compiler | M | No: hand-written wiring works, but every library in 2 and 4 needs boilerplate |
| 4 | [RISC-V CPU, memory map and firmware memories](#4-risc-v-cpu-memory-map-and-firmware-memories) | Library | L | Yes |
| 5 | [Dataflow device libraries](#5-dataflow-device-libraries) (Ethernet, FFT, camera, video, GPU) | Library | M each, L total | Yes |
| 6 | [Functions shared by hardware and software](#6-functions-shared-by-hardware-and-software) | Compiler or tooling | M to L | No: duplicate the code by hand |
| 7 | [Simulating a whole SoC](#7-simulating-a-whole-soc) | Simulation | M | For verification |
| 8 | [Register map builder](#8-register-map-builder) | Library | S to M | Yes |
| 9 | [Exporting the hardware interface to C software](#9-exporting-the-hardware-interface-to-c-software) | Tooling | S | Yes, while firmware is C |
| 10 | [Board support and vendor IP](#10-board-support-and-vendor-ip) | Library + small compiler fixes | S | Partly |
| 11 | [Small language gaps and bugs](#11-small-language-gaps-and-bugs) | Compiler | XS each | Workarounds exist |

## What already maps

Most of the language StreamSoC needs is already in Pypeline. These parts port without new
features:

| StreamSoC uses (C) | Pypeline today |
|---|---|
| `#pragma PART`, `board/arty.h` part | `PART()`, `board.arty.part100t` |
| `DECL_INPUT`/`DECL_OUTPUT`, `_REG` variants | `Input[T]`/`Output[T]`, plus a `Reg[T]` |
| `MAIN` with struct args/return for the MIG DDR3 ports (`xil_mem_module`) | `@MAIN` args become `<main>_<arg>` ports, the return becomes `<main>_return_output` |
| `static` registers, `#pragma FEEDBACK`, `DECL_FEEDBACK_WIRE` | `Reg[T]` (same blocking read-after-write semantics the CPU FSM relies on), `Feedback[T]` |
| Global wires between MAINs, cross-device dataflow MAINs (`video_dataflow` etc.) | `Wire[T]`, `module.wire` access, compound wires split by leaf across writers |
| `GLOBAL_VALID_READY_PIPELINE_INST` (FFT butterfly, power, fb_pos address) | `make_stream_auto_pipeline` in a wiring `@MAIN` |
| `GLOBAL_PIPELINE_INST_W_VALID_ID` (CPU execute stage) | `AUTO_PIPELINE` (or a plain call) in a wiring `@MAIN` |
| `GLOBAL_STREAM_FIFO` on one clock | `Fifo[T] = global_fifo(n)` at module level, or `make_stream_fifo` in a wiring `@MAIN` |
| `GLOBAL_FUNC_INST` | `Inst[f]` at module level |
| `FIFO_FWFT` (VGA reads, scaler line FIFO) | `make_fifo` / `make_stream_fifo` |
| `DECL_STREAM_RAM_DP_W_R_1` (FFT RAM) | `make_stream_ram` |
| `DECL_RAM_TP_R_R_W_1` (register file), `DECL_4BYTE_RAM_SP_RF_1` (DMEM), IMEM ROM | `make_ram` with `ports=("r", "r", "w")`, `byte_write_enables=True`, `init=` |
| `FUNC_LATENCY` ROM (FFT omega table) | `make_ram(init=...)`, and the table can be computed in Python |
| `stream(T)`, `ndarray(2, pixel_t)` video | `make_stream_t`, `make_ndarray_fragment_t` (field `.frag`, not `.data`) |
| `axis8_to_axis32`, `axis32_to_axis8`, `axis_packet_to_type`, length limiter | `make_dwidth_widen`/`_narrow`, `make_axis_to_type` (limiter built in) |
| `type_byte_serializer`, `T_to_bytes`/`bytes_to_T` | `make_serializer`, `make_type_to_bytes`/`make_type_from_bytes` |
| `vga_timing.h`, VGA PMOD wires | `make_vga_timing`, `board.arty.vga_pmod_ja_jb` |
| `cordic.h` | `dsp/cordic.py` |
| `printf` in hardware | `sim_print` |
| `__vhdl__` | `vhdl()` with `@sim_model` |
| `#ifdef` device selection | `param()` and module-level conditional `import` |

What follows is what does not map.

## 1. Python software on the CPU

**Size XL. Not required.**

All StreamSoC software is C: `main.c`, the per-device `software/device.h` helpers,
`bootstrap.S`, `link.ld`, and a `riscv32-unknown-elf-gcc -march=rv32i -fpack-struct=1`
Makefile. Running Python on the CPU instead, for example MicroPython, needs much more than
a Pypeline feature:

- **Memory.** MicroPython's own description gives 256 KiB of code space and 16 KiB of
  RAM as the floor ([micropython.org](https://micropython.org/),
  [FAQ](https://github.com/micropython/micropython/wiki/FAQ)). StreamSoC has a 64 KiB
  instruction ROM and 32 KiB of data RAM, both block RAM. That means several times more
  block RAM, or a CPU that can fetch instructions from DDR3 through the shared bus, which
  is gap 2 plus CPU changes. Both "runtime loading of CPU memory" and "larger off-chip
  memory" are already on the wiki's future-work list.
- **The CPU.** The core is a multi-cycle rv32i at 62.5 MHz with no M or C extension.
  MicroPython's RISC-V work targets RV32IMC, rv32i code is larger, and an interpreter on a
  slow multi-cycle core may not keep up with the drawing loop in `main.c` (about 1,500 GPU
  rectangle commands per audio buffer). Adding M, and maybe C, to the core is likely part
  of this.
- **A MicroPython port** for this SoC: startup code, linker script, HAL glue, and a console.
  StreamSoC has no UART, so either a UART device gets added or scripts are frozen into the
  firmware with no REPL.
- **Register access from Python.** MicroPython's `uctypes` can lay a struct over an address.
  The layout descriptions can be generated from the Pypeline types with the same leaf walk
  that `src/pypeline_host.py` already uses (see gap 9), so this part is small.

Recommendation: keep C firmware for the first Pypeline StreamSoC (gap 9 makes that work)
and treat MicroPython as a later project. It is mostly a CPU and memory-system project, not
an HDL one.

## 2. Shared resource bus and AXI memory-mapped library

**Size L to XL. Required.**

The DDR3 memory is shared by six hosts through PipelineC's shared resource bus: the CPU,
the camera frame-buffer writer (`fb_pos_main`), the GPU (`gpu_main`), the power-spectrum
writer (`power_to_ddr_connect`), the Ethernet audio writer, and a high-priority VGA read
port. Pypeline has none of this; it has AXI-Stream only. The C code to replace is about
4,500 lines: `include/shared_resource_bus.h` (1,534), `shared_resource_bus_decl.h`
(1,219, mostly repetition), `multi_host_clk_shared_resource_bus_decl.h`,
`include/axi/axi_shared_bus.h` (1,149) and `include/axi/axi.h` (369). Pieces needed:

- **Bus types.** The generic five-channel bus (write request, write data, write response,
  read request, read data; each data, id, valid, ready) built from user payload types, and
  the AXI4 memory-mapped payload types (`axi_write_req_t` ... `axi_read_data_t`,
  `axi32_host_to_dev_t`). Struct factories cover this well.
- **The arbiter.** `dev_arb_pipelined`, the multiple-in-flight round-robin arbiter from M
  hosts to N device ports, with id tagging and response routing by id.
- **Host-side helpers.** `write_start_logic`, `read_start_logic` and the finish halves:
  the small FSMs a host calls each cycle to issue one transfer.
- **Device adapters.** `axi_shared_bus_dev_ctrl_pipelined` (bus to the MIG's AXI port),
  `rd_pri_port_arb` (the VGA read-priority 2:1 arbiter), and `DECL_AXI_SHARED_BUS_CSR_DEV`
  (an AXI-Lite register device, used by the buttons).
- **Data movers.** `u32_stream_to_axi_writes` and `axi_reads_to_u32_stream`: stream to
  DDR3 writes driven by descriptors, which carry the audio and power data.
- **Descriptor helpers** for software: `axi_descriptor_t` and the `mm_axi_desc_*` macros.

Two language points make this harder than a straight port:

- **Several writers of one host port (`INST_ARRAY`).** Four different MAINs write
  `host_to_dev(axi_xil_mem, cpu)`. C resolves that with `#pragma INST_ARRAY`, which gives
  each writer its own element of `..._host_to_dev_wires_on_host_clk[4]`. Pypeline requires
  exactly one writer instance per wire leaf. Writers may split a compound wire by
  *constant* index, so today each host has to name its own port number
  (`axi_xil_mem.host_to_dev[2]` inside the GPU), and the bus has to be told the count. The
  translation guide maps `INST_ARRAY` to "factory function + Python list/loop"
  ([pipelinec_to_pypeline.md](pipelinec_to_pypeline.md#11-synthesis-pragmas)), which only
  works when every host is a distinct function that knows its index. Automatic port
  allocation is part of gap 3.
- **A bus is a bundle of global wires plus an arbiter MAIN.** A library factory cannot
  declare those (gap 3), so every bus instance needs a hand-written wiring module.

A single-clock version of the bus can be built and tested before the multi-clock work
lands.

## 3. Generating module-level hardware from Python code

**Size M, compiler work. Not strictly required, but needed for reusable libraries.**

This is the Pypeline counterpart of the C macros that declare MAINs, global wires and FIFOs:
`GLOBAL_*_INST`, `GLOBAL_STREAM_FIFO`, `SHARED_BUS_DECL`, `SHARED_BUS_ARB_PIPELINED`,
`DECL_INPUT` inside device headers. Part of it is done:

- **`@MAIN`s made by code work.** `MAIN(fn, name=...)` makes one from a factory, a loop or
  generated source ([MAINs made in code](pypeline_guide.md#mains-made-in-code-mainfn-name)).
  A made `@MAIN` uses the wires of its function's own module and of the modules that
  module imports, so a factory in a library cannot reach the wires of the design that
  calls it.
- **Global instances and FIFOs exist** as module-level declarations: `Inst[f]`
  ([global instances](pypeline_guide.md#instf--global-instances)) replaces
  `GLOBAL_FUNC_INST`, and `Fifo[T]` ([global FIFOs](pypeline_guide.md#fifot--global-fifos))
  replaces `GLOBAL_STREAM_FIFO`, on one clock or across two.

Still missing:

- **Wires, ports, instances and FIFOs declared by library code.** Global wires are found by
  scanning the source AST, only among the direct children of the module body. A factory
  cannot declare a `Wire[T]`, `Input[T]`, `Output[T]`, `Inst[f]` or `Fifo[T]`, and neither
  can a module-level `if` or loop (see gap 11 for the silent failure this causes). The
  guide's Limitations table lists "Global FIFOs and instances made by library code".
- **No instance arrays.** There is no way to say "each instance that writes this wire gets
  its own element of this array", which is what `INST_ARRAY` does for the shared bus
  (gap 2).

Today's workaround is to write out each bus's wires (or `Inst[f]` declarations) in the
design module, with made `@MAIN`s for the repeated parts. That is workable for one SoC but
makes the bus and the memory map partly copy-paste code.

What closing it probably looks like: wires, ports, FIFOs and instances that register
themselves by value when constructed (for example `bus = make_shared_bus(...)` returning
an object that owns its wires and arbiter MAIN), names derived from the construction site
so they stay a pure function of the source, and a per-instance port allocation for
multi-writer wires.

## 4. RISC-V CPU, memory map and firmware memories

**Size L. Required.**

There is no RISC-V work in Pypeline yet. The C to port is about 2,400 lines:
`include/risc-v/risc-v.h` (decode, rv32i execute, optional M extension, write-back and next
PC, 956 lines), `fsm_riscv_decl.h` (the multi-cycle FSM core, 357), `mem_decl.h` (IMEM,
DMEM and the MMIO-aware data memory wrapper with byte lanes, 580), `risc-v/mem_map.h` (187),
`reg_file.h` (50), plus `my_mem_map_module` in `cpu/hardware/devices.c` (about 280).

No language feature is missing for the core itself. The FSM's same-cycle state changes
work because `Reg[T]` reads see earlier writes in the same call, the register file and
memories are `make_ram` shapes, and decode is bit slices and `if`/`elif`. Some things are
easier than in C: the IMEM and DMEM contents can be read from gcc's `.bin` output by plain
Python at elaboration (`make_ram(init=...)`), which replaces `bin2vhdl.py` and the
`*_mem_init.h` headers, and the `MM_ENTRIES` table becomes a Python list that loops unroll
at compile time.

Work and risk:

- Porting and testing decode/execute against real gcc programs (a cocotb or Verilator
  harness running compiled firmware).
- Elaboration and synthesis time of a CPU-sized FSM have not been tried in Pypeline.
- The C core marks `printf` debugging throughout; `sim_print` covers it, though `%X` becomes
  `hex()`.

[cpu_planning.md](cpu_planning.md) plans this work in milestones, starting from the
single-cycle core rather than StreamSoC's FSM core.

## 5. Dataflow device libraries

**Size M each, L in total. Required.**

Library code the SoC's devices use that has no Pypeline version. The language supports all
of it; this is porting work.

| Device | C to port | Notes |
|---|---|---|
| Ethernet frame RX/TX | `include/net/eth_32.c` (410 lines), MAC filter, `axis32_max_len_limiter` | Width converters and struct-from-AXIS already exist |
| Audio over Ethernet | `include/i2s/i2s_32b.h` (91), `eth_to_i2s/hardware/device.c` | Sample types and the deserializer glue |
| FFT engine | `fft/hardware/device.c` (521: FSM, RAM 2:1 packing, butterfly), the shared parts of `fft/software/fft.h` | Omega ROM can be computed in Python; `rev()` needs a bit-reverse helper (gap 11) |
| Power spectrum | `power/software/power.h` (`fixed_sqrt`, 111) | `limited_while` loops become `for` loops with an exit flag; `dsp/magnitude.py` computes I²+Q² but has no square root |
| Camera control | `include/sccb/sccb.h` (571), `sccb/hardware/device.c` | I²C-like FSM; SIO_D needs separate `_o`/`_i`/`_t` ports (gap 10) |
| Camera video | `dvp/hardware/dvp.h` decoder (113) | Small |
| Video pipeline | `frame_decoder`, `crop2d`, `scale2d`, `fb_pos` (about 330) | Straightforward; the writes into DDR3 need gap 2 |
| GPU | `gpu/hardware/device.c` (90) | Rectangle FSM; DDR3 writes need gap 2 |
| VGA from DDR3 | `vga/hardware/device.c` reader (205) | Uses the priority read port from gap 2 |
| LEDs, buttons, switches, cycle counter | a few lines each | Trivial; buttons need the AXI-Lite device from gap 2 |

## 6. Functions shared by hardware and software

**Size M to L. Not required.**

StreamSoC compiles some C both as hardware and as CPU software. `fft/software/fft.h` holds
`fft_2pt_w_omega_lut`, `next_iters`, `rev` and the fixed-point helpers; the CPU version
`compute_fft_cc` and the hardware FSM run the same iterator code, and `power.h`'s
`sample_power` is the same. The memory-map header is also shared (gap 9). Pypeline
hardware is Python, so a C program cannot call it. Options:

- Duplicate the functions in C by hand. Cheapest, and drift is caught only by testing.
- Emit C from Pypeline functions. The elaborated function bodies are typed and loop-free,
  so a C printer for plain combinational functions is plausible, but it is new tooling with
  its own testing burden.
- Run them as Python on the CPU, which needs gap 1, plus a small runtime for the
  `uintN_t` types on MicroPython.

## 7. Simulating a whole SoC

**Size M. Needed for verification.**

- **Models for vendor IP.** The MIG DDR3 controller and the Xilinx TEMAC sit outside the
  generated VHDL. A testbench needs `@sim_model` versions: an AXI memory model and an
  Ethernet frame source.
- **Speed.** The native simulator's own benchmark is a small VGA design: a 1280x720 frame
  (about 1.2 million cycles) takes about 3 s in raw mode and 15 s in strict mode
  ([pypeline_sim_DESIGN.md](pypeline_sim_DESIGN.md)). StreamSoC has dozens of MAINs and a
  CPU that needs millions of cycles just for camera setup (each `wait_ms(3)` is 187,500
  cycles), so native simulation will probably be far slower than that; this has not been
  measured. The generated-VHDL flows (`--verilator`, `--cxxrtl`) exist and are the likely
  route, but their conversion to Verilog or C++ drops `sim_print` output and
  `sim_finish()` ([Other HDL simulators](README.md#other-hdl-simulators)), and
  `--verilator --run all` crashes ([#406](https://github.com/JulianKemmerer/PipelineC/issues/406)). CPU output
  there needs a C++ driver that prints the console device's ports.

## 8. Register map builder

**Size S to M. Required.**

The CPU's memory-mapped registers are one `mm_regs_t` struct assembled from per-device
fragments (`#include "../i2s/i2s_mm_regs.h"` inside the struct), and devices hook into it
with macros: `MM_STREAM`, `HANDSHAKE_MM_READ`/`_WRITE`, `STRUCT_MM_ENTRY_NEW` (a
byte-addressed read and byte-enabled write of the whole struct), and
`MM_SHARED_AXI_TO_FROM_HOST`.

Pypeline has the pieces: `struct(NamedTuple(name, fields))` builds a struct from a field list
collected from device modules (the library already does this in `ram.py` and
`interface.py`), `make_type_to_bytes`/`make_type_from_bytes` give the byte view, and
variable array indexing does the byte offsets. Missing is the library that ties them
together. One limitation shapes it: a hardware body cannot pick a struct field by a Python
string. `getattr(regs, "gpu_cmd")` and `setattr(...)` on a hardware value are rejected with
"only supported with compile-time constant arguments" (rechecked at `b88f7600`). So the
generic handshake helpers must either generate source text, as `interface_func.py` and
`stream.py` already do with `exec`, or each device writes its few lines out by hand. The
CPU plan avoids the question by giving each device its own structs, mapped whole through
bytes, instead of one `mm_regs_t` of every device.

## 9. Exporting the hardware interface to C software

**Size S. Required while firmware is C.**

In C StreamSoC, `cpu/mem_map.h` and each device's `mem_map.h` are compiled by both
PipelineC and gcc, so the register layout, addresses and constants (`FRAME_WIDTH`, `NFFT`,
`MM_ENTRIES`, `draw_rect_t`, `axi_descriptor_t` ...) cannot drift. With Pypeline hardware
there is no shared source, so the C side has to be generated:

- **A C header** with packed struct typedefs, constants and register addresses.
  `host_export` and `src/pypeline_host.py` already walk exactly these types, but they write a
  Python module only. The old C front end generated C headers. Adding C output is a fourth
  consumer of the same leaf walk. Pypeline's byte layout (packed, each leaf rounded up to
  whole bytes) matches gcc's `-fpack-struct=1` for byte-multiple fields, which is all
  StreamSoC uses. Packing has a cost, though: GCC 12.1 (`-march=rv32i`) writes a `uint32_t`
  field of a packed struct through a pointer as four byte reads and four byte writes, while
  a constant address keeps one `sw`. A generated header is better off with naturally aligned
  structs, which need no packing (see
  [Struct layout shared with C](cpu_planning.md#struct-layout-shared-with-c)).
- **Linker script values.** `link.ld` repeats the IMEM and DMEM sizes by hand ("TODO how to
  share variables?"). Generating them from the same Python constants fixes that too.
- **Running the software build.** Module-level Python can run the compiler before the ROM
  contents are read. A synthesis `@initial` hook runs too late for this, since it runs
  after the first import and the ROM is built during import (still true at `b88f7600`).
  The CPU plan builds firmware during import, once per run, through a proposed run-once
  value ([Firmware build and RAM contents](cpu_planning.md#firmware-build-and-ram-contents)).

## 10. Board support and vendor IP

**Size S. Partly required.**

- **No general Arty board module.** `include/board/arty.h` lets each device pick pin
  directions with `#define JA_0_OUT` and friends, including `_o`/`_i`/`_t` triples for the
  camera's bidirectional SIO_D pin. Pypeline has `board.arty.part35t`/`part100t`,
  `board.arty.clocks` (the 100 MHz pin as a named clock) and fixed modules for two VGA PMOD
  pairs, plus `examples/pypeline/arty` (an MMCM in `board.vhd`, with the PLL lock made
  into a reset). A device can declare its own `Input`/`Output` ports with the board pin
  names, but that ties the device to specific pins.
- **Ports cannot be chosen by condition.** A port declared inside a module-level `if` is
  silently dropped (gap 11), so pin selection needs one module per choice, imported
  conditionally.
- **No `FUNC_BLACKBOX`.** The TEMAC Ethernet IP is a `__vhdl__` component in C, marked
  `FUNC_BLACKBOX` so timing synthesis replaces it with IO registers. Pypeline has no such
  marker, and what its timing synthesis does with an unresolved vendor component inside
  `vhdl()` has not been tested. The workaround is the one the DDR3 already uses: instantiate
  the IP in the board's `board.vhd` and connect it through `@MAIN` ports.

## 11. Small language gaps and bugs

**Size XS each.** Found while checking the ports above, and rechecked at `b88f7600`. The
two bugs are [#404](https://github.com/JulianKemmerer/PipelineC/issues/404) and [#405](https://github.com/JulianKemmerer/PipelineC/issues/405), in the
[issues inventory](issues_inventory.md) with reproducers
(`conditional_global_decl_known_issue` and `reversed_bit_slice_known_issue`).

| Item | Status | Workaround |
|---|---|---|
| `Output[T]` (or any global wire) declared inside a module-level `if` | **Bug ([#404](https://github.com/JulianKemmerer/PipelineC/issues/404)):** the build succeeds, no port is created, and the MAIN's write to it becomes an unused local. A `Wire[T]` read by another MAIN stops the build with "Unknown name" instead. Native simulation treats both as wires | Declare ports unconditionally, or in a conditionally imported module |
| Reversed bit slice `x[0:7]`, which FFT `rev()` uses in C as `v(0, 31)` | **Bug ([#405](https://github.com/JulianKemmerer/PipelineC/issues/405)):** hardware silently emits `x(7 downto 0)`, not reversed; native simulation raises `ValueError: negative shift count` | Split to bits with `uint_to_array_le`, reverse them in a loop, rejoin with `array_to_uint_le` (native simulation and GHDL agree). A `bit_reverse()` helper would be better |
| `limited_while(cond, i, N)` loops with a hardware condition (`fixed_sqrt`) | Not supported, as documented | `for i in range(N):` with an exit flag |
| Selecting a struct field by name string in hardware | Not supported (`getattr` rejected) | Generate source text, or write fields out (gap 8) |

## Suggested order of work

1. Gap 9 (C header export) and gap 11 fixes: small, and they unblock C firmware.
2. Gap 4 (CPU) with BRAM-only memory and register-only MMIO, plus gap 8: the SoC
   "TEMPLATE" directory (CPU, clock, LEDs) running C firmware. [cpu_planning.md](cpu_planning.md)
   breaks this step into milestones.
3. Gap 2 on one clock, written with hand-made wiring. Writing it shows exactly which parts
   of gap 3 matter.
4. Gap 3, scoped by what step 3 needed.
5. Gap 5 devices one at a time, then gap 7 for whole-SoC testing.
6. Gaps 6 and 1 last, as their own projects.
