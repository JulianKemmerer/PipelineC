"""Run one of the pinned rv32ui tests on the single-cycle core."""

from pypeline import *
from cpu.sim_ctrl import sim_ctrl_device
from riscv import firmware
from riscv.core import riscv_out_t
from riscv.single_cycle import make_rv32i_single_cycle_core
from riscv.isa_tests import INCLUDES, ISA_TESTS, RISCV_TESTS_DIR

# ISA program and byte capacities, set during design import.
ISA_TEST = param("ISA_TEST", "rv32ui/simple", choices=ISA_TESTS)
IMEM_SIZE = param("IMEM_SIZE", 4096)
DMEM_SIZE = param("DMEM_SIZE", 1024)
# A stalled test fails in both simulation backends.
MAX_CYCLES = param("MAX_CYCLES", 3712)
# Build into the two RAM windows on each import.
fw = firmware.build(
    sources=(RISCV_TESTS_DIR / "isa" / (ISA_TEST + ".S"),),
    imem_size=IMEM_SIZE,
    dmem_size=DMEM_SIZE,
    includes=INCLUDES,
    bootstrap=False,
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
