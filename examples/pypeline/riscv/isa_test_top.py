"""Run one of the pinned rv32ui tests on the single-cycle core."""

from pypeline import Input, MAIN, Reg, make_reset, param, sim_assert, uint1_t, uint32_t
from cpu.sim_ctrl import sim_ctrl_device
from riscv import firmware
from riscv.core import make_rv32i_core, riscv_out_t
from riscv.isa_tests import INCLUDES, ISA_TESTS, RISCV_TESTS_DIR

# ISA program and byte capacities, set during design import.
ISA_TEST = param("ISA_TEST", "rv32ui/simple", choices=ISA_TESTS)
IMEM_SIZE = param("IMEM_SIZE", 4096)
DMEM_SIZE = param("DMEM_SIZE", 1024)
# A stalled test fails in both simulation backends.
MAX_CYCLES = param("MAX_CYCLES", 3712)
# Build into the two RAM windows on each import.
fw = firmware.build(
    (RISCV_TESTS_DIR / "isa" / (ISA_TEST + ".S"),),
    IMEM_SIZE,
    DMEM_SIZE,
    includes=INCLUDES,
    bootstrap=False,
)
core = make_rv32i_core(
    IMEM_SIZE, DMEM_SIZE, fw.imem_init, fw.dmem_init, mem_map=sim_ctrl_device
)
# Synchronous reset on the default clock.
rst: Input[uint1_t] = make_reset()


@MAIN(reset=rst, reset_registers="all")
def riscv() -> riscv_out_t:
    cycle: Reg[uint32_t]
    sim_assert(cycle < MAX_CYCLES, f"MAX_CYCLES reached at cycle {cycle}")
    cycle += 1
    return core()
