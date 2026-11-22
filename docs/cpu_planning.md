# Pypeline HDL CPU Generator / Framework — v0.1 Planning & Spec

## 1. Vision & Scope

The goal of this work is to establish a clean, Python-native **CPU generator and SoC bring-up library** in **Pypeline HDL** (the Python frontend for PypelineC). Previously, building softcores in C-based PipelineC relied on shared C headers, preprocessor macros, and manual build glue. With Pypeline's compile-time arbitrary-Python elaboration, typed structs, `make_ram` primitives, and native Python simulation (`pypeline_sim.py`), we can unify hardware generation, memory mapping, firmware compilation, and verification into one cohesive Python workflow.

To avoid getting lost in full-featured SoC complexity on day one, **v0.1 is strictly scoped to a minimal, end-to-end working baseline** whose abstractions scale cleanly toward multi-cycle, auto-pipelined, and multi-clock-domain systems (such as porting the legacy PipelineC **StreamSoC**).

### Guiding Implementation Principle: Library First, Targeted Pre-CPU Compiler Fixes

* **Stay within existing Pypeline constructs by default:** Pypeline's existing elaboration model already supports arbitrary Python execution at compile time. Most v0.1 CPU generator features (table-driven decoding, memory map assembly, firmware orchestration, RAM initialization) should live in pure user-space Python library code.
* **Close high-leverage compiler gaps up front when justified:** Where a small compiler or tooling gap would force awkward workarounds across the entire CPU/MMIO library (for example, `@initial` feeding `make_ram(init=...)`, compile-time `getattr` on hardware structs, or C header export from `pypeline_host.py`), we will evaluate and consider closing those gaps *first* in M0 before writing the CPU framework.

### v0.1 Hard Constraints

* **Clocking:** Single clock domain.
* **Execution Model:** Single-cycle CPU.
* **Memory:** All on-chip memory (small combinational-read LUTRAMs) with **separate IMEM and DMEM** (Harvard architecture).
* **ISA Target:** **RISC-V RV32I**, **little-endian** (minimal ISA configurability in v0.1; switchable endianness and other ISAs deferred).
* **MMIO Struct Fields:** **Byte-multiple fields only** in v0.1 (no sub-byte fields; e.g., store narrow values like a 4-bit field inside a `uint8`, and pack bit flags manually into bytes/words rather than using `u1` arrays).
* **Target Platforms:**
  1. **Native Python Simulation** (`pypeline_sim.py`)
  2. **pico-ice** (Lattice iCE40, 12 MHz input clock, GHDL + Yosys + `nextpnr-ice40`)
  3. **Arty** (Xilinx Artix-7, 100 MHz input clock, Vivado or OpenXC7)

---

## 2. Existing Pypeline Capabilities & Pre-CPU Gap Triage

### Ready to Use Today

* **Memories & Register Files:** `make_ram` already supports multi-port shapes like `ports=("r", "r", "w")` (register file), `byte_write_enables=True` (DMEM byte lanes), and `init=...` (reading firmware payloads in Python, replacing legacy `bin2vhdl.py` and `*_mem_init.h` headers).
* **Core Hardware Primitives:** `Reg[T]` (blocking read-after-write semantics), `Wire[T]`, `Feedback[T]`, `Input[T]`/`Output[T]`, `PART()`, `param()`, module-level conditional `import`, and factory-generated `@MAIN`s (recently closed since the older gaps doc was written).
* **Dynamic Structs & Byte Serialization:** `struct(NamedTuple(name, fields))` (already used in `ram.py` and `interface.py`) can assemble composite register-map structs dynamically from device field lists; `make_type_to_bytes` / `make_type_from_bytes` plus variable array indexing provide byte-addressed struct views.
* **Type Walking for Export:** `host_export` and `src/pypeline_host.py` already walk Pypeline types/leaves to emit Python host modules. Pypeline's byte layout (packed, each leaf rounded up to whole bytes) matches `riscv32-unknown-elf-gcc -fpack-struct=1` for byte-multiple fields.
* **Debug Printing:** `sim_print` works in native simulation (note: `--verilator` drops `sim_print` output, reinforcing the value of a real MMIO console).

