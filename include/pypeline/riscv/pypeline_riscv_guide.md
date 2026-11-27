# Single-cycle RV32I CPU

The core executes one little-endian RV32I instruction per clock. The C demo
and ISA test top build their firmware during design import. Start with the
[example commands](../../../examples/pypeline/riscv/README.md).

## Address map and reset

| Default byte address | Contents |
|---|---|
| `0` through `IMEM_SIZE - 1` | Instruction ROM, reset vector at zero |
| `0x40000000` through `0x40000000 + DMEM_SIZE - 1` | Read/write data, including constants, globals and the descending stack |
| `0x80000000` through `0xffffffff` | Memory-mapped devices |

The IMEM base is also the reset vector. Choose non-overlapping, word-aligned RAM windows below the MMIO base. Sizes are positive multiples of four bytes. A power-of-two window aligned to its size uses an upper-bit equality check. Other windows use an unsigned byte offset and size comparison. Instruction
fetches must be word-aligned. Halfword and word data accesses require natural
alignment. An invalid fetch, data access or instruction fails simulation with
the PC and instruction word.

Use `@MAIN(reset=rst, reset_registers="all")` on the enclosing top. Reset
restarts the PC at the IMEM base and clears the halt and device registers. Both memories
and the register file retain their contents. The architectural x0 always reads
zero. C startup sets the stack pointer and clears `.bss` on every boot.
Initialized writable `.data` retains the program's last writes across reset.
Reload the image to restore its initial values.

## Core and device port

```python
from cpu.mem_map import AddressMap
from cpu.sim_ctrl import make_sim_ctrl_device
from riscv import firmware
from riscv.single_cycle import make_rv32i_single_cycle_core

# Omit layout for the default addresses above.
layout = AddressMap(imem_base=0x8000, dmem_base=0x400, mmio_base=0x10000, tohost=0x10040)
fw = firmware.build(sources=[source], imem_size=1024, dmem_size=2048, layout=layout)
core = make_rv32i_single_cycle_core(
    imem_size=1024, dmem_size=2048, imem_init=fw.imem_init, dmem_init=fw.dmem_init,
    layout=layout, mem_map=make_sim_ctrl_device(tohost=layout.tohost),
)
```

Call `core()` once per clock. Separate call sites instantiate independent cores, including when they use the same factory result. Each factory can take its own layout, firmware and device. Its `riscv_out_t` gives the current instruction's
`pc`, `unknown_op`, `mem_out_of_range`, `halt` and `return_value`. ECALL and
EBREAK halt at their own PC. A halted core holds these outputs and the fetch address, suppresses register and memory writes, and presents idle byte enables to its still-clocked peripheral until reset. FENCE completes in one cycle. The Harvard core
has read-only instruction memory and provides no CSRs, traps or FENCE.I.

A custom `@hw_func` device takes `addr: uint32_t`, `wr_data: uint32_t`,
`wr_byte_ens: uint1_t[4]` and `rd_byte_ens: uint1_t[4]`, in that order.
It receives a word-aligned byte address. Byte enables and store data are
shifted to their little-endian word lanes. Both enables are clear for an idle
or invalid transfer. Return a `cpu.mem_map.riscv_mem_map_mod_out_t` with
`addr_is_mapped`, combinational `rd_data`, `halt` and `return_value`. The core
checks the address claim for active MMIO accesses, selects the requested
load lanes, and sign-extends LB and LH.

The simulation-control device accepts full-word stores to `TOHOST` at
`0x80000000`. A store of 1 finishes successfully. An odd code
`(n << 1) | 1` with nonzero `n` fails with the test number or C return
value. An even code or a partial store also fails. In hardware the device
holds the halt bit and return value. The upper word at `TOHOST + 4`
accepts stores and both words read zero.

## Building firmware

