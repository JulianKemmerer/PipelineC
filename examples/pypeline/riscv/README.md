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
| Run one ISA test | `./src/pypelinec examples/pypeline/riscv/isa_test_top.py --sim --comb --run all -D ISA_TEST=rv32ui/add --out_dir "$OUT/isa"` |
| Run an exported ELF | `./src/pypelinec examples/pypeline/riscv/top.py --sim --comb --run all -D FIRMWARE="$OUT/firmware/fw.elf" --out_dir "$OUT/elf"` |

The demo checks a counter and a checksum using a table, string and libgcc
division. Success prints `TOHOST code=1 return_value=0`. For a per-instruction
trace add `-D RISCV_TRACE=1`. For longer firmware set `-D MAX_CYCLES=...`.

To export and disassemble the same firmware, run these commands with the same
`OUT`. The Python helper writes a stand-alone project there.

```sh
PYTHONPATH=src:include/pypeline python3 -c 'import sys; from riscv import firmware; firmware.build(["examples/pypeline/riscv/main.c"], 1024, 2048, project_dir=sys.argv[1])' "$OUT/firmware"
make -C "$OUT/firmware" dump-code
```

The [library guide](../../../include/pypeline/riscv/pypeline_riscv_guide.md)
describes the port, address map, reset behavior and custom firmware.