### Pre-CPU Compiler & Tooling Gaps to Verify / Close First (M0)

Because `pypeline_stream_soc_gaps.md` is partially outdated (e.g., factory-generated `@MAIN`s from Gap 3 have already landed), treat the items below as an **M0 verification checklist** against current Pypeline. Any confirmed blocker with high library-ergonomics leverage is a candidate to close *before* starting the CPU generator implementation:

| Candidate Gap | Why It Matters for CPU / MMIO Library | Current Status / Evaluation Plan |
|---|---|---|
| **`@initial` producing values for `make_ram(init=...)`** *(High-priority pre-CPU candidate)* | `@initial` is the cleanest, most natural place to run side-effecting build steps like invoking `gcc` to generate firmware images (rather than running `gcc` during bare module import). Currently `@initial` executes *after* module import, too late for `make_ram(init=...)`. | Investigate allowing `@initial` (or a deferred init hook) to compute and supply `make_ram(init=...)` payloads. Fall back to module-level Python only if compiler changes are too invasive. |
| **Compile-time `getattr(regs, "field_name")` on hardware structs** *(High-priority pre-CPU candidate)* | Generic `MemoryMap` / register-handshake helpers need to access named fields of hardware structs inside elaboration loops without falling back to `exec`-based source-text generation. Note the distinction: **compile-time string** field selection only requires lowering `getattr(hw_struct, "foo")` to `hw_struct.foo` with its static type (no tagged union needed). True **runtime** dynamic selection across heterogeneously typed fields would require a tagged union / max-width bitcast, which MMIO avoids by operating on byte arrays via `make_type_to_bytes` / `make_type_from_bytes`. | Verify if still rejected in current Pypeline. If so, evaluate closing compile-time `getattr` (and a functional field-update equivalent) before building the `MemoryMap` library. |
| **C Header Export in `pypeline_host.py`** (Gap 9) | Required from day one so C firmware structs, constants, and base addresses never drift from Pypeline hardware definitions. | Add a C output backend alongside the existing Python leaf-walker in `src/pypeline_host.py` / `host_export`. |
| **Remaining Gap 3 pieces** (factory global wires/ports/FIFOs) | Factory-generated `@MAIN`s are understood to be closed, which already unlocks reusable CPU/SoC factories. | Verify in M0 what else from Gap 3 is already supported (factory `Wire`/`Input`/`Output`/`Fifo`) vs. still needs hand-written top-level declarations. |
| **Small language bugs** (Gap 11) | Conditional `Input`/`Output`/`Wire` inside a module-level `if` previously dropped ports silently; reversed bit slices (`x[0:7]`) had a hardware/sim bug. | Verify against current Pypeline. Workarounds exist (conditional module `import` for board variants; `uint_to_array_le` + reverse + `array_to_uint_le` if bit-reversal is needed). |
| **Simulation speed at scale** (Gap 7) | Native `pypeline_sim.py` runs ~1.2M cycles in ~3 s (raw) / ~15 s (strict) on a small design; fine for v0.1 tests, slow for multi-million-cycle full-SoC runs. | Use `pypeline_sim.py` for v0.1 (`riscv-tests` and console demos); keep console/halt MMIO-based so it also works cleanly with a Verilator/CXXRTL C++ driver later. |

---

## 3. Foundational Design Pillars (v0.1)

### 3.1 Functional Single-Cycle Core & Table-Driven Decoder

* **Functional Datapath Separation:** Clearly separate explicit state (`Reg[T]` for `pc`, `make_ram` for register file and memories) from pure combinational functions (`decode`, `imm_gen`, `alu`, `branch_eval`, `load_store_align`). Keeping the datapath functional keeps the single-cycle core clean today and prepares it for Pypeline's automatic pipelining (`AUTO_PIPELINE`) when evolving to multi-cycle/pipelined cores later.
* **Compact Python-Generated Decoder:** Rather than maintaining a monolithic hand-written `if/elif` decode tree, declare instructions as a Python data structure (bitmask/match patterns and control outputs) and let plain Python elaboration emit compact Pypeline decode logic.
* **Minimal ISA Configurability (v0.1):** Focus strictly on RV32I (little-endian) first. Keep obvious, compiler-supported knobs easy to introduce later (e.g., RV32E 16-register mode for tight iCE40 area budgets, optional M/C extensions, or switchable endianness).

