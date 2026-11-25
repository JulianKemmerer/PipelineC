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
otherwise, the checks ran against commit `b88f7600`, and [M0](#m0-audit)'s against
`dbfab002`. They used small designs built with `pypelinec --comb --no_synth`, plus
`--sim`, `--sim --cocotb --ghdl` or `pypeline_sim_debug.py` (the native-versus-GHDL
cycle diff) where a row says so, and the GCC toolchain described under
[What Pypeline provides today](#what-pypeline-provides-today).

## Table of Contents 

- [Goal and scope](#goal-and-scope)
- [What Pypeline provides today](#what-pypeline-provides-today)
- [Gaps and how the plan handles them](#gaps-and-how-the-plan-handles-them)
- [Architecture](#architecture)
  - [Layers](#layers)
  - [Address map](#address-map)
  - [One command and the build order](#one-command-and-the-build-order)
  - [Where the code goes](#where-the-code-goes)
- [Milestones](#milestones)
- [M0: Audit](#m0-audit)
  - [Bugs](#bugs)
  - [Legacy sources](#legacy-sources)
  - [Spikes](#spikes)
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
- **One command per run.** Every `pypelinec` run on a CPU top compiles the firmware
  during the design import, so one command builds the software and builds, simulates or
  synthesizes the hardware. For a board, that command ends at the final VHDL, and the
  user runs the vendor flow by hand. Each milestone keeps this as more of the firmware's
  inputs come from the hardware
  ([One command and the build order](#one-command-and-the-build-order)).
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
| All three memories in one `@MAIN` | An IMEM ROM, a byte-enable DMEM and the register file, each with its own contents, called from one `@MAIN` | `pypeline_sim_debug.py`: native simulation and GHDL print the same values on all 21 cycles, the `sim_finish()` cycle included |
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
| Bit store into a struct field or array element, `s.f[0] = v` | Not supported ([#362](https://github.com/JulianKemmerer/PipelineC/issues/362)): elaboration stops with an internal error, native simulation with a `TypeError`. Bit stores into a local, a parameter, a `Reg` or a wire work in both | Store into a local and write the field back. JALR clears bit 0 of a local: `result[0] = 0` |
| Reading a field of a call's result, `f(x).y` | Elaboration stops with an internal error ([#71](https://github.com/JulianKemmerer/PipelineC/issues/71)) | Bind the result to a local first: `o = ram(...)`, then `o.p0.rd_data` |
| Native-simulation state behind a stateless caller | Two stateful instances that only a stateless caller tells apart share one native-simulation state ([#382](https://github.com/JulianKemmerer/PipelineC/issues/382)). Two `make_stream_fifo` FIFOs in one `@MAIN` hit it. The three memories in one `@MAIN` (above) do not | M3's memory map calls several stateful devices of one kind from library code, and M4's console has a TX and an RX FIFO: fix #382 before [M3](#m3-memory-mapped-control-and-status-registers) |
| Memories on iCE40 | The UP5K has no distributed RAM: its block RAMs (EBR) and SPRAM read on a clock edge. It has 5,280 LUT4s and 5,280 flip-flops. Combinational-read memories therefore become flip-flops or logic: a 2 KiB DMEM alone is 16,384 bits. A constant IMEM is a ROM that synthesis reduces to logic, so a short program whose memory is mostly zeros may fit | Arty is the first board. [M6](#m6-hardware-bring-up) tries pico-ice with a blink firmware and the smallest memories that hold it. A registered-read core is [deferred](#deferred) |
| Wires, ports, instances and FIFOs made by library code | Not supported. A `@MAIN` that a library factory makes cannot reach the design's wires | The core factory takes its MMIO devices as hardware-function arguments, and the design module owns the pins |
| Native simulation speed | Measured only for M0's decode spike: `decode` and `execute` fed from three ROMs, with a 20-field `sim_print` each cycle, ran 2,290 cycles at 499 cycles per second | M1 measures cycles per second on the ISA tests, which are short programs |
| Verilator and CXXRTL simulation | The conversion they run drops `sim_print` and `sim_finish()` ([Other HDL simulators](README.md#other-hdl-simulators)), and `--verilator --run all` crashes ([#406](https://github.com/JulianKemmerer/PipelineC/issues/406)) | Not used by these milestones: tests run in native simulation and cocotb + GHDL, and the console is an MMIO device ([M4](#m4-console-and-uart)) |

## Architecture

### Layers

1. **The core** executes one instruction per clock. It talks to memory through the
   **ISA-native port**, the inputs and outputs of the legacy mem map module
   (`RISCV_MEM_MAP_MOD_INPUTS` in `include/risc-v/mem_map.h`):
   - `addr`, 32 bits;
   - `wr_data`, 32 bits, and `wr_byte_ens[4]`;
   - `rd_byte_ens[4]`;
   - `rd_data`, combinational, and `addr_is_mapped`.

   Every memory and device sees this port. The legacy module's `valid` and `ready`
   signals belong to the multi-cycle cores, which are [deferred](#deferred).
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

### One command and the build order

Each run is one command. The file names are proposals:

| Run | Command |
|---|---|
| Native simulation | `pypelinec top.py --sim --comb --run all` |
| cocotb + GHDL | `pypelinec top.py --sim --comb --cocotb --ghdl --run all` |
| Synthesis | `pypelinec top.py`, with the part from the top's board module or `--part` |
| One ISA test | `pypelinec isa_test_top.py --sim --comb --run 200000 -D ISA_TEST=rv32ui/add` |
| Board VHDL, from M6 | `pypelinec board_top.py`; the vendor flow after it is manual ([M6](#m6-hardware-bring-up)) |

Each of these compiles the firmware while it imports the design, and a run that imports
the design twice compiles it twice ([Spikes](#spikes)). Only a project with its own
firmware build runs a second command: it builds its ELF and passes it with
`-D FIRMWARE=` ([Firmware build and RAM contents](#firmware-build-and-ram-contents)).

More of the firmware's inputs come from the hardware definitions as the milestones
add them:

| From | Firmware input | Made from |
|---|---|---|
| M1 | Linker script, `bootstrap.S` | The address map constants and `TOHOST` |
| M2 | `-march=rv32i_zicsr`; the `.tohost` placement | The core's CSRs; `TOHOST` |
| M3 | `mem_map.h`, with the handshake registers' polling helpers | The frozen memory map |
| M4 | The console's registers in `mem_map.h`, and its C library | The console device |
| M5 | `-march` (`rv32im` with the M plugin), the riscv-tests suites to run, and a header of wrappers for a custom instruction | The plugin list, and the custom instruction plugin's rows |

Four rules keep each run one command:

- **One description, two consumers.** The firmware helper takes the objects the core
  factory takes: the memory sizes, the frozen memory map and, from M5, the plugin list.
  It derives the linker script, the header and `-march` from them, so the firmware and
  the hardware cannot disagree, and the top states each choice once.
- **The top's module-level code sets the order.** The hardware definitions come
  first, then the helper, then the core factory, which receives the helper's words:

  ```python
  mm = MemoryMap(base=MEM_MAP_BASE_ADDR)  # from M3; M1 passes the simulation-control device
  mm.add("leds", ctrl_regs_t=leds_ctrl_regs_t)
  mm.freeze()
  # writes mem_map.h, link.ld and bootstrap.S, runs gcc
  fw = firmware.build(sources=("main.c",), imem_size=IMEM_SIZE, dmem_size=DMEM_SIZE, mem_map=mm)
  core = make_rv32i_core(imem_init=fw.imem_init, dmem_init=fw.dmem_init, mem_map=mm)
  ```

- **Firmware inputs are fixed during import.** Parameters, Python constants, struct
  types, the frozen map and the plugin list are all known before the RAMs exist. Results
  of elaboration, pipelining or synthesis are not, and no milestone's firmware uses
  them. A device whose result takes cycles gives the firmware a status bit to poll, not
  a cycle count, so the same ELF runs whatever pipeline depth a build picks. Such
  devices are [deferred](#deferred) anyway.
- **Generated files are not declared.** The helper writes the linker script, `bootstrap.S`
  and, from M3, `mem_map.h` into its fresh temporary directory, and gcc's `-MD` file lists
  that header too. The helper leaves these files out of what it passes to `depends_on`.
  They come from Python sources the build already records, and they are gone by the
  next build's up-to-date check.

### Where the code goes

- `include/pypeline/riscv/`: everything RISC-V:
  - the core factory, the decoders and the extension plugins;
  - the firmware build: the GCC driver, and the generators of the linker script,
    `bootstrap.S` and the firmware Makefile;
  - riscv-tests, copied into the repository: `isa/rv32ui/`, `isa/rv32um/`,
    `isa/macros/scalar/test_macros.h`, the `p` environment and `encoding.h` from
    riscv-test-env, both BSD licenses, and the upstream commits they came from;
  - the replacement test environment from M1.
- `include/pypeline/cpu/`: the parts no ISA owns:
  - the ELF loader;
  - the simulation-control device;
  - from M3, `cpu/mem_map`: the memory map builder and its register and console devices.
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
| [M0](#m0-audit) | Audit of the legacy CPUs and of Pypeline; decisions; bugs filed | — | Done |
| [M1](#m1-single-cycle-rv32i-core-firmware-build-and-isa-tests) | Single-cycle RV32I core ported from the legacy core; firmware built during import; resets; `rv32ui` with a replacement test environment | Nothing to fix; workarounds for #71 and #362 | `rv32ui` passes in native simulation and GHDL; a C demo builds and runs from one command |
| [M2](#m2-machine-mode-traps-and-csrs) | Machine-mode CSRs, ECALL, EBREAK, MRET and exception traps | Nothing known | `rv32ui` passes with the unmodified riscv-tests `p` environment |
| [M3](#m3-memory-mapped-control-and-status-registers) | Memory map with struct registers for LEDs, buttons and a cycle counter; handshake registers (`MM_STREAM`) for FIFOs; C header export with the polling helpers | Fix [#382](https://github.com/JulianKemmerer/PipelineC/issues/382) | Firmware reads and writes every field of the mapped structs, checked field by field; a FIFO loopback through handshake registers passes |
| [M4](#m4-console-and-uart) | Console MMIO device and UART | Nothing more (#382 is fixed before M3) | "Hello" prints in native simulation and GHDL; an echo test passes |
| [M5](#m5-table-driven-decoder-and-isa-extensions) | Table-driven decoder; extension plugins, starting with M | Fix [#402](https://github.com/JulianKemmerer/PipelineC/issues/402), including its table form | The table decoder matches M1's decoder; `rv32um` passes |
| [M6](#m6-hardware-bring-up) | Arty bring-up, then a pico-ice blink | Fix the dropped conditional declaration, [#404](https://github.com/JulianKemmerer/PipelineC/issues/404) | The same firmware runs in simulation and on Arty; blink runs on pico-ice, or its utilization is recorded |

## M0: Audit

M0 is done. It ran on commit `dbfab002` with the toolchain described under
[What Pypeline provides today](#what-pypeline-provides-today), riscv-tests `3df703cd`
and riscv-test-env `6de71edb`; M1 copies the tests from those commits. Its spikes ran
outside the repository, and M1 rebuilds in the library what it keeps from them. The
findings that change the plan are folded into the sections they change: the
[gaps table](#gaps-and-how-the-plan-handles-them),
[Firmware build and RAM contents](#firmware-build-and-ram-contents) and
[M2](#m2-machine-mode-traps-and-csrs)'s CSR list.

### Bugs

Every open bug has an entry in the [issues inventory](issues_inventory.md) and a
`known_issues_tests.py` reproducer, unless the row says otherwise.

| Bug | Found by | Issue |
|---|---|---|
| A wire or port declared inside a module-level `if` is dropped | The [StreamSoC survey](pypeline_stream_soc_gaps.md) | [#404](https://github.com/JulianKemmerer/PipelineC/issues/404) |
| A reversed bit slice `x[0:7]` is built as `x[7:0]` | The StreamSoC survey | [#405](https://github.com/JulianKemmerer/PipelineC/issues/405) |
| `--verilator --run all` crashes | Rechecking the survey | [#406](https://github.com/JulianKemmerer/PipelineC/issues/406) |
| A struct constant from a module-level table does not elaborate | The decoder-table check | Part of [#402](https://github.com/JulianKemmerer/PipelineC/issues/402), whose reproducer has the table form |
| Bit-slice assignment raises in native simulation | The `decode()` port | [#408](https://github.com/JulianKemmerer/PipelineC/issues/408) |
| `hex()` of a negative signed value prints differently in native and VHDL simulation | The `decode()` port | [#409](https://github.com/JulianKemmerer/PipelineC/issues/409) |
| A single-bit store, `x[i] = v`, stops elaboration with an internal error | The `decode()` port | A new form of [#362](https://github.com/JulianKemmerer/PipelineC/issues/362), added to the issue; fixed with #408 |
| Reading a field of a call's result, `f(x).y`, stops elaboration | The `decode()` testbench | Already [#71](https://github.com/JulianKemmerer/PipelineC/issues/71) |

Each open one has a workaround in the gaps table; #408, #409 and the single-bit store are
fixed. #402 and #404 are fixed before M5 and M6.

### Legacy sources

| Source | Decision | Notes |
|---|---|---|
| `include/risc-v/risc-v.h`: opcode and funct constants | Port as is | Module-level integers |
| `risc-v.h`: `decode()` | Port | One `if`/`elif` tree, as in C. The per-instruction `printf`s become M1's `RISCV_TRACE` prints. Dropped: `print_rs1_read`/`print_rs2_read`, which only steer those prints, and `is_rv32i`/`is_rv32_mul`/`is_rv32_div`, autopipeline split flags that M5's plugins replace. Each chain of `int13_uint1_12(...)` immediate helpers becomes one `concat`. Added for M1: FENCE as a no-op, ECALL and EBREAK as halt |
| `risc-v.h`: `execute()` | Port | JALR's `int32_uint1_0(result, 0)` becomes the single-bit store `result[0] = 0`. The M extension's `execute_rv32_mul` and `execute_rv32_div` move to M5's M plugin |
| `risc-v.h`: `select_reg_wr_data()`, `select_next_pc()` | Port | Legacy load handling is split three ways: `decode()` sets byte enables, the DMEM wrapper shifts and truncates, and `select_reg_wr_data()` sign-extends. M1 joins them in the load and store alignment function |
| `examples/risc-v/risc-v_decl.h` | Redesigned as M1's core factory | Same datapath. The macro instance (`riscv_name` and `#define`d sizes and contents) becomes factory arguments, and `#pragma FEEDBACK` becomes `Feedback[T]`. Its `halt` and `return_value` outputs are declared but never assigned; M1's halt comes from ECALL, EBREAK and the `TOHOST` write |
| `include/risc-v/reg_file.h` | Port | The same three-port RAM and `x0` write gate. M1 adds the `x0` read mux, so `x0` does not depend on the RAM's initial contents |
| `include/risc-v/mem_decl.h`, 0-cycle IMEM and DMEM | Redesigned | The raw-VHDL RAMs become `make_ram(read_latency=0)`, with `byte_write_enables=True` for DMEM. A store outside DMEM and MMIO, or to an unmapped MMIO address, sets `mem_out_of_range` but still drives the DMEM write at `addr >> 2` (from the code). M1 enables the write only in the DMEM window. The legacy check flags a misaligned access only when it spills past its word; M1 flags any misaligned access |
| `mem_decl.h`, 1-cycle and handshake variants | Deferred | They belong to the registered-read and FSM cores |
| `include/risc-v/mem_map.h`: `STRUCT_MM_ENTRY_NEW` | Redesigned in M3 | Each device's structs are mapped whole through bytes, instead of one `mm_regs_t` for every device |
| `mem_map.h`: `MM_STREAM`, `HANDSHAKE_MM_READ`/`_WRITE` and the C `mm_handshake_*` macros | Kept in M3 | They become M3's [handshake registers](#memory-map), and the generated header keeps the C macros. `MM_STREAM` is a data field plus a `uint32_t` valid flag that both sides write. `HANDSHAKE_MM_READ` captures a stream into the registers while the flag is clear and sets it; `HANDSHAKE_MM_WRITE` drives a stream from them while the flag is set and clears it on a transfer. The firmware's `mm_handshake_read`/`_try_read`/`_write` wait on the flag, copy the data and flip the flag. The pico-ice firmware's `mem_map.h` has the same handshake as functions, `try_read_handshake` and `try_write_handshake`, used for its `uart_rx` and `uart_tx` registers. StreamSoC's mem-map module (`examples/stream_soc/cpu/hardware/devices.c`) applies the CPU's store after the handshake logic, so a store in the same cycle wins |
| `mem_map.h`: `STRUCT_MM_ENTRY_NEWEST`, `BYTES4_MM_WRITE_LOGIC`, `MM_SHARED_AXI_TO_FROM_HOST` | Dropped or deferred | `NEWEST` is a word-indexed form of the same mapping, which M3 builds its own way. The AXI windows are deferred |
| `examples/risc-v/risc-v.c`, `examples/pico-ice/ice_makefile_pipelinec/risc-v/single_cycle_risc-v_top.c` | Redesigned in M3 and M6 | Their memory-map modules write fields (`o.outputs`, `mem_map_outputs`) that the current headers do not declare, so they probably do not build. From the code; not built |
| Firmware: the `Makefile`, `link.ld`, `bootstrap.S` and `bin2vhdl.py` in `examples/pico-ice/.../firmware/` and `examples/risc-v/gcc_test/` | Dropped | The firmware helper replaces them. The legacy build uses `-O3 -mstrict-align -lm` without `-nostdlib`. `bootstrap.S` sets `sp`, calls `main` and has nothing after the call. `.bss` sits inside `.data`, so objcopy writes its zeros, and `.data` has a load address in ROM that nothing uses |
| Demo programs | The pico-ice `main.c` is ported | M1 ports it without its UART, which M4 adds. The `gcc_test` demos (FFT, frame buffer, I2S, game of life) use StreamSoC devices and are not ported |
| `examples/risc-v/cocotb/test_top.py` | Dropped | The simulation-control device's `sim_assert` and `sim_finish()` replace its checks. It reads `halt` and `main_return`, which the single-cycle core does not drive |
| `examples/stream_soc/cpu/` | Input to M3 | Its FSM core is deferred. Its single `mm_regs_t` and its `MM_ENTRIES` table of `REGS` and `SHARED_AXI` windows become M3's per-device builder, without the AXI windows. It compiles with `-fpack-struct=1`, which M3's natural alignment replaces |

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
| `int13_uint1_12(x, b)`-style bit assembly | `concat` |
| `x(hi, lo)` | `x[hi:lo]` |

### Spikes

**Firmware build.**

- **ISA tests:** all 42 `rv32ui` tests build with the replacement environment and a
  generated linker script. The largest, `ld_st`, takes 936 words of IMEM (3,744 bytes), so
  the ISA tests need 4 KiB of IMEM. Their data is at most 20 words, except `ma_data`
  (96 words), which is excluded anyway.
- **Pass and fail stores:** the store to `tohost` assembles to an `auipc` that wraps from
  IMEM at `0x0` to the MMIO window at `0x8000_0000`. The RV32 linker accepts this.
- **ELF loader:** a loader using only `struct` matched objcopy's bytes for every loaded
  section of the 42 ELFs, and left nothing else non-zero.
- **Compile time:** 17 to 33 ms per ISA test, except 132 ms for the first. A C demo (a
  counter, libgcc division, a `const` table and a string; 132 words of IMEM, 15 of DMEM)
  takes 59 ms (median of 10).
- **Compiles per run:** an elaboration-only, native or cocotb run imports the design
  once, and a pipelined build whose design reads `.latency` imports it twice. M1's core
  is combinational, so a run compiles its firmware once or twice, at that cost.

**`decode()` and `execute()`.**

- **Elaboration:** the ported `decode()` elaborates in 1 s with `--comb --no_synth` (2.9 s
  for the whole command). `decode()` with `execute()` takes 2 s (5.2 s).
- **Against objdump:** in native simulation, `decode()` gave objdump's fields for all
  10,425 instruction words of the 42 ELFs, the C demo and one `p`-environment test (45
  mnemonics, CSR instructions, ECALL and MRET among them).
- **Native against GHDL:** `pypeline_sim_debug.py` fed 2,289 distinct instruction words,
  with pseudo-random register values, through both functions. Every decoded field and
  every result agreed. The cycle diff reported mismatches only on negative immediates,
  until they were printed as unsigned values (the `hex()` bug).

**CSRs and traps.** M2 lists what riscv-test-env's `env/p/riscv_test.h` uses.

## M1: Single-cycle RV32I core, firmware build and ISA tests

M1 ports the legacy single-cycle core, adds what the ISA tests
need, and builds the firmware with no manual step.

**Before it starts:** nothing to fix. M1 works around:

- [#362](https://github.com/JulianKemmerer/PipelineC/issues/362): byte lanes through an
  array;
- [#71](https://github.com/JulianKemmerer/PipelineC/issues/71): bind a call's result to a
  local before reading its fields.

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
- **IMEM:** a ROM, `make_ram(uint32_t, IMEM_SIZE // 4, ports=("r",), read_latency=0, init=imem)`.
- **Decode:** the legacy `decode()` if/elif tree, plus FENCE as a no-op and ECALL/EBREAK
  as halt. An unknown encoding sets `unknown_op`.
- **Register file:** the two-read, one-write RAM from
  [What Pypeline provides today](#what-pypeline-provides-today), with its write port driven
  through `Feedback`. `x0` reads as zero through a mux and is never written. It
  therefore does not depend on RAM contents, which have no reset.
- **DMEM:** `make_ram(uint32_t, DMEM_SIZE // 4, ports=("rw",), read_latency=0,
  byte_write_enables=True, init=dmem)`. Loads select and sign-extend lanes from a
  `uint_to_array_le` array.
- **Reset:** the core's `@MAIN` uses `reset_registers="all"`. The PC, the status flags and
  the device registers reset; IMEM, DMEM and the register file keep their contents.
  - After a reset during a run, the startup code zeroes `.bss` again, but `.data` keeps
    the values the program last wrote. Only reloading the FPGA restores it.
  - M1 documents this behavior. Restoring `.data` needs a copy from a readable image
    ([Deferred](#deferred)).
- **Halt:** a clock enable around the core's call stops a halted core.
- **Debug outputs:** the legacy core's `pc`, `unknown_op`, `mem_out_of_range`, `halt`
  and `return_value`.
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
- calls `sim_finish()`.

These are hardware statements, so the same pass/fail check works in native simulation and
in GHDL. On a board, the write sets `halt`.

### Firmware build and RAM contents

Call an ordinary Python helper on each import, before constructing either RAM.
Repeated calls with the same inputs produce identical IMEM and DMEM words. See
[Code that runs during design import](pypeline_guide.md#code-that-runs-during-design-import).

```python
fw = firmware.build(sources=("main.c",), imem_size=IMEM_SIZE, dmem_size=DMEM_SIZE)  # compile, link, load
core = make_rv32i_core(imem_init=fw.imem_init, dmem_init=fw.dmem_init, mem_map=mm)
```

The names are proposals.

- **Compile:** the helper calls gcc directly:
  `riscv32-unknown-elf-gcc -march=rv32i -mabi=ilp32 -O2 -nostdlib -nostartfiles
  -T <generated .ld> bootstrap.S <sources> -lgcc`, with no `-fpack-struct`. It looks for the
  toolchain on `PATH`, then in `/opt/riscv/bin`, unless a parameter names its location.
  It builds in a fresh temporary directory outside the source tree. From M2 it passes
  `-march=rv32i_zicsr`. GCC 12.1 also accepts CSR instructions under `-march=rv32i`,
  but that depends on the toolchain's ISA-spec default.
- **Generated linker script and `bootstrap.S`:** both come from the address map constants.
  - The linker script puts `.text`, with `.text.init` first, in IMEM. It puts `.rodata`,
    `.data`, `.bss` and the stack in DMEM. It exports `__stacktop`, `__bss_start` and
    `_end`, and defines `tohost` at `TOHOST` for the replacement test environment.
  - From M2 it places the `p` environment's `.tohost` section at `TOHOST` instead, as
    `NOLOAD`. `NOLOAD` still gives the ELF a segment in the MMIO window, with no file
    bytes, which the loader skips.
  - `bootstrap.S` sets `sp`, zeroes `.bss`, calls `main`, and writes the result to `TOHOST`.
- **Generated Makefile:** with `project_dir=`, the helper also writes a `Makefile`, the
  linker script and `bootstrap.S` (and from M3 the C header) into that directory. The
  Makefile runs the same gcc command, so the firmware can be rebuilt, disassembled and
  debugged by hand. The build itself never runs `make`. Every import writes these
  files, so each is replaced through a temporary file and a rename, and only when its
  content changed.
- **Load:** the [ELF loader](#where-the-code-goes) reads the loadable segments with
  Python's `struct` module (no objcopy or `pyelftools` step). It places them by virtual
  address into the IMEM and DMEM word lists. A segment with no file bytes outside both
  windows, such as `.tohost`, is skipped. Any other segment outside both windows, or one
  that does not fit, is an error that names the segment.
- **Choosing the firmware per run:** `param("FIRMWARE", ...)` names an ELF to load
  instead of building the default sources, so one design runs any program:
  `pypelinec top.py --sim --comb --run 200000 -D FIRMWARE=app.elf`. A project with its own
  build passes its ELF this way. Running an existing Makefile from the helper is not
  supported.
- **Hardware identity:** the contents are part of each RAM's entity name. To the build
  cache, new firmware is a new design. The helper declares what it reads with
  `depends_on`: the C and assembly sources, the headers gcc lists in its `-MD`
  dependency file, and an ELF named by `-D FIRMWARE`. So a repeat build and a testbench
  on built hardware notice edited firmware without `--rebuild`
  ([Code that runs during design import](pypeline_guide.md#code-that-runs-during-design-import)).
  The `-MD` file also lists the toolchain's own headers (`stdint.h` and newlib's), so a
  toolchain change that changes them builds again too. Any other toolchain change needs
  `--rebuild`. The files the helper generates, the linker script and `bootstrap.S` among
  them, are not declared
  ([One command and the build order](#one-command-and-the-build-order)).

### ISA tests

- **Sources:** the `rv32ui` tests from the riscv-tests copy, built against a replacement
  environment. The standard `p` environment needs CSRs, `ecall` and `mret`, which arrive
  in M2. The replacement is a `riscv_test.h` that defines:
  - `RVTEST_CODE_BEGIN` and `RVTEST_CODE_END` without trap setup;
  - `RVTEST_PASS` and `RVTEST_FAIL` as stores to `TOHOST`;
  - the data-section macros.

  Other small cores take this approach; picorv32's `tests/riscv_test.h` is one example.
  The replacement stays after M2, for cores built without traps. M0 built all 42
  `rv32ui` tests with such a replacement.
- **Excluded tests:**
  - `fence_i`, which writes instructions through data stores. A Harvard IMEM cannot take
    those writes.
  - `ma_data`, where present, which tests misaligned accesses.
- **ISA test top:** `param("ISA_TEST", ...)` names one test, such as `rv32ui/add`. The
  top builds it with the firmware helper during import, against the test environment's
  include directories. Each test is then one command:
  `pypelinec isa_test_top.py --sim --comb --run 200000 -D ISA_TEST=rv32ui/add`. The
  `--run` count is the cycle cap that catches a hung test.
- **Native run:** a registered test runs that command for each ISA test, in parallel,
  and reports pass or fail per test.
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
  feature table describe the core and firmware workflow. The example README gives each
  run as one command.

Risks: M0 elaborated only `decode()` and `execute()` (2 s), and measured native
simulation speed only for them (499 cycles per second). The whole core is larger on both
counts.

## M2: Machine-mode traps and CSRs

M2 runs the ISA tests with riscv-tests' own `p` environment, unmodified. The trap logic
goes into the core as one unit, so M5 can make it the first plugin.

**Before it starts:** nothing known.

What the `p` environment needs, from riscv-test-env `6de71edb`'s `env/p/riscv_test.h`
and M0's disassembly of `rv32ui` `add` built with it:

- **Instructions:** the environment uses `csrrs` (as `csrr`), `csrrw` (`csrw`), `csrrwi`
  (`csrwi`), ECALL, MRET and FENCE. The core also implements `csrrc` and the other
  immediate forms, which the `rv32mi` tests use.
- **What must not trap,** from the order of the accesses:
  1. `mhartid` is read before `mtvec` is first written, so it reads 0 without trapping.
  2. Each probe then points `mtvec` past itself, so these may trap as illegal
     instructions: `mnstatus` (CSR `0x744`, from Smrnmi), `satp`, `pmpaddr0` and
     `pmpcfg0`, `medeleg` and `mideleg`.
  3. `mie` is written while `mtvec` still points at the write, so a trap there would
     loop. `mie` reads as zero and ignores writes: there are no interrupts.
  4. Once `mtvec` points at the trap vector, the writes to `mstatus` and `mepc`, a second
     `mhartid` read and MRET must not trap.
- **CSRs:** `mstatus`, `mtvec` (direct mode), `mepc`, `mcause`, `mhartid` and `mie`, as
  above. The environment writes 0 to `mstatus` before MRET. In a machine-only core,
  `mstatus.MPP` still reads as machine mode, so MRET stays in machine mode and the
  test's ECALLs are cause 11.
- **Traps:** ECALL (cause 11) and EBREAK (cause 3) save the PC in `mepc`, set `mcause`
  and jump to `mtvec`. An unknown encoding or CSR traps as an illegal instruction
  (cause 2). `unknown_op` stays as a debug output.
- **Trap vector:** it reads `mcause`. Causes 8, 9 and 11, ECALL from each privilege
  mode, write the result to `tohost`. Any other cause writes a fail code
  (`TESTNUM | 1337`).
- **MRET:** jumps to `mepc`. The environment enters the test through it.
- **`tohost`:** the trap handler writes the pass or fail code that the test left in
  `TESTNUM` (`gp`) to `tohost`, then 0 to `tohost + 4`, and repeats. The generated linker
  script places the `.tohost` section at M1's `TOHOST`. Pass and fail codes are M1's.

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

**Before it starts:** fix [#382](https://github.com/JulianKemmerer/PipelineC/issues/382).
Native simulation gives two stateful instances one state when only a stateless caller
tells them apart. The memory map calls several devices of one kind from library code,
which takes that shape unless the builder's code is arranged around the bug, and the
loopback demo puts a `make_stream_fifo` beside them. M4's console needed the fix
anyway, for its two FIFOs in one `@MAIN`.

### Memory map

A builder collects devices and places them in the MMIO window. It checks alignment and
overlaps, then freezes into address constants plus one hardware function: the core
factory's MMIO argument.

```python
mm = MemoryMap(base=MEM_MAP_BASE_ADDR)
mm.add("sim", sim_ctrl_device)              # M1's TOHOST keeps its address
mm.add("leds", ctrl_regs_t=leds_ctrl_regs_t)        # the CPU writes, the design reads
mm.add("board", status_regs_t=board_status_regs_t)  # the design drives, the CPU reads
mm.add("cmd", handshake_mm_write=cmd_t)            # CPU to design, into a FIFO's write side
mm.add("result", handshake_mm_read=result_t)       # design to CPU, from a FIFO's read side
mm.freeze()
```

- **Control registers** (the legacy `mm_ctrl_regs_t`): a struct that the CPU writes
  with byte enables and the design reads.
- **Status registers** (the legacy `mm_status_regs_t`): a struct that the design
  drives and the CPU reads.
- **Handshake registers** (the legacy `MM_STREAM`): the legacy valid/ready handshake,
  so a FIFO's write or read side connects to the CPU without glue logic. Each is a
  data field `<name>`, padded to whole words, then a `uint32_t` `<name>_valid`. Both
  sides write `<name>_valid`, each only in the state the other side waits for:
  - **`handshake_mm_write=`** (the legacy `HANDSHAKE_MM_WRITE`): the firmware waits for
    `<name>_valid` to clear, writes the data and sets the flag. The device drives the
    data and the flag to the design as a `make_stream_interface(T).fwd_t` and takes back
    its `fb_t`, which is the shape of `make_stream_fifo`'s `in_stream_if`. It clears
    the flag in the cycle the design accepts the data.
  - **`handshake_mm_read=`** (the legacy `HANDSHAKE_MM_READ`): the device's `ready` to
    the design is the flag's inverse. On a transfer it captures the data and sets the
    flag. The firmware waits for the flag, reads the data and clears the flag. A FIFO's
    `out_stream_if` connects directly.

  Neither side touches the data while the other side owns it, so a `T` wider than a
  word is safe across several accesses. If misused firmware stores to the flag in the
  cycle the device changes it, the store wins, as in the legacy module. The device's
  outputs to the design come straight from its registers, so a FIFO whose `ready` is
  combinational makes no loop. Each register holds one transfer, and the FIFO behind
  it does the buffering.
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
writes `mem_map.h`, which contains:

- typedefs that use `stdint.h` types;
- the window and device base addresses;
- `volatile` struct pointers;
- `_Static_assert`s on `sizeof` and on every `offsetof`;
- for the handshake registers, the legacy polling helpers with their names and
  arguments: `mm_handshake_write(hs_name, in_ptr)`, `mm_handshake_read(out_ptr,
  hs_name)` and `mm_handshake_try_read(success_ptr, out_ptr, hs_name)` from
  `include/risc-v/mem_map.h`, and `try_write_handshake()` and `try_read_handshake()`
  from the pico-ice firmware's `mem_map.h`. They wait on (or test) `<name>_valid`, move
  the data and flip the flag. The data is written before the flag is set and read before
  it is cleared, and `volatile` keeps those accesses in order.

The firmware helper takes the frozen map (`mem_map=`), calls the generator during import and
compiles against the header. The build also writes the header to `<out_dir>/host/`, and
`project_dir=` gets a copy.

**Demo:**

- LEDs, through control registers.
- Buttons, switches and a cycle counter, through status registers.
- A combinational compute block between control registers (the operands) and status
  registers (the result). This shows the first accelerator pattern: the firmware writes
  operands, and the next instruction reads the result.
- A loopback through a `make_stream_fifo`: a `handshake_mm_write` register feeds the
  FIFO's write side, and its read side feeds a `handshake_mm_read` register. The
  firmware writes values and reads them back through the polling helpers.

### M3 exit criteria

- **Field coverage:** firmware writes and reads every field of a test set of structs with
  byte, halfword and word accesses. The set covers 8-, 16- and 32-bit fields, an array and
  a nested struct. Native simulation checks the hardware values against Python's.
- **Header unit test:** the header's offsets match Pypeline's leaf offsets, and `mm.add`
  rejects a misaligned struct with an error that names the field.
- **Handshake registers:** in the loopback demo, the firmware writes as many values as
  the two registers and the FIFO's `capacity_beats` hold, checks that one more
  `try_write_handshake()` fails, then reads every value back in order and checks that
  `mm_handshake_try_read` then fails. It passes in native simulation and GHDL, and
  `native_vs_vhdl_sim` compares it cycle by cycle.
- **Blinky:** the blinky firmware drives the LED register in simulation.
- **Docs:** a guide section, and [One walk, three consumers](pypeline_DESIGN.md#one-walk-three-consumers)
  updated for the fourth consumer of the leaf walk.

## M4: Console and UART

**Before it starts:** nothing more. The console device calls two `make_stream_fifo`
FIFOs, TX and RX, from one `@MAIN`, the shape of
[#382](https://github.com/JulianKemmerer/PipelineC/issues/382), which is fixed before M3.

- **UART MAC:** a port of `include/uart/uart_mac.h` (TX and RX, with the baud divisor
  derived from the clock rate) to Pypeline streams, buffered with `make_stream_fifo`.
- **Console device:** the pico-ice firmware's two handshake registers, `uart_tx` and
  `uart_rx`, both of `uint8_t`. `uart_tx` is a `handshake_mm_write` register that
  feeds the TX FIFO's write side, and `uart_rx` is a `handshake_mm_read` register fed
  by the RX FIFO's read side. A load has no side effect: the firmware clears
  `uart_rx_valid` after taking the byte. A single-cycle core drives an address every
  cycle, so a pop-on-read register would need `rd_byte_ens`, and this design avoids
  that.
- **Simulation console:** `sim_print` adds its own newline, so one print per character
  does not work. The device collects TX bytes into a `char_t[N]` line buffer and prints
  it with `sim_print` at each newline. Console output then appears the same way in native
  simulation and in GHDL.
- **Firmware library:** `putchar`, `puts`, `getchar`, and decimal and hex number output,
  without `printf`. `putchar` and `getchar` call the pico-ice firmware's
  `try_write_uart` and `try_read_uart`, which use the polling helpers. The console device brings these C sources, and the firmware helper
  compiles the sources of every device in the map, so a top lists only its own.
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
- **`decoded_t`:** the legacy decoder's output struct, built with
  `struct(NamedTuple(...))` from the field lists of the enabled plugins.
- **Plugins:** a plugin is a Python object that contributes rows, control fields and an
  execute function. It can also bring state or MMIO devices. The core factory takes a
  list of plugins. RV32I itself is the first one, and M2's CSRs and traps the second.
  The firmware helper takes the same list. It sets `-march` from it (`rv32im` with the
  M plugin), and the ISA test registration runs only the riscv-tests suites of the
  enabled plugins.
- **First extension, M:** `mul`, `mulh*`, `div*` and `rem*`, checked with `rv32um`
  through the `p` environment. In a single-cycle core these instructions are
  combinational and set the clock rate. M5 measures that; a multi-cycle execute stays
  deferred.
- **Second candidate:** a custom-0 instruction that wraps a Pypeline function (CFU
  style). Its plugin also generates a C header from its rows: one inline function per
  instruction, emitting it with the assembler's `.insn` directive, so firmware calls it
  by name. GCC 12.1 assembles `.insn r CUSTOM_0, ...` under `-march=rv32i`.
- **Optimized decoder netlist (optional, needs a compiler feature):** a combinational
  function tagged for optimization would be synthesized on its own with Yosys and ABC.
  The optimized gate netlist would then come back as ordinary Pypeline operators
  (bitwise ops, adds, muxes). The source can then be written for clarity, as a table
  loop or a plain `if`/`elif` chain, and still get an optimized netlist. Unlike a
  `vhdl()` body, the result stays visible to the elaborator, so autopipelining can cut
  it. No such tag exists yet; it is a separate compiler task. A manual trial on a
  radix-2 divider step (sky130, `abc -fast`) measured:
  - cells and delay fell from 1,249 and 10.7 ns to 754 and 5.8 ns, against 449 and
    5.3 ns for hand-written flat VHDL;
  - the 32-step divider met its goal in 77 pipeline stages, against 81 without the
    netlist;
  - limiting ABC's gate list to AND, OR, XOR and MUX avoids gates that Pypeline must
    build from two operators (NAND, NOR, XNOR, ANDNOT, ORNOT);
  - fine-grained gate netlists must be judged with the planned sweep: `--coarse`
    under-measured the trial badly.

  If the feature exists by M5, the decoder is its first CPU user and joins the
  comparison against M1's decoder below.

M5 is done when:

- the table decoder matches M1's decoder on every RV32I encoding class, checked through
  `sim_call` with an exhaustive sweep of the opcode and funct fields plus random words;
- `rv32ui` and the M2 `rv32mi` set pass with the table decoder;
- `rv32um` passes with the M plugin;
- elaboration time and synthesis results are recorded against M1's decoder, and against
  the optimized-netlist decoder if that feature exists, and M5 decides whether M1's
  decoder stays.

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
- **Final VHDL, then by hand:** the `pypelinec` command builds the firmware and writes
  the final VHDL and its file list, `vhdl_files.txt`. The user then runs the rest by
  hand, as in the board examples: the vendor flow, with the board wrapper (`board.vhd`
  or `top.sv`, holding the PLL) and the constraints, and then programming the board.
  The example README gives these steps. Rebuild the bitstream after every firmware
  edit, because the firmware is in the IMEM and DMEM contents. The board examples'
  Makefile rules depend only on the wrapper and the constraints, so their documented
  command is `make clean all`. Generating the wrapper and running the vendor flow from
  the build are [deferred](#deferred).
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
- the example README gives the manual steps from the final VHDL to a programmed board,
  and lists the hardware checks to run by hand.

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
- Board wrapper generation, a candidate milestone after M6. The build would write the
  board top that M6 writes by hand (the PLL or MMCM instance, the reset from its lock
  signal, the pin constraints) and could run the vendor flow through to a bitstream.
  Its first step is a survey of existing board descriptions that could supply per-board
  pins and clocks, such as LiteX's
  [litex-boards](https://github.com/litex-hub/litex-boards).
- Multiple clock domains, and the vendor IP the StreamSoC port needs (DDR3, Ethernet).
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
