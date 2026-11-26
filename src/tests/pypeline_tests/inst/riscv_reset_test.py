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
from cpu.sim_ctrl import sim_ctrl_device
from riscv import firmware
from riscv.core import make_rv32i_core, riscv_out_t

# Leave RAM live across a mid-program reset (the counter loop is past startup).
RESET_AT = 900
# Use the example program and its stack layout.
fw = firmware.build(
    [Path(__file__).resolve().parents[4] / "examples/pypeline/riscv/main.c"], 1024, 2048
)
core = make_rv32i_core(1024, 2048, fw.imem_init, fw.dmem_init, sim_ctrl_device)
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
            (o.pc == 0) == (cycle == RESET_AT + 1), f"restart pc={o.pc} at {cycle}"
        )
    return o
