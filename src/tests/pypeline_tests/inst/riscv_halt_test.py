"""ADDI x1,x0,7 followed by EBREAK. Check held outputs and the gated step trace."""

from pypeline import MAIN, Reg, sim_assert, sim_finish, sim_print, uint32_t
from pypeline import Wire, hw_func, uint1_t
from cpu.mem_map import riscv_mem_map_mod_out_t
from riscv.core import make_rv32i_core

# The checker observes whether the clock-enabled datapath still evaluates.
ticks: Wire[uint32_t]


@hw_func
def mem_map(
    addr: uint32_t, wr_data: uint32_t, wr_byte_ens: uint1_t[4], rd_byte_ens: uint1_t[4]
) -> riscv_mem_map_mod_out_t:
    sim_assert(ticks < 2, f"datapath enabled while halted at {ticks}")
    rv: riscv_mem_map_mod_out_t
    rv.addr_is_mapped = addr[31]
    rv.rd_data = wr_data
    return rv


# Only two instructions are present; a fetch past EBREAK also fails the PC check.
core = make_rv32i_core(8, 4, [0x00700093, 0x00100073], [0], mem_map)


@MAIN
def riscv():
    cycle: Reg[uint32_t]
    ticks = cycle
    o = core()
    sim_print(
        f"cycle={cycle} pc={o.pc} halt={o.halt} return_value={o.return_value}",
        debug=True,
    )
    sim_assert(o.halt == (cycle != 0), f"halt={o.halt} at {cycle}")
    sim_assert(
        o.pc == (uint32_t(4) if cycle != 0 else uint32_t(0)), f"pc={o.pc} at {cycle}"
    )
    sim_assert(~(o.unknown_op | o.mem_out_of_range) & (o.return_value == 0))
    if cycle == 9:
        sim_finish()
    cycle += 1
