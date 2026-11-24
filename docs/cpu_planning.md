# Pypeline CPU Planning

This is the plan for a RISC-V CPU and SoC library written in Pypeline
([pypeline_guide.md](pypeline_guide.md)). It covers the scope, what Pypeline provides
today and what it lacks, the design decisions that hold across the work, and the
milestones in order. Each milestone names the issues that must be fixed before it
starts. Keep the plan current: when a milestone lands, change its section to say what
was built and where, and remove answered questions from
[Open questions](#open-questions). The wider StreamSoC port this work feeds into is
surveyed in [pypeline_stream_soc_gaps.md](pypeline_stream_soc_gaps.md).

Statements about current Pypeline behavior say how they were checked. Unless a row says
otherwise, the checks ran against commit `b88f7600`. They used small designs built with
`pypelinec --comb --no_synth`, plus `--sim`, `--sim --cocotb --ghdl` or
`pypeline_sim_debug.py` (the native-versus-GHDL cycle diff) where a row says so, and
the GCC toolchain described under
[What Pypeline provides today](#what-pypeline-provides-today).

## Table of Contents

- [Goal and scope](#goal-and-scope)
- [What Pypeline provides today](#what-pypeline-provides-today)
- [Gaps and how the plan handles them](#gaps-and-how-the-plan-handles-them)
- [Architecture](#architecture)
  - [Layers](#layers)
  - [Address map](#address-map)
  - [Where the code goes](#where-the-code-goes)
- [Milestones](#milestones)
- [M0: Audit](#m0-audit)
- [M1: Single-cycle RV32I core, firmware build and ISA tests](#m1-single-cycle-rv32i-core-firmware-build-and-isa-tests)
  - [Core](#core)
  - [Simulation-control device](#simulation-control-device)
  - [Firmware build and RAM contents](#firmware-build-and-ram-contents)
  - [ISA tests](#isa-tests)
  - [M1 exit criteria](#m1-exit-criteria)
- [M2: Machine-mode traps and CSRs](#m2-machine-mode-traps-and-csrs)
- [M3: Memory-mapped control and status registers](#m3-memory-mapped-control-and-status-registers)
  - [Memory map](#memory-map)
  - [Struct layout shared with C](#struct-layout-shared-with-c)
  - [C header](#c-header)
  - [M3 exit criteria](#m3-exit-criteria)
- [M4: Console and UART](#m4-console-and-uart)
- [M5: Table-driven decoder and ISA extensions](#m5-table-driven-decoder-and-isa-extensions)
- [M6: Hardware bring-up](#m6-hardware-bring-up)
- [Deferred](#deferred)
- [Open questions](#open-questions)

## Goal and scope

The goal is a CPU generator and SoC bring-up library in Pypeline. The core, the memory
map, the firmware build, the C header the firmware compiles against, the tests and the
board top levels all live in one Python flow. That flow replaces what the C front end's
CPUs needed:

- the preprocessor-macro cores in `include/risc-v/`;
- `bin2vhdl.py` and the generated `*_mem_init.h` files;
- a `link.ld` and a `mem_map.h` kept in step by hand (both carry
  "TODO how to share variables?");
- a separate `make hex` run before every hardware build.

The first milestones build a small but complete system. Their abstractions are chosen to
extend later to multi-cycle and pipelined cores, bus fabrics, and a port of StreamSoC
(`examples/stream_soc/`).

Principles:

- **Library first.** The core, decoder, memory map and firmware build are library code in
  `include/pypeline/`: Pypeline hardware plus host Python. A compiler change enters the
  plan only when a milestone's design needs it and no clean library workaround exists. It
  then goes through the [issues inventory](issues_inventory.md) like any other change.
  Compile-time `getattr` on hardware structs is not needed
  ([Gaps](#gaps-and-how-the-plan-handles-them) says why).
- **Fix blocking bugs first.** Where a known bug sits on a milestone's path, the
  milestone lists it under "Before it starts", and the bug is fixed before the
  milestone begins rather than worked around in library code.
- **One firmware binary everywhere.** The same ELF runs in native simulation, in GHDL and
  on each board. Simulation hooks sit behind MMIO addresses that the hardware implements
  too.
- **Standard tools.** The RISC-V GCC toolchain and the official
  [riscv-tests](https://github.com/riscv-software-src/riscv-tests) suite. No custom
  assembler or ISA model.
- **Each milestone passes its own tests and updates its docs** before the next one starts.
  A later milestone can then be deferred without reworking an earlier one.

Constraints until a milestone lifts them:

| Topic | Choice |
|---|---|
| Clocks | One clock domain |
| Execution | Single-cycle: one instruction per clock. Multi-cycle and pipelined cores, the legacy FSM core among them, are [deferred](#deferred) |
| Memory | On-chip, separate instruction and data memories (Harvard), combinational read |
| ISA | RV32I, little-endian, machine mode only. M1 has no CSRs or traps: FENCE is a no-op, and ECALL and EBREAK halt. [M2](#m2-machine-mode-traps-and-csrs) adds the machine-mode CSRs and traps that the riscv-tests `p` environment uses. [M5](#m5-table-driven-decoder-and-isa-extensions) adds extensions. No interrupts |
| MMIO structs | Fields of 1, 2, 4 or 8 bytes at naturally aligned offsets ([Struct layout shared with C](#struct-layout-shared-with-c)) |
| Targets | Native Python simulation and cocotb + GHDL. Arty A7 (Artix-7, Vivado) is the first board. pico-ice (iCE40 UP5K, GHDL + Yosys + nextpnr) runs a small blink firmware only ([M6](#m6-hardware-bring-up)) |

## What Pypeline provides today

| CPU need | Pypeline today | Checked by |
|---|---|---|
| PC and control state | `Reg[T]`: blocking read-after-write within a cycle | guide |
| Register file with two combinational reads and one write | `make_ram(uint32_t, 32, ports=("r", "r", "w"), read_latency=0)`. Write-back is computed after the reads, so the write port is driven through a [`Feedback[T]`](pypeline_guide.md#feedback-wires-feedbackt) of `ram.p2_in_t` | A design reads `x[k]` and `x[k-1]` each cycle, where `x[k-1]` was written the cycle before. Native simulation and cocotb + GHDL printed the same values |
| IMEM ROM, DMEM with byte lanes | `make_ram(..., ports=("r",), init=...)`; `make_ram(..., ports=("rw",), byte_write_enables=True)`, whose `wr_en` is then a `uint1_t[4]` | guide ([RAMs](pypeline_guide.md#rams-make_ram--make_stream_ram)) |
| All three memories in one `@MAIN` | An IMEM ROM, a byte-enable DMEM and the register file, each with its own contents, called from one `@MAIN` | `pypeline_sim_debug.py`: native simulation and GHDL printed the same values on every cycle except the `sim_finish()` cycle ([#361](https://github.com/JulianKemmerer/PipelineC/issues/361)) |
| RAM contents from Python | `init=` takes a list or a dict. `make_ram` checks and converts it when called. The contents are part of the RAM's identity: different contents make a different entity | `include/pypeline/ram.py` |
| Resets | `make_reset()`, `make_clock(..., reset=)`, and `reset_registers="all"` or `Reg[T, RESET]`. Through a reset, a RAM keeps its contents, its in-flight requests are cancelled, and the write at the reset edge does not happen | guide ([Resets](pypeline_guide.md#resets)) |
| Per-build choices (firmware, memory sizes, tracing) | `param()` and `-D` | guide ([Build Parameters](pypeline_guide.md#build-parameters-param-and--d)) |
| `@MAIN`s made by factories | `MAIN(fn, name=)` | guide ([MAINs made in code](pypeline_guide.md#mains-made-in-code-mainfn-name)) |
| Shared instances and FIFOs | `Inst[f]`, `Fifo[T]`, declared at module level | guide ([`Inst[f]`](pypeline_guide.md#instf--global-instances)) |
| Byte views of structs | `make_type_to_bytes`/`make_type_from_bytes`, `byte_length`, arrays indexed by a hardware value | guide |
| Structs built from field lists | `struct(NamedTuple(name, fields))` | `ram.py`, `interface.py` |
| Type export for host software | `host_export`. `src/pypeline_host.py`'s `generate()` is pure and can run during import | source |
| Simulation control from hardware | `sim_print`, `sim_assert`, `sim_finish`, in both native simulation and generated VHDL | guide |
| Testbench processes in Python | Simulation-only `@MAIN`s over `@sim_input`/`@sim_output` | guide |
| Board starting points | `examples/pypeline/pico_ice`: an icepll PLL in `top.sv`, and `pll_locked` through two registers into the clock's reset. `examples/pypeline/arty`: an MMCM in `board.vhd`, with the same reset pattern. Board modules `board.arty.clocks`, `part35t`, `part100t` and the VGA PMOD modules | examples |
| Waveforms | `--wave` | guide |

**Toolchain.** riscv-gnu-toolchain configured with `--with-arch=rv32i --with-abi=ilp32`
builds an RV32I libgcc, which rv32i firmware needs: `*`, `/` and `%` call `__mulsi3`,
`__divsi3` and their relatives. GCC 12.1 configured that way links them with
`-nostdlib ... -lgcc`. The toolchain's default install prefix, `/opt/riscv`, is often not
on `PATH`; the legacy Makefiles say `export PATH=$PATH:/opt/riscv/bin`.

## Gaps and how the plan handles them

| Gap | Status | Plan |
|---|---|---|
| Preparing RAM contents | Module-level Python runs on every design import | M1 compiles firmware in a private temporary directory and passes its words to the RAM factories ([Firmware build and RAM contents](#firmware-build-and-ram-contents)) |
| Selecting a hardware struct field by string | In a hardware body, `getattr(regs, "led")` and `setattr(o, "led", v)` both fail: "only supported with compile-time constant arguments" | Not needed: the memory map maps each device's structs whole, through bytes. Add compile-time `getattr` only when a design needs it |
| C header export | `pypeline_host.py` writes a Python module only | [M3](#m3-memory-mapped-control-and-status-registers) adds a C header generator next to `generate()`. It runs during import, because gcc needs the header before the RAM contents exist |
| Packed C structs for MMIO | Pypeline's byte layout matches `-fpack-struct=1`, but packing changes how GCC accesses fields. With GCC 12.1 (`-march=rv32i -O2`, with or without `-mstrict-align`), a `uint32_t` field write through a pointer to a packed struct becomes four `lbu` + `sb` pairs. A write through a constant address stays one `sw`. A register with side effects, such as a UART TX, would see four byte writes and four reads | Mapped structs keep natural alignment, so the plain C layout equals Pypeline's. The header uses no packing and checks every offset with `_Static_assert` ([Struct layout shared with C](#struct-layout-shared-with-c)) |
| Struct constants from a Python table | A `for` loop over a module-level list of `(mask, match, ctrl_t(...))` rows fails at `c = ctrl` with "Cannot emit non-int Python value as hardware". It is one of the forms of [#402](https://github.com/JulianKemmerer/PipelineC/issues/402), whose inventory entry and reproducer include it. A typed local in the loop, `k: ctrl_t = ctrl`, elaborates | Fix #402 before [M5](#m5-table-driven-decoder-and-isa-extensions) |
| A wire or port declared inside a module-level `if` | Bug, [#404](https://github.com/JulianKemmerer/PipelineC/issues/404): an `Output[T]` gets no port, and the `@MAIN`'s write to it is dropped with no error. A `Wire[T]` read by another `@MAIN` stops the build with "Unknown name". Native simulation treats both as wires | Fix before [M6](#m6-hardware-bring-up), whose board tops choose pins. Until then, choose variants by conditional `import` |
| Reversed bit slice `x[0:7]` | Bug, [#405](https://github.com/JulianKemmerer/PipelineC/issues/405): built as `x[7:0]`; native simulation raises | The CPU needs no reversed slice |
| Bit index from a hardware value, `x[i]` | Not supported ([#362](https://github.com/JulianKemmerer/PipelineC/issues/362)) | Load and store byte lanes index a `uint_to_array_le` array instead |
| `sim_print` on the `sim_finish()` cycle | Missing from VHDL simulation output ([#361](https://github.com/JulianKemmerer/PipelineC/issues/361)); the memory checks above show it too | Print the result, then finish one cycle later |
| `sim_print` of a value of 2³¹ or more | Overflows in GHDL ([#360](https://github.com/JulianKemmerer/PipelineC/issues/360)). MMIO addresses start at `0x8000_0000` | Print addresses and data with `hex()`, which does not overflow |
| Native-simulation state behind a stateless caller | Two stateful instances that only a stateless caller tells apart share one native-simulation state ([#382](https://github.com/JulianKemmerer/PipelineC/issues/382)). Two `make_stream_fifo` FIFOs in one `@MAIN` hit it. The three memories in one `@MAIN` (above) do not | M4's console has a TX and an RX FIFO: fix #382 before [M4](#m4-console-and-uart) |
| Memories on iCE40 | The UP5K has no distributed RAM: its block RAMs (EBR) and SPRAM read on a clock edge. It has 5,280 LUT4s and 5,280 flip-flops. Combinational-read memories therefore become flip-flops or logic: a 2 KiB DMEM alone is 16,384 bits. A constant IMEM is a ROM that synthesis reduces to logic, so a short program whose memory is mostly zeros may fit | Arty is the first board. [M6](#m6-hardware-bring-up) tries pico-ice with a blink firmware and the smallest memories that hold it. A registered-read core is [deferred](#deferred) |
| Wires, ports, instances and FIFOs made by library code | Not supported. A `@MAIN` that a library factory makes cannot reach the design's wires | The core factory takes its MMIO devices as hardware-function arguments, and the design module owns the pins |
| Native simulation speed | Not measured for a CPU | M1 measures cycles per second on the ISA tests, which are short programs |
| Verilator and CXXRTL simulation | The conversion they run drops `sim_print` and `sim_finish()` ([Other HDL simulators](README.md#other-hdl-simulators)), and `--verilator --run all` crashes ([#406](https://github.com/JulianKemmerer/PipelineC/issues/406)) | Not used by these milestones: tests run in native simulation and cocotb + GHDL, and the console is an MMIO device ([M4](#m4-console-and-uart)) |

## Architecture

### Layers

1. **The core** executes one instruction per clock. It talks to memory through the
   **ISA-native port**:
   - a 32-bit address;
   - 32-bit write data;
   - four byte write enables;
   - a read enable;
   - combinational read data.

   Every memory and device sees this port.
2. **Address decode** splits the port into windows. Instruction fetch has its own IMEM
   port. Data accesses go to DMEM or to the MMIO window.
3. **Devices** in the MMIO window each own their registers: a hardware function plus the
   structs it maps. The [memory map](#memory-map) places devices and builds the decode.
4. **Later layers**, outside these milestones:
   - AXI-Lite, Pypeline's shared resource bus and multi-cycle devices attach as windows,
     through adapters on the native port.
   - A device that cannot answer within the cycle adds a stall to its window; the core's
     port keeps its shape.
   - Another ISA reuses the devices through an adapter from its own native port.

### Address map

The default comes from the legacy cores, whose `include/risc-v/mem_decl.h` decodes single
address bits:

| Window | Base | Selected by | Holds |
|---|---|---|---|
| IMEM | `0x0000_0000` | instruction fetch only | `.text` |
| DMEM | `0x4000_0000` | address bit 30 | `.rodata`, `.data`, `.bss`, stack |
| MMIO | `0x8000_0000` | address bit 31 | devices, starting with M1's simulation-control device |

- Sizes are Python constants (parameters). They set both the `make_ram` sizes and the
  generated linker script.
- `.rodata` lives in DMEM because, in a Harvard design, loads cannot read IMEM. GCC puts
  string literals, `const` tables and switch jump tables there and reads them with loads.
  The legacy `link.ld` already places `.rodata` in its RAM section.
- A data access outside DMEM and MMIO, or a misaligned one, sets `mem_out_of_range`, as
  the legacy core does. From M2, it traps instead.

### Where the code goes

- `include/pypeline/riscv/`: everything RISC-V:
  - the core factory, the decoders and the extension plugins;
  - the firmware build: the GCC driver, and the generators of the linker script,
    `crt0.S` and the firmware Makefile;
  - riscv-tests, copied into the repository: `isa/rv32ui/`, `isa/rv32um/`,
    `isa/macros/scalar/test_macros.h`, the `p` environment and `encoding.h` from
    riscv-test-env, both BSD licenses, and the upstream commits they came from;
  - the replacement test environment from M1.
- `include/pypeline/cpu/`: the parts no ISA owns:
  - the ELF loader;
  - the simulation-control device;
  - from M3, `cpu/mmio`: the memory map builder and its register and console devices.
- `include/pypeline/uart/`, from M4: the UART MAC. It is not CPU-specific, so it sits
  beside `vga/` and `axi/`.
- `examples/pypeline/riscv/`: top-level designs and demo firmware; from M6, the board
  wrappers and Makefiles.
- Tests: fixtures in `src/tests/pypeline_tests/inst/`, registered as
  [Adding a test](pypeline_TESTS.md#adding-a-test) describes. `Test.requires=` is a
  `shutil.which` check today, which misses a toolchain that is off `PATH`. M1 lets a
  test ask the firmware helper's toolchain lookup instead. Without a toolchain the test
  reports a skip, not a pass.
- Docs:
  - Library code has no `*_DESIGN.md`. Each user-visible feature gets a guide section
    when it lands.
  - The example gets a README, and the [README](../README.md) feature table gets a row.
  - M3's C header generator extends `src/pypeline_host.py`, so M3 updates
    [One walk, three consumers](pypeline_DESIGN.md#one-walk-three-consumers).

## Milestones

| Milestone | Delivers | Before it starts | Done when |
|---|---|---|---|
| [M0](#m0-audit) | Audit of the legacy CPUs and of Pypeline; decisions; bugs filed | — | The open questions are answered and the bugs found have GitHub issues |
| [M1](#m1-single-cycle-rv32i-core-firmware-build-and-isa-tests) | Single-cycle RV32I core ported from the legacy core; firmware built during import; resets; `rv32ui` with a replacement test environment | Nothing to fix; workarounds for #360, #361 and #362 | `rv32ui` passes in native simulation and GHDL; a C demo builds with no manual step |
| [M2](#m2-machine-mode-traps-and-csrs) | Machine-mode CSRs, ECALL, EBREAK, MRET and exception traps | Nothing known | `rv32ui` passes with the unmodified riscv-tests `p` environment |
| [M3](#m3-memory-mapped-control-and-status-registers) | Memory map with struct registers for LEDs, buttons and a cycle counter; C header export | Nothing known | Firmware reads and writes every field of the mapped structs, checked field by field |
| [M4](#m4-console-and-uart) | Console MMIO device and UART | Fix [#382](https://github.com/JulianKemmerer/PipelineC/issues/382) | "Hello" prints in native simulation and GHDL; an echo test passes |
| [M5](#m5-table-driven-decoder-and-isa-extensions) | Table-driven decoder; extension plugins, starting with M | Fix [#402](https://github.com/JulianKemmerer/PipelineC/issues/402), including its table form | The table decoder matches M1's decoder; `rv32um` passes |
| [M6](#m6-hardware-bring-up) | Arty bring-up, then a pico-ice blink | Fix the dropped conditional declaration, [#404](https://github.com/JulianKemmerer/PipelineC/issues/404) | The same firmware runs in simulation and on Arty; blink runs on pico-ice, or its utilization is recorded |

## M0: Audit

The status tables above record the part of the audit already done. The two bugs that
the [StreamSoC survey](pypeline_stream_soc_gaps.md) found
([#404](https://github.com/JulianKemmerer/PipelineC/issues/404) and
[#405](https://github.com/JulianKemmerer/PipelineC/issues/405)), and a Verilator crash
found while rechecking it ([#406](https://github.com/JulianKemmerer/PipelineC/issues/406)),
are in the [issues inventory](issues_inventory.md) with `known_issues_tests.py`
reproducers. #402's entry and reproducer include the table form.
What remains:

1. **Read the legacy sources.** For each piece, record whether it ports as is, is
   redesigned, or is dropped.

   | Source | What it holds |
   |---|---|
   | `include/risc-v/risc-v.h` | Opcodes, `decode()` (an if/else tree with an optional M extension), `execute()`, `select_reg_wr_data()`, `select_next_pc()`. No FENCE, ECALL, EBREAK or CSRs |
   | `examples/risc-v/risc-v_decl.h` | The single-cycle core: PC, IMEM, decode, a register file through `#pragma FEEDBACK`, execute, DMEM, write-back |
   | `include/risc-v/mem_decl.h`, `include/risc-v/reg_file.h` | IMEM and DMEM wrappers in 0- and 1-cycle forms, address-bit decode, byte lanes, `mem_out_of_range`; the register file |
   | `include/risc-v/mem_map.h` | `STRUCT_MM_ENTRY_NEW` (a struct mapped whole through bytes), `MM_STREAM`, `HANDSHAKE_MM_READ`/`_WRITE` |
   | `examples/risc-v/risc-v.c`, `examples/pico-ice/ice_makefile_pipelinec/risc-v/single_cycle_risc-v_top.c` | Single-cycle tops: the memory-map module, LEDs, debug outputs |
   | `examples/pico-ice/ice_makefile_pipelinec/risc-v/firmware/`, `examples/risc-v/gcc_test/` | Makefile (`make hex`), `link.ld`, `bootstrap.S`, `bin2vhdl.py`, demo programs |
   | `examples/risc-v/cocotb/test_top.py` | The cocotb harness: it stops on `halt` and fails on `unknown_op` or `mem_out_of_range` |
   | `examples/stream_soc/cpu/` | StreamSoC's CPU top, `mem_map.h` and `devices.c` (`my_mem_map_module`), input to M3's design |

   `include/risc-v/fsm_riscv_decl.h`, the multi-cycle FSM core of the pico-ice demo
   `examples/pico-ice/ice_makefile_pipelinec/risc-v/risc-v_top.c`, is not ported in these
   milestones ([Deferred](#deferred)).

   The C idioms map to Pypeline like this:

   | C front end | Pypeline |
   |---|---|
   | `#pragma FEEDBACK` | `Feedback[T]` |
   | `printf` traces | `sim_print` behind a parameter |
   | the `riscv_name` macro instance | a factory call |
   | `*_mem_init.h` | `init=` |

2. **Run spikes outside the repository** before M1 settles its APIs:
   - build one `rv32ui` test with the replacement environment and the generated linker
     script, and load its ELF into IMEM and DMEM images;
   - count how many times a typical build imports the design, and time one firmware
     compile, to measure the cost per design import;
   - list the CSRs and trap causes that riscv-tests' `env/p/riscv_test.h` uses, from its
     source, as input to M2;
   - measure the elaboration time of the ported `decode()`; no CPU-sized function has
     been elaborated yet.
3. **Answer the [open questions](#open-questions).**

M0 is done when this plan records each decision and every bug it finds has a GitHub
issue, an inventory entry and a reproducer.

## M1: Single-cycle RV32I core, firmware build and ISA tests

M1 ports the legacy single-cycle core, adds what the ISA tests
need, and builds the firmware with no manual step.

**Before it starts:** nothing to fix. M1 works around [#361](https://github.com/JulianKemmerer/PipelineC/issues/361)
(finish a cycle after the last print), [#360](https://github.com/JulianKemmerer/PipelineC/issues/360)
(print with `hex()`) and [#362](https://github.com/JulianKemmerer/PipelineC/issues/362)
(byte lanes through an array).

### Core

A factory in `include/pypeline/riscv/` returns the core as a hardware function. It takes:

- the memory sizes;
- the IMEM and DMEM contents;
- the MMIO hardware function, which answers the native port for the MMIO window. M1
  passes the simulation-control device.

The datapath stays split into pure functions around explicit state:

- `decode`;
- immediate generation;
- `execute`;
- load and store alignment;
- the write-back select;
- the next-PC select.

A multi-cycle or pipelined core can then recombine these functions without rewriting
them.

- **PC:** a `Reg[uint32_t]`, reset to the reset vector `0x0000_0000`.
- **IMEM:** a ROM, `make_ram(uint32_t, IMEM_WORDS, ports=("r",), read_latency=0, init=imem)`.
- **Decode:** the legacy `decode()` if/elif tree, plus FENCE as a no-op and ECALL/EBREAK
  as halt. An unknown encoding sets `unknown_op`.
- **Register file:** the two-read, one-write RAM from
  [What Pypeline provides today](#what-pypeline-provides-today), with its write port driven
  through `Feedback`. `x0` reads as zero through a mux and is never written. It
  therefore does not depend on RAM contents, which have no reset.
- **DMEM:** `make_ram(uint32_t, DMEM_WORDS, ports=("rw",), read_latency=0,
  byte_write_enables=True, init=dmem)`. Loads select and sign-extend lanes from a
  `uint_to_array_le` array.
- **Reset:** the core's `@MAIN` uses `reset_registers="all"`. The PC, the status flags and
  the device registers reset; IMEM, DMEM and the register file keep their contents.
  - After a reset during a run, the startup code zeroes `.bss` again, but `.data` keeps
    the values the program last wrote. Only reloading the FPGA restores it.
  - M1 documents this behavior. Restoring `.data` needs a copy from a readable image
    ([Deferred](#deferred)).
- **Halt:** a clock enable around the core's call stops a halted core.
- **Debug outputs:** `pc`, `unknown_op`, `mem_out_of_range`, `halt` and the exit code.
  Per-instruction trace prints sit behind `param("RISCV_TRACE", False)` and print with
  `hex()`.

### Simulation-control device

The device is one register at the MMIO base, `TOHOST`. It follows the `riscv-tests`
convention: writing 1 means pass, and writing `(n << 1) | 1` means test `n` failed. The
startup code writes `(main's return value << 1) | 1`, so a return of 0 passes. A write to
`TOHOST + 4`, the upper half of the `p` environment's 64-bit `tohost`, is accepted and
ignored (used from M2).

On a write, the device:

- prints the result with `sim_print`;
- fails a `sim_assert` on a failure code;
- calls `sim_finish()` one cycle later ([#361](https://github.com/JulianKemmerer/PipelineC/issues/361)).

These are hardware statements, so the same pass/fail check works in native simulation and
in GHDL. On a board, the write sets `halt`.

### Firmware build and RAM contents

Call an ordinary Python helper on each import, before constructing either RAM.
Repeated calls with the same inputs produce identical IMEM and DMEM words. See
[Code that runs during design import](pypeline_guide.md#code-that-runs-during-design-import).

```python
fw = firmware.build(sources=("main.c",), imem=IMEM, dmem=DMEM)  # compile, link, load
core = make_rv32i_core(imem_init=fw.imem_words, dmem_init=fw.dmem_words, mmio=mm)
```

The names are proposals.

- **Compile:** the helper calls gcc directly:
  `riscv32-unknown-elf-gcc -march=rv32i -mabi=ilp32 -O2 -nostdlib -nostartfiles
  -T <generated .ld> crt0.S <sources> -lgcc`, with no `-fpack-struct`. It looks for the
  toolchain on `PATH`, then in `/opt/riscv/bin`, unless a parameter names its location.
  It builds in a fresh temporary directory outside the source tree.
- **Generated linker script and `crt0.S`:** both come from the address map constants.
  - The linker script puts `.text` in IMEM and `.rodata`, `.data`, `.bss` and the stack in
    DMEM. It exports `__stack_top`, `__bss_start` and `__bss_end`. From M2 it also places
    the `p` environment's `.tohost` section at `TOHOST`, as `NOLOAD`, so the ELF has no
    segment in the MMIO window.
  - `crt0.S` sets `sp`, zeroes `.bss`, calls `main`, and writes the result to `TOHOST`.
- **Generated Makefile:** with `project_dir=`, the helper also writes a `Makefile`, the
  linker script and `crt0.S` (and from M3 the C header) into that directory. The
  Makefile runs the same gcc command, so the firmware can be rebuilt, disassembled and
  debugged by hand. The build itself never runs `make`. Every import writes these
  files, so each is replaced through a temporary file and a rename, and only when its
  content changed.
- **Load:** the [ELF loader](#where-the-code-goes) reads the loadable segments with
  Python's `struct` module (no objcopy or `pyelftools` step). It splits them by address
  into the IMEM and DMEM word lists. A segment outside both windows, or one that does not
  fit, is an error that names the segment.
- **Choosing the firmware per run:** `param("FIRMWARE", ...)` names an ELF to load
  instead of building the default sources, so one design runs any program:
  `pypelinec top.py --sim --comb --run 200000 -D FIRMWARE=add.elf`. A project with its own
  build passes its ELF this way. Running an existing Makefile from the helper is not
  supported.
- **Hardware identity:** the contents are part of each RAM's entity name. To the build
  cache, new firmware is a new design. The helper declares what it reads with
  `depends_on`: the C and assembly sources, the headers gcc lists in its `-MD`
  dependency file, and an ELF named by `-D FIRMWARE`. So a repeat build and a testbench
  on built hardware notice edited firmware without `--rebuild`
  ([Code that runs during design import](pypeline_guide.md#code-that-runs-during-design-import)).

### ISA tests

- **Sources:** the `rv32ui` tests from the riscv-tests copy, built against a replacement
  environment. The standard `p` environment needs CSRs, `ecall` and `mret`, which arrive
  in M2. The replacement is a `riscv_test.h` that defines:
  - `RVTEST_CODE_BEGIN` and `RVTEST_CODE_END` without trap setup;
  - `RVTEST_PASS` and `RVTEST_FAIL` as stores to `TOHOST`;
  - the data-section macros.

  Other small cores take this approach; picorv32's `tests/riscv_test.h` is one example.
  The replacement stays after M2, for cores built without traps.
- **Excluded tests:**
  - `fence_i`, which writes instructions through data stores. A Harvard IMEM cannot take
    those writes.
  - `ma_data`, where present, which tests misaligned accesses.
- **Native run:** a registered test builds each ISA test with the firmware helper and
  runs it in native simulation with `-D FIRMWARE=`, in parallel, reporting pass or fail
  per test. A cycle cap catches a hung test.
- **GHDL run:** the same tests run in cocotb + GHDL. If the full GHDL set is too slow for
  the default run, a named subset is registered, and the full set is documented as an
  opt-in command. M1 records both run times.

### M1 exit criteria

- **ISA tests:** every `rv32ui` test except the exclusions passes in native simulation,
  and in cocotb + GHDL (the full set or the registered subset).
- **C demo:** a demo ported from the pico-ice `main.c`, without its UART, builds during
  import with no manual step. It runs a counter and some arithmetic and returns a
  checksum. It passes in native simulation and in GHDL, and `native_vs_vhdl_sim`
  compares its trace cycle by cycle.
- **Firmware reproducibility:** compiling the same inputs on a second import yields the
  same IMEM and DMEM words.
- **Edited firmware:** after a build, editing `main.c` or a header it includes makes the
  next build of the same top build again, naming the file.
- **Reset:** a reset pulsed mid-run, from a `@sim_input`-driven reset pin, restarts the
  program from the reset vector.
- **Synthesis and docs:** a synthesis test of the core top passes with `device_models`,
  the default tool for tests. The guide sections, the example README and the README
  feature table describe the core and firmware workflow.

Risks: no CPU-sized design has been elaborated yet, and native simulation speed is
unmeasured.

## M2: Machine-mode traps and CSRs

M2 runs the ISA tests with riscv-tests' own `p` environment, unmodified. The trap logic
goes into the core as one unit, so M5 can make it the first plugin.

**Before it starts:** nothing known.

What the `p` environment needs, to be confirmed against the copied
`env/p/riscv_test.h` by M0's spike:

- **CSR instructions:** `csrrw`, `csrrs`, `csrrc` and their immediate forms.
- **CSRs:** `mstatus`, `mtvec` (direct mode), `mepc`, `mcause` and `mhartid` (reads 0).
  `mie` reads as zero and ignores writes: there are no interrupts, and the environment
  writes it before it points `mtvec` past the access, so a trap there would loop.
- **Traps:** ECALL (cause 11) and EBREAK (cause 3) save the PC in `mepc`, set `mcause`
  and jump to `mtvec`. An unknown encoding or CSR traps as an illegal instruction
  (cause 2), which the environment's `satp` and PMP probes rely on: they point `mtvec`
  at the next instruction first. `unknown_op` stays as a debug output.
- **MRET:** jumps to `mepc`. The environment enters the test through it.
- **`tohost`:** the trap handler writes the test number to the `.tohost` section, which
  the generated linker script places at M1's `TOHOST`. Pass and fail codes are M1's.

Misaligned accesses trap too (causes 4 and 6) instead of setting `mem_out_of_range`.
Interrupts, timers and counters stay [deferred](#deferred).

M2 is done when:

- `rv32ui` passes with the unmodified `p` environment in native simulation and GHDL, and
  still passes with M1's replacement environment;
- the `rv32mi` tests that need only the CSRs above pass, and the plan lists the others
  with the reason each is excluded;
- a C demo installs a trap handler, takes an ECALL and returns from it with `mret`;
- the core's synthesis result is recorded against M1's, since the CSR read mux and the
  trap path can lengthen the critical path;
- the guide section describes the CSRs and trap causes the core implements.

## M3: Memory-mapped control and status registers

**Before it starts:** nothing known.

### Memory map

A builder collects devices and places them in the MMIO window. It checks alignment and
overlaps, then freezes into address constants plus one hardware function: the core
factory's MMIO argument.

```python
mm = MemoryMap(base=MMIO_BASE)
mm.add("sim", sim_ctrl_device)              # M1's TOHOST keeps its address
mm.add("leds", ctrl_t=leds_ctrl_t)          # the CPU writes, the design reads
mm.add("board", status_t=board_status_t)    # the design drives, the CPU reads
mm.freeze()
```

- **Control struct:** a register that the CPU writes with byte enables and the design
  reads.
- **Status struct:** a value that the design drives and the CPU reads.
- **Mapping:** each struct maps whole, through `make_type_to_bytes`/`make_type_from_bytes`
  and a word index, as the legacy `STRUCT_MM_ENTRY_NEW` does. No generic code names a
  field.
- **Per-device structs:** the legacy cores use one `mm_regs_t` holding every device's
  registers. Here each device has its own structs. The map then never selects a field by
  string, and each device can bring its own hardware.

### Struct layout shared with C

Pypeline's struct-to-bytes layout is packed. The plain `ilp32` C layout equals it exactly
when all of the following hold:

- Each leaf takes 1, 2, 4 or 8 bytes in Pypeline. A `uint4_t` takes 1 byte and is a
  `uint8_t` in C; a `uint24_t` does not qualify.
- Each leaf's offset is a multiple of its size.
- Each struct's size, nested structs included, is a multiple of its largest leaf.
- A mapped struct's size is a multiple of 4.

`mm.add` checks these rules. On a violation it names the field and suggests an explicit
padding field. The header then needs no packing, so GCC accesses each field at its full
width.

### C header

A generator next to `generate()` in `src/pypeline_host.py` walks the same leaves and
writes `mmio.h`, which contains:

- typedefs that use `stdint.h` types;
- the window and device base addresses;
- `volatile` struct pointers;
- `_Static_assert`s on `sizeof` and on every `offsetof`.

The firmware helper calls the generator during import and compiles against the header. The
build also writes the header to `<out_dir>/host/`, and `project_dir=` gets a copy.

**Demo:**

- LEDs, through a control struct.
- Buttons, switches and a cycle counter, through a status struct.
- A combinational compute block between a control struct (the operands) and a status
  struct (the result). This shows the first accelerator pattern: the firmware writes
  operands, and the next instruction reads the result.

### M3 exit criteria

- **Field coverage:** firmware writes and reads every field of a test set of structs with
  byte, halfword and word accesses. The set covers 8-, 16- and 32-bit fields, an array and
  a nested struct. Native simulation checks the hardware values against Python's.
- **Header unit test:** the header's offsets match Pypeline's leaf offsets, and `mm.add`
  rejects a misaligned struct with an error that names the field.
- **Blinky:** the blinky firmware drives the LED register in simulation.
- **Docs:** a guide section, and [One walk, three consumers](pypeline_DESIGN.md#one-walk-three-consumers)
  updated for the fourth consumer of the leaf walk.

## M4: Console and UART

**Before it starts:** fix [#382](https://github.com/JulianKemmerer/PipelineC/issues/382).
The console device calls two `make_stream_fifo` FIFOs, TX and RX, from one `@MAIN`, which
is the shape in which native simulation gives both FIFOs one state. Giving each FIFO its
own `@MAIN` would avoid it, at the cost of wiring that the fix makes unnecessary.

- **UART MAC:** a port of `include/uart/uart_mac.h` (TX and RX, with the baud divisor
  derived from the clock rate) to Pypeline streams, buffered with `make_stream_fifo`.
- **Console device:** four registers:

  | Register | Access |
  |---|---|
  | `TX_DATA` | A write pushes a byte |
  | `TX_STATUS` | The space left |
  | `RX_DATA` | A read pops a byte |
  | `RX_STATUS` | Whether a byte is waiting |

  A single-cycle core drives an address every cycle. The device therefore pops RX only in
  a cycle where the core performs a load from `RX_DATA` (its read enable), never on the
  address alone.
- **Simulation console:** `sim_print` adds its own newline, so one print per character
  does not work. The device collects TX bytes into a `char_t[N]` line buffer and prints
  it with `sim_print` at each newline. Console output then appears the same way in native
  simulation and in GHDL.
- **Firmware library:** `putchar`, `puts`, `getchar`, and decimal and hex number output,
  without `printf`.
- **Stimulus:** a simulation-only `@MAIN` over `@sim_input` feeds RX bytes.

M4 is done when:

- "Hello from Pypeline CPU!" prints in native simulation and GHDL;
- an echo test passes with RX stimulus, and `native_vs_vhdl_sim` compares it cycle by
  cycle;
- a UART TX-to-RX loopback at a small baud divisor passes in simulation;
- the UART block has a synthesis test.

## M5: Table-driven decoder and ISA extensions

**Before it starts:** fix [#402](https://github.com/JulianKemmerer/PipelineC/issues/402),
including the table form in its reproducer. The decoder's rows hold control-struct
constants, so `c = ctrl` from a module-level table must elaborate. The typed-local
workaround (`k: ctrl_t = ctrl`) works, but the table should read the way the guide says
module-level constants work.

- **Decoder table:** each instruction is a Python row of name, mask, match and control
  values. A compile-time loop over the rows builds `decode()`. Traces use the same table
  to name instructions.
- **Control struct:** built with `struct(NamedTuple(...))` from the field lists of the
  enabled plugins.
- **Plugins:** a plugin is a Python object that contributes rows, control fields and an
  execute function. It can also bring state or MMIO devices. The core factory takes a
  list of plugins. RV32I itself is the first one, and M2's CSRs and traps the second.
- **First extension, M:** `mul`, `mulh*`, `div*` and `rem*`, checked with `rv32um`
  through the `p` environment. In a single-cycle core these instructions are
  combinational and set the clock rate. M5 measures that; a multi-cycle execute stays
  deferred.
- **Second candidate:** a custom-0 instruction that wraps a Pypeline function (CFU
  style).

M5 is done when:

- the table decoder matches M1's decoder on every RV32I encoding class, checked through
  `sim_call` with an exhaustive sweep of the opcode and funct fields plus random words;
- `rv32ui` and the M2 `rv32mi` set pass with the table decoder;
- `rv32um` passes with the M plugin;
- elaboration time and synthesis results are recorded against M1's decoder, and M5
  decides whether M1's decoder stays.

## M6: Hardware bring-up

**Before it starts:** fix [#404](https://github.com/JulianKemmerer/PipelineC/issues/404), a wire or port
declared inside a module-level `if` being dropped. Board tops choose pins per board, and a dropped
pin shows up only on the board. Watch Vivado's log for `TIMING LOOPS!`
([#318](https://github.com/JulianKemmerer/PipelineC/issues/318): Vivado removes logic it
treats as a timing loop, cause unknown).

- **Arty first:** the single-cycle core, with memories in LUT RAM. The A7-35T has
  400 Kbit of distributed RAM. The board top reuses `examples/pypeline/arty`'s
  `board.vhd` (an MMCM) and its Vivado Makefile.
- **pico-ice second, blink only:** the same single-cycle core with a blink firmware and
  the smallest IMEM and DMEM that hold it. IMEM is a constant ROM that synthesis reduces
  to logic, so its zero words cost nothing. DMEM and the register file (31 × 32 bits)
  become flip-flops. The top reuses `examples/pypeline/pico_ice`'s `top.sv` (an icepll
  PLL) and Makefile. If it does not fit, M6 records the utilization; the registered-read
  core it would need is deferred.
- **Clock and reset:** the CPU `@MAIN` runs on the PLL clock, under the reset made from
  `pll_locked`, with `reset_registers="all"`.
- **Pins:**
  - LEDs from M3's control registers;
  - buttons and switches into its status registers;
  - on Arty, UART TX and RX from M4, on the USB-UART pins from Digilent's master `.xdc`;
  - `halt` and the pass/fail code shown on LEDs.

M6 is done when:

- the same firmware (blinky, UART hello, MMIO compute) runs in simulation and on Arty;
- blink runs on pico-ice, or the plan records its utilization and what would make it
  fit;
- each board top has a registered synthesis test: Vivado for Arty and open tools for
  pico-ice, as `example_arty_top` and `example_pico_ice_top` do;
- the example README lists the hardware checks to run by hand.

## Deferred

- Multi-cycle and pipelined cores, multi-cycle devices with stalls, and the cores whose
  memories read on a clock edge: the legacy FSM core
  (`include/risc-v/fsm_riscv_decl.h`) and a registered-read core for iCE40.
- Interrupts, timers and counters (`mtime`, `mcycle`, Zicntr), and privilege modes
  below machine mode.
- Restoring `.data` on reset, writable IMEM (`fence.i`, a bootloader), and loading firmware
  at run time.
- AXI-Lite and the shared resource bus as windows on the native port. Per-writer port
  allocation (`INST_ARRAY`) and library-made wires, instances and FIFOs, scoped by what
  the bus needs.
- Sub-byte register fields and bitfield packing in the memory map and the header.
- Multiple clock domains, PLLs generated by the build, and the vendor IP the StreamSoC
  port needs (DDR3, Ethernet).
- Whole-SoC verification at scale: `@sim_model`s of vendor IP, and Verilator or CXXRTL
  drivers.
- Other ISAs and switchable endianness, through an adapter from their native port.
- C generated from combinational Pypeline functions, so firmware and hardware share code.
- MicroPython. It needs much more memory and ideally RV32IMC; `uctypes` layouts could
  come from the same leaf walk.
- A UART or JTAG bridge, so host Python reads and writes registers by memory-map name.
- Compile-time `getattr` on hardware structs, until a design needs it.

## Open questions

There are no outstanding design questions for M1.