### 3.2 Harvard Memory Architecture, RAM Defaults & Read-Only Sections

Starting with **separate IMEM and DMEM** avoids structural hazards in a single-cycle design (allowing simultaneous instruction fetch and data load/store in one cycle).

* **IMEM (Instruction Memory):** Read-only at runtime in v0.1, initialized directly from the compiled firmware image. Holds `.text`.
* **DMEM (Data Memory):** Read/write on-chip RAM. Holds `.rodata`, `.data`, `.bss`, and the stack.
* **Critical Harvard Detail (`.rodata` & `.data`):** Because GCC places string literals (`"Hello\n"`), `const` tables, and switch jump tables in `.rodata` and reads them with data load instructions (`lw`/`lb`), **DMEM must be initialized with `.rodata` and `.data`**—not just IMEM with `.text`.
  * *v0.1 Approach:* Extract **two** initialization payloads from the compiled ELF (`imem` from `.text`; `dmem` from `.rodata` + `.data`) in Python and pass them directly to `make_ram(init=...)`. Zero `.bss` in `crt0.S` (or via RAM zero-init).
* **Hardware Inference Defaults (Artix-7 Proven Style):**
  * **Byte Enables:** Use the proven Artix-7 inference style (`make_ram(..., byte_write_enables=True)`) as the default without adding platform-specific workarounds in v0.1.
  * **Memory Initialization:** Use the proven Artix-7 VHDL initialization pattern (`make_ram(init=...)`), which is expected to carry over cleanly to iCE40 as well—no extra platform-specific init paths in v0.1.

### 3.3 Layered MMIO Architecture: ISA-Native Protocol, Address Windows & Struct Mapping

