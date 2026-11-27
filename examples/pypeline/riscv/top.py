"""Run the checksum demo, an ISA test or a prebuilt ELF on the single-cycle core."""

from pathlib import Path
from pypeline import *
from cpu.mem_map import AddressMap
from riscv.sim_ctrl import make_sim_ctrl_device
from riscv.isa_tests import INCLUDES, ISA_TESTS, RISCV_TESTS_DIR
from riscv import firmware
from riscv.core import riscv_out_t
from riscv.single_cycle import make_rv32i_single_cycle_core

# Select one program. The ISA assembly supplies its own entry point.
ISA_TEST = param(name="ISA_TEST", default="", choices=("",) + ISA_TESTS)
FIRMWARE = param(name="FIRMWARE", default="", help="prebuilt RV32I ELF")
# Limit FPGA pins to reset, clock and the program's pass indication.
STATUS_PIN_ONLY = param(name="STATUS_PIN_ONLY", default=False)
# Simulation watchdog shared by native and generated HDL runs.
MAX_CYCLES = param(name="MAX_CYCLES", default=3712)
# Pass the same byte ranges to the firmware linker and the hardware decoder.
mmio_base = param(name="MMIO_BASE", default=0x80000000)
layout = AddressMap(
    imem_base=param(name="IMEM_BASE", default=0),
    imem_size=param(name="IMEM_SIZE", default=4096 if ISA_TEST else 1024),
    dmem_base=param(name="DMEM_BASE", default=0x40000000),
    dmem_size=param(name="DMEM_SIZE", default=1024 if ISA_TEST else 2048),
    mmio_base=mmio_base,
    mmio_size=param(name="MMIO_SIZE", default=0x100000000 - mmio_base),
    tohost=param(name="TOHOST", default=mmio_base),
)
if ISA_TEST and FIRMWARE:
    raise ValueError("choose one of ISA_TEST and FIRMWARE")
if FIRMWARE:
    fw = firmware.load(path=FIRMWARE, layout=layout)
elif ISA_TEST:
    fw = firmware.build(
        sources=(RISCV_TESTS_DIR / "isa" / (ISA_TEST + ".S"),),
        includes=INCLUDES,
        bootstrap=False,
        layout=layout,
    )
else:
    fw = firmware.build(sources=(Path(__file__).with_name(name="main.c"),), layout=layout)
core = make_rv32i_single_cycle_core(
    layout=layout,
    imem_init=fw.imem_init,
    dmem_init=fw.dmem_init,
    mem_map=make_sim_ctrl_device(tohost=layout.tohost),
)
# Synchronous reset on the default clock.
rst: Input[uint1_t] = make_reset()


if STATUS_PIN_ONLY:

    @MAIN(reset=rst, reset_registers="all")
    def passed() -> uint1_t:
        result = core()
        return result.halt & (result.return_value == 0)
else:

    @MAIN(reset=rst, reset_registers="all")
    def riscv() -> riscv_out_t:
        return core()


# A hardware-language checker also runs in generated VHDL simulation.
@MAIN(reset=rst, reset_registers="all")
def simulation_deadline():
    cycle: Reg[uint32_t]
    sim_assert(cycle < MAX_CYCLES, f"MAX_CYCLES reached at cycle {cycle}")
    cycle += 1
