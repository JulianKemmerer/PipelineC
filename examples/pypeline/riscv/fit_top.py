"""Part-neutral FPGA fit example with a small firmware image and one status pin."""

from pathlib import Path
from pypeline import *
from cpu.sim_ctrl import sim_ctrl_device
from riscv import firmware
from riscv.single_cycle import make_rv32i_single_cycle_core

# Both windows describe the physical RAMs and the firmware linker regions.
IMEM_SIZE = 64
DMEM_SIZE = 16
fw = firmware.build(
    sources=[Path(__file__).with_name("fit.S")],
    imem_size=IMEM_SIZE,
    dmem_size=DMEM_SIZE,
    bootstrap=False,
)
core = make_rv32i_single_cycle_core(
    imem_size=IMEM_SIZE,
    dmem_size=DMEM_SIZE,
    imem_init=fw.imem_init,
    dmem_init=fw.dmem_init,
    mem_map=sim_ctrl_device,
)
# Reset restarts the demonstration. The status pin stays high after success.
rst: Input[uint1_t] = make_reset()


@MAIN(mhz=1.0, reset=rst, reset_registers="all")
def passed() -> uint1_t:
    result = core()
    return result.halt & (result.return_value == 0)