`firmware.build(sources, imem_size, dmem_size, *, includes=(), bootstrap=True,
project_dir=None, layout=AddressMap())` returns two lists of 32-bit words sized to the memory
windows. Pass paths relative to the invoking directory or anchor a source to
the design with `Path(__file__).with_name("main.c")`. Set `-D RISCV_GCC=...`
or the `RISCV_GCC` environment variable to select gcc. Otherwise the helper
searches PATH for `riscv32-unknown-elf-gcc`, then its conventional installation
under `/opt/riscv/bin`.

The command runs in a fresh temporary directory on each import.

```sh
riscv32-unknown-elf-gcc -march=rv32i -mabi=ilp32 -O2 -nostdlib -nostartfiles -T link.ld -MD -I... bootstrap.S sources... -lgcc -o fw.elf
```

The firmware build follows the [PipelineC firmware example](../../../examples/pico-ice/ice_makefile_pipelinec/risc-v/firmware/Makefile), which credits [MicroRV32’s basic C build](https://github.com/agra-uni-bremen/microrv32/tree/master/microrv32/sw/basic-c). Its [linker script](../../../examples/pico-ice/ice_makefile_pipelinec/risc-v/firmware/link.ld) also thanks dutracgi and cites the [Memfault linker-script guide](https://interrupt.memfault.com/blog/how-to-write-linker-scripts-for-firmware).

The linker emits separate ELF load segments for IMEM and DMEM so neither includes ELF headers when the base is inside a page. It puts `.text.init` first, maps read-only data and writable data to
DMEM, and defines `__stacktop`, `__bss_start`, `_end` and `tohost`. C builds
start at `_bootstrap`. Assembly with its own entry sets `bootstrap=False` and
defines `_start` at the IMEM base. The loader checks ELF class, endianness, machine,
entry and segment bounds. It places file bytes by virtual address, zero-fills
the rest of each loadable segment, and skips disjoint NOLOAD segments.

The import declares the sources and transitive project and toolchain headers
from gcc's dependency information. One compile-and-link command writes every
source's list to the same `fw.d`, so with several sources the helper also asks
the preprocessor for the earlier sources' lists. The generated startup, linker
script and temporary ELF stay private. A repeated build detects edits to declared inputs.
To use a prebuilt ELF call `firmware.load(path, imem_size, dmem_size, layout=layout)`. This
also declares the ELF as a build input. Specify `project_dir=` to export the
Makefile, linker script and optional startup for manual builds. Each file is
replaced atomically when its content changes. The example opts in only when
you export a project explicitly.

## ISA tests and traces

The trap-free environment follows the example of [PicoRV32’s test header](https://github.com/YosysHQ/picorv32/blob/main/tests/riscv_test.h). The single-cycle datapath is adapted from the [PipelineC implementation](../../../examples/risc-v/risc-v_decl.h).

The [pinned upstream copy](riscv-tests/README.md) contains 42 rv32ui
assembly wrappers and their rv64ui includes. Forty run under a trap-free
environment, with `gp` holding the current test number. `fence_i` needs writable
instruction memory and `ma_data` needs misaligned data access.

Set `-D ISA_TEST=rv32ui/add` on the ISA top. Use `--run all` so the program
runs to its exit store. The tops assert a `MAX_CYCLES` deadline (default
3,712 cycles). `-D RISCV_TRACE=1` prints the PC, instruction word, register
write and effective store address, source data and unshifted byte mask before
the device can finish the simulation. The [test reference](../../../docs/pypeline_TESTS.md#risc-v-cpu-coverage)
covers the native/GHDL comparisons.

The implementation binds hardware call results before selecting fields (#71),
indexes a byte array for variable lanes (#362), and declares each local before
the `if` or ternary that assigns it
([issues inventory](../../../docs/issues_inventory.md#39-411i411-a-local-first-assigned-inside-a-runtime-if-is-unknown-after-the-if)).
Each RAM and device has a distinct call site (#353, #382). The device and core
return values feed the core outputs so their simulation statements survive
trimming (#410). See the [issues inventory](../../../docs/issues_inventory.md).
