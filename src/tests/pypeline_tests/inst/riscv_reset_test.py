"""Reset the running C demo after it has started using DMEM and boot it again."""

from pathlib import Path
from pypeline import (
    MAIN,
    Reg,
    Wire,
    make_reset,
    sim_assert,
    sim_print,
    uint1_t,
    uint32_t,
)
from cpu.mem_map import AddressMap
from riscv.sim_ctrl import make_sim_ctrl_device
from riscv import firmware
from riscv.single_cycle import make_rv32i_single_cycle_core, riscv_out_t

# Leave RAM live across a mid-program reset (startup has cleared .bss).
RESET_AT = 90
# Hardware comparison uses the same reset vector as the linker.
RESET_VECTOR = 0x8000
# Relocate all windows and place the mailbox inside the MMIO region.
layout = AddressMap(
    imem_base=RESET_VECTOR,
    dmem_base=0x10000,
    mmio_base=0x400,
    mmio_size=0x80,
    tohost=0x440,
)
fw = firmware.build(
    sources=[Path(__file__).resolve().parents[4] / "examples/pypeline/riscv/main.c"],
    layout=layout,
)
core = make_rv32i_single_cycle_core(
    imem_init=fw.imem_init,
    dmem_init=fw.dmem_init,
    mem_map=make_sim_ctrl_device(tohost=layout.tohost),
    layout=layout,
)
# Generator and CPU share the default clock.
cpu_rst: Wire[uint1_t] = make_reset()
cycle: Wire[uint32_t]


@MAIN
def reset_gen():
    count: Reg[uint32_t]
    cycle = count
    cpu_rst = count == RESET_AT
    count += 1


@MAIN(reset=cpu_rst, reset_registers="all")
def riscv() -> riscv_out_t:
    sim_assert(cycle < 9000, f"reset demo timed out at {cycle}")
    o = core()
    if (cycle == RESET_AT) | (cycle == RESET_AT + 1):
        sim_print(f"reset cycle={cycle} pc={o.pc}", debug=True)
        sim_assert(
            (o.pc == RESET_VECTOR) == (cycle == RESET_AT + 1),
            f"restart pc={o.pc} at {cycle}",
        )
    return o