* **ISA-Native MMIO Protocol as the Base Layer:**
  * Inside the core, the ISA spec dictates register counts and operand shapes. At the core's memory boundary, the ISA dictates the **base native MMIO protocol**—essentially raw RAM control signals (address width, data width, read/write enables, byte strobes). For RV32I, this is a 32-bit little-endian address/data interface with 4-bit byte write-enables, combinational read, and registered write.
  * Standard bus fabrics (**AXI**, **AXI-Lite**, Pypeline's **shared resource bus**) are **not** built into v0.1. Instead, they will sit cleanly *on top* of this base layer via thin protocol adapters. When another ISA (`OtherISA`) is added in the future with a different native memory shape, only a thin `OtherISA`-to-AXI (or shared bus) adapter is needed to reuse the bus and peripheral ecosystem.
* **Address Windows & Bridges:**
  * Model regions of the address space as composable **address windows** (e.g., DMEM window, local MMIO register window).
  * In v0.1, all windows are local single-cycle windows. Later, attaching an AXI-Lite bridge, Pypeline's shared resource bus, or a multi-cycle peripheral simply registers a bus-backed window (introducing `valid`/`ready` or stall semantics on that region) without changing the core's local MMIO model.
* **`MemoryMap` & Register Map Builder (Inspired by `amaranth-soc` / LiteX / legacy `mm_regs_t`):**
  * Compose per-device register definitions and typed Pypeline `struct`s into a single address map (`mem_map.add("leds", LedRegs, addr=0x2000_0000)` or auto-aligned placement), enforcing alignment and checking for overlaps before `.freeze()`.
  * **Byte-Multiple Struct Policy (v0.1):** Mapped structs must use byte-multiple fields only (no sub-byte fields or `u1` arrays; pack flags into `uint8`/`uint32` manually and widen narrow values like `uint4` into `uint8`). This ensures a clean 1:1 match between Pypeline's whole-byte leaf packing and `gcc -fpack-struct=1`.
  * Leverage `struct(NamedTuple(...))`, `make_type_to_bytes`/`make_type_from_bytes`, and—ideally—fixed compile-time `getattr` (falling back to `exec` source generation only if needed) to automatically emit address decode logic and byte-accessible struct MMIO (`STRUCT_MM_ENTRY_NEW`-style behavior).
* **First Accelerator Pattern (MMIO-Mapped Combinational Compute):**
  * Skip custom RISC-V instructions for v0.1.
  * Demonstrate hardware acceleration by wiring combinational logic directly between mapped MMIO input/output struct fields (firmware writes operands to MMIO registers and immediately reads the computed result). This naturally scales to auto-pipelined multi-cycle accelerators later.

### 3.4 Automated Software Build & C Artifact Generation

Users should not need to manually maintain Makefiles or run `gcc`/`objcopy` in separate build steps. Ideally, firmware compilation runs cleanly inside an `@initial` block (pending the M0 `@initial` -> `make_ram(init=...)` gap check) or another dedicated elaboration hook so bare module imports stay clean.

From the frozen `MemoryMap` and Pypeline struct definitions, the framework automatically generates:

1. **C Hardware Header (`mmio.h`):** Extend the existing leaf-walk infrastructure in `src/pypeline_host.py` / `host_export` with a C backend emitting packed struct typedefs (matching `-fpack-struct=1` for byte-multiple fields), constants, base address `#define`s, and typed `volatile` pointer helpers for reading/writing mapped structs.
2. **Linker Script (`regions.ld`):** Populates `IMEM` and `DMEM` origins/sizes directly from the Python constants (solving legacy StreamSoC's manual size duplication in `link.ld`), placing `.text` in `IMEM` and `.rodata`/`.data`/`.bss`/stack in `DMEM`, and exporting `_stack_top`, `_bss_start`, `_bss_end`.
3. **Minimal Startup Stub (`crt0.S`):** Sets `sp`, zeroes `.bss`, jumps to `main()`, and writes to the `HALT` MMIO register on return.
4. **Compiler Driver:** Invokes `riscv32-unknown-elf-gcc -march=rv32i -mabi=ilp32 -fpack-struct=1 -nostdlib`, extracts separate IMEM and DMEM binary images, and passes them into `make_ram(init=...)`.

### 3.5 Unified Console (`putchar` over UART + Simulation Console + Halt)

Make `putchar()` / string printing a flagship v0.1 application—especially valuable for live bring-up on `pico-ice` and for simulator-independent output (since `--verilator` drops `sim_print`).

* Define a standard **Console / Control MMIO block** at a fixed address window:
  * `TX_DATA` (write): Transmits one byte.
  * `TX_STATUS` (read): Ready/busy flag (always ready in sim; reflects UART TX busy on FPGA).
  * `HALT` / `TOHOST` (write): Signals program exit + pass/fail status code.
* **In `pypeline_sim.py`:** Intercept writes to `TX_DATA` to print characters directly to Python `stdout`, and intercept writes to `HALT`/`TOHOST` to stop simulation cleanly with an exit status.
* **On FPGA (`pico-ice` / `Arty`):** Bind the exact same MMIO address to a minimal UART TX peripheral (e.g., USB-UART on `pico-ice`). Identical firmware binaries run across simulation and hardware.

### 3.6 Board Integration & Top-Level IO

* **Build on Existing Pypeline Board Support:** Audit and build upon Pypeline's existing board definitions (`board.arty.part100t`, fixed PMOD modules, and any `pico-ice` mappings) rather than starting from scratch.
* **Work Within Current Port/IP Constraints:**
  * Avoid conditional port declarations inside module-level `if` blocks (until Gap 11 is verified fixed); select board/pin modules via conditional `import`.
  * Since Pypeline does not yet have built-in PLL/clock-gen instantiation or `FUNC_BLACKBOX` support (Gap 10), v0.1 will run off the raw board clock where practical (e.g., 12 MHz on `pico-ice`) or use a minimal board-level clock wrapper / `board.vhd` port hookup on `Arty` (100 MHz).
* **Optional External Board Definitions:** Importing pinouts from `amaranth-boards` or `litex-boards` (note: LiteX is Migen-based) is appealing only if kept **zero- or minimal-dependency** (e.g., lightweight declarative Python dicts or an offline extractor script, without pulling heavy package trees into Pypeline).

### 3.7 Verification Strategy (Golden Reference)

* **No Custom Python Assembler:** Skip building a bespoke Python assembler; rely on standard RISC-V toolchains.
* **Standard `riscv-tests` Suite:** Use the official `riscv-tests` (`rv32ui-p-*`) suite as the golden reference. Build a Python test runner that loads each compiled test into IMEM/DMEM, executes it in `pypeline_sim.py`, watches the `tohost` / `HALT` MMIO address, and reports pass/fail per test. This becomes the permanent regression suite as the core evolves.

---

## 4. Pre-Implementation Audit & Gap Triage (M0)

Before locking down library syntax and APIs, perform three focused checks inside the existing repo:

1. **Legacy PipelineC C-Macro Generator Patterns:** Thoroughly examine how the old PipelineC CPU/SoC macros and generators were structured so we preserve what worked well and replace the hacky boilerplate cleanly in Python. Key files to inspect:
   * `include/risc-v/risc-v.h` (decode, RV32I execute, write-back, next-PC)
   * `fsm_riscv_decl.h`, `mem_decl.h`, `reg_file.h` (core FSM, IMEM/DMEM byte-lane wrappers, register file)
   * `include/risc-v/mem_map.h`, `cpu/mem_map.h`, `cpu/hardware/devices.c` (`MM_ENTRIES`, `mm_regs_t`, `STRUCT_MM_ENTRY_NEW`, `MM_STREAM`, `HANDSHAKE_MM_READ`/`_WRITE`)
2. **Existing Pypeline Infrastructure:**
   * Inspect `src/pypeline_host.py` and `host_export` to plan the C header export backend (Gap 9).
   * Inspect existing Pypeline board mapping modules (`board/arty*`, `pico-ice` support) to determine the cleanest top-level IO extension pattern.
3. **Verify & Close Targeted Pre-CPU Compiler Gaps:**
   * Check current status of Gap 3 (confirm factory `@MAIN`s and check factory wires/ports/FIFOs) and Gap 11 bugs.
   * Assess and—if small and clean—implement `@initial` -> `make_ram(init=...)` value passing and compile-time `getattr(hw_struct, "field_name")` before writing the `MemoryMap` and firmware runner APIs.

---

## 5. v0.1 Vertical Slice & Milestones

| Milestone | Deliverable | Exit Criteria |
|---|---|---|
| **M0: Audit, Gap Verification & C Export** | Audit legacy PipelineC CPU/MMIO macros + Pypeline board mappings; verify current gap status; evaluate/close targeted pre-CPU gaps (`@initial` -> `make_ram(init=...)`, compile-time `getattr`); add C header export backend alongside `pypeline_host.py` (Gap 9). | A test byte-multiple Pypeline struct exports a valid packed C header matching `-fpack-struct=1`; firmware-init hook and struct-field access strategy are locked in. |
| **M1: Core + Decoder + `riscv-tests`** | Functional RV32I single-cycle core (little-endian), Python table-driven decoder, Artix-7-style `make_ram` IMEM/DMEM, `tohost`/halt sim hook. | Core passes `rv32ui-p-*` base integer tests in `pypeline_sim.py` (excluding system/fence ops not in v0.1). |
| **M2: `MemoryMap` + Automated C Flow** | `MemoryMap` builder with address windows, byte-multiple typed struct-to-MMIO mapping, automated firmware build emitting `regions.ld`, `crt0.S`, `mmio.h`, and feeding `make_ram(init=...)`. | Standalone C firmware builds automatically inside the Pypeline flow (zero manual Make/gcc), reads/writes a mapped struct, and passes in `pypeline_sim.py`. |
| **M3: Console + First Accelerator** | Unified Console MMIO (`TX_DATA`, `TX_STATUS`, `HALT`) + minimal C `putchar()`/`puts()`, plus a combinational compute unit wired between mapped MMIO struct fields. | C firmware prints `"Hello from Pypeline CPU!\n"` and results from the combinational MMIO compute block directly to `stdout` in simulation. |
| **M4: Hardware Bring-Up (`pico-ice` & `Arty`)** | Board top-level integration (clock, reset, LEDs, UART TX) using Pypeline's board mapping support. | Exact same **Blinky + UART Hello + MMIO Struct Compute** demo runs identically in simulation, on `pico-ice` (via USB-UART), and on `Arty`. |

---

## 6. Explicitly Deferred (Post-v0.1 Roadmap)

Keeping these out of v0.1 protects momentum while ensuring v0.1 abstractions line up cleanly with the broader StreamSoC roadmap (`pypeline_stream_soc_gaps.md`):

* **Shared Resource Bus & AXI / AXI-Lite Adapters (Gap 2):** Layered on top of the ISA-native MMIO protocol via `MemoryMap` address windows—first on a single clock, reusing whatever factory-`@MAIN`/wiring capabilities are available.
* **Remaining Module-Level Factory Gaps (Remaining parts of Gap 3):** Factory-generated `@MAIN`s have already landed; any remaining pieces needed for zero-boilerplate multi-host buses (such as `INST_ARRAY`-style automatic per-writer port allocation or factory global wires/FIFOs, if still open) are deferred until Gap 2 concretely scopes them.
* **Sub-Byte Struct Fields & Bitfield Packing:** Automatic bitfield packing/unpacking (e.g., `u1` flag arrays or packed sub-byte registers) in `MemoryMap` and `mmio.h`.
* **Multi-Cycle & Auto-Pipelined Execution:** Transitioning from single-cycle to multi-cycle FSM / auto-pipelined CPU execution and pipelined accelerators.
* **Multi-Clock Domains, PLL Generation & Vendor IP (`FUNC_BLACKBOX`, Gap 10):** Formal clock-gen instantiation in board packages, CDC bridges, and external vendor IP (DDR3 MIG, TEMAC) needed for the full StreamSoC port.
* **Whole-SoC Verification at Scale (Gap 7):** `@sim_model` vendor IP models (AXI DDR3, Ethernet) and Verilator/CXXRTL C++ testbench integration for multi-million-cycle runs.
* **Custom RISC-V Instructions (CFU) & Other ISAs:** Wiring Pypeline functions into `custom-0` opcodes, adding M/C extensions, switchable endianness, and native-MMIO-to-AXI adapters for non-RISC-V ISAs.
* **Functions Shared by Hardware & Software (Gap 6):** Generating C from combinational Pypeline functions (e.g., FFT/power helpers) so hardware and C firmware don't drift.
* **MicroPython Support (Gap 1):** Requires substantially larger memory (~256 KiB flash / 16 KiB RAM floor, or off-chip DDR3 instruction fetch) and ideally RV32IMC; `uctypes` struct layouts can reuse the same `pypeline_host.py` leaf walker later.
* **Interactive Host Memory Access:** UART/JTAG host-to-MMIO bridge allowing PC-side Python scripts to read/write live FPGA registers by `MemoryMap` name.

---

## 7. Open Questions to Resolve in M0

1. **`@initial` -> `make_ram(init=...)` Feasibility:** Can `@initial` be extended (or paired with a deferred callable on `make_ram(init=...)`) so `gcc` runs cleanly during elaboration instead of at bare module import time?
2. **Compile-Time `getattr` vs. Source Generation (`exec`) for `MemoryMap`:** Confirm whether adding compile-time `getattr(hw_struct, "field_name")` (and a matching functional update) is straightforward enough to close in M0, or whether v0.1 `MemoryMap` helpers should follow the existing `exec` pattern from `interface_func.py` / `stream.py`.