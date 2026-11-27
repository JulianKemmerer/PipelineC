# Run a single-cycle RV32I CPU

Run these commands from the repository root. Set `OUT` to a scratch directory
outside the source tree. Install a bare-metal RISC-V GCC toolchain with an
RV32I/ILP32 libgcc. For a source build, configure the Newlib toolchain with
`--with-arch=rv32i --with-abi=ilp32` and your installation prefix, then build
the default target. See the [upstream installation instructions](https://github.com/riscv-collab/riscv-gnu-toolchain#installation).

The helper checks `RISCV_GCC`, PATH, then the conventional
`/opt/riscv/bin/riscv32-unknown-elf-gcc`. A multilib toolchain can be selected
with `export RISCV_GCC=/path/to/riscv64-unknown-elf-gcc`. GHDL simulation also
needs cocotb. See the repository's [tool setup](../../../docs/README.md#set-up-your-tools).

| Run | Command |
|---|---|
| C demo in native simulation | `./src/pypelinec examples/pypeline/riscv/top.py --sim --comb --run all --out_dir "$OUT/native"` |
| C demo in GHDL | `./src/pypelinec examples/pypeline/riscv/top.py --sim --comb --cocotb --ghdl --run all --out_dir "$OUT/ghdl"` |
| Synthesize with sky130 timing | `./src/pypelinec examples/pypeline/riscv/top.py --comb --syn_tool device_models --out_dir "$OUT/synth"` |
| Synthesize the C demo for Arty A7-35T | `./src/pypelinec examples/pypeline/riscv/top.py --comb --part xc7a35ticsg324-1l --syn_tool vivado --out_dir "$OUT/arty-demo"` |
| Run one ISA test | `./src/pypelinec examples/pypeline/riscv/isa_test_top.py --sim --comb --run all -D ISA_TEST=rv32ui/add --out_dir "$OUT/isa"` |
| Run an exported ELF | `./src/pypelinec examples/pypeline/riscv/top.py --sim --comb --run all -D FIRMWARE="$OUT/firmware/fw.elf" --out_dir "$OUT/elf"` |

The demo checks a counter and a checksum using a table, string and libgcc
division. Success prints `TOHOST code=1 return_value=0`. For a per-instruction
trace add `-D RISCV_TRACE=1`. For longer firmware set `-D MAX_CYCLES=...`.

To export and disassemble the same firmware, run these commands with the same
`OUT`. The Python helper writes a stand-alone project there.

```sh
PYTHONPATH=src:include/pypeline python3 -c 'import sys; from riscv import firmware; firmware.build(sources=["examples/pypeline/riscv/main.c"], imem_size=1024, dmem_size=2048, project_dir=sys.argv[1])' "$OUT/firmware"
make -C "$OUT/firmware" dump-code
```

## FPGA fit example

[fit_top.py](fit_top.py) exposes reset and a single success output. Its
[short assembly program](fit.S) writes and reads a DMEM word and sends the
result to the mailbox. It uses 64 bytes of instruction ROM and 16 bytes of
data RAM. The fixed ROM lets synthesis specialize the datapath to this program.
A different firmware image or DMEM size can change the fit substantially.

| FPGA part | Command from the repository root | Result with a 1 MHz clock constraint |
|---|---|---|
| Arty A7-35T | `./src/pypelinec examples/pypeline/riscv/fit_top.py --comb --part xc7a35ticsg324-1l --syn_tool vivado --out_dir "$OUT/arty"` | Vivado 2019.2 synthesis used 528 slice LUTs and 100 registers |
| pico-ice UP5K | `./src/pypelinec examples/pypeline/riscv/fit_top.py --comb --part ICE40UP5K-SG48 --syn_tool open_tools --out_dir "$OUT/pico_ice"` | Yosys 0.48+51 and nextpnr-ice40 (seed 1) routed 919 of 5,280 logic cells, used zero EBRs, and reported 19.30 MHz |

These are FPGA part builds with unconstrained pin placement. Programming a
board also requires a board wrapper and physical pin constraints.

For comparison, the C demo above uses 1,024 bytes of IMEM and 2,048 bytes of
DMEM. Vivado 2019.2 synthesis for the same Arty part used 2,200 slice LUTs and
164 registers. The demo has no clock goal. Vivado's timing report uses the
driver's 1 GHz fallback constraint and reports negative slack at that frequency.

The [library guide](../../../include/pypeline/riscv/pypeline_riscv_guide.md)
describes the port, address map, reset behavior and custom firmware.
