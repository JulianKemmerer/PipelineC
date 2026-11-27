"""Run the C demo or a prebuilt RV32I ELF on the single-cycle core."""

from pathlib import Path
from pypeline import *
from cpu.sim_ctrl import sim_ctrl_device
from riscv import firmware
from riscv.core import riscv_out_t
from riscv.single_cycle import make_rv32i_single_cycle_core

# Memory capacities in bytes, matching the pico-ice firmware example.
IMEM_SIZE = param("IMEM_SIZE", 1024)
DMEM_SIZE = param("DMEM_SIZE", 2048)
# Program selection and simulation deadline.
FIRMWARE = param("FIRMWARE", "", help="an ELF to run instead of main.c")
MAX_CYCLES = param("MAX_CYCLES", 3712)
if FIRMWARE:
    fw = firmware.load(FIRMWARE, imem_size=IMEM_SIZE, dmem_size=DMEM_SIZE)
else:
    fw = firmware.build(
        sources=(Path(__file__).with_name("main.c"),),
        imem_size=IMEM_SIZE,
        dmem_size=DMEM_SIZE,
    )
core = make_rv32i_single_cycle_core(
    imem_size=IMEM_SIZE,
    dmem_size=DMEM_SIZE,
    imem_init=fw.imem_init,
    dmem_init=fw.dmem_init,
    mem_map=sim_ctrl_device,
)
# Synchronous reset on the default clock.
rst: Input[uint1_t] = make_reset()


@MAIN(reset=rst, reset_registers="all")
def riscv() -> riscv_out_t:
    return core()


# A hardware-language checker also runs in generated VHDL simulation.
@MAIN(reset=rst, reset_registers="all")
def simulation_deadline():
    cycle: Reg[uint32_t]
    sim_assert(cycle < MAX_CYCLES, f"MAX_CYCLES reached at cycle {cycle}")
    cycle += 1
