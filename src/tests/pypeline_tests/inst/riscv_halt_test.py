"""Check independent CPU instances, retirement on halt and an always-clocked peripheral."""

from pypeline import *
from cpu.mem_map import AddressMap, riscv_mem_map_mod_out_t
from riscv.core import riscv_out_t
from riscv.single_cycle import make_rv32i_single_cycle_core

# Observe the peripheral's local clock counter even after its CPU halts.
device_ticks: Wire[uint32_t]


@hw_func
def peripheral(
    rd_byte_ens: uint1_t[4], wr_byte_ens: uint1_t[4], wr_data: uint32_t, addr: uint32_t
) -> riscv_mem_map_mod_out_t:
    ticks: Reg[uint32_t]
    device_ticks = ticks
    write = array_to_uint_le(wr_byte_ens)
    sim_assert(
        write == (uint4_t(15) if ticks == 2 else uint4_t(0)),
        f"unexpected write mask {write} at {ticks}",
    )
    rv: riscv_mem_map_mod_out_t
    rv.addr_is_mapped = addr == 0x1004
    rv.halt = write != 0
    rv.return_value = ticks
    ticks += 1
    return rv


@hw_func
def idle_device(
    addr: uint32_t, wr_data: uint32_t, wr_byte_ens: uint1_t[4], rd_byte_ens: uint1_t[4]
) -> riscv_mem_map_mod_out_t:
    rv: riscv_mem_map_mod_out_t
    return rv


# The same factory result at two call sites has independent architectural state.
core = make_rv32i_single_cycle_core(
    layout=AddressMap(imem_size=8, dmem_size=4),
    imem_init=[0x00700093, 0x00100073],
    dmem_init=[0],
    mem_map=idle_device,
)
# LUI x1,1; ADDI x1,x1,4; SW x0,0(x1). The store itself requests halt.
other = make_rv32i_single_cycle_core(
    imem_init=[0x000010B7, 0x00408093, 0x0000A023],
    dmem_init=[0],
    mem_map=peripheral,
    layout=AddressMap(
        imem_size=12,
        dmem_size=4,
        imem_base=0x104,
        dmem_base=0x24,
        mmio_base=0x1000,
        tohost=0x1004,
    ),
)


@MAIN
def check():
    cycle: Reg[uint32_t]
    first = core()
    second: riscv_out_t
    if cycle >= 2:
        second = core()
    third = other()
    sim_assert(first.halt == (cycle >= 1))
    sim_assert(first.pc == (uint32_t(4) if cycle >= 1 else uint32_t(0)))
    sim_assert(second.halt == (cycle >= 3))
    sim_assert(second.pc == (uint32_t(4) if cycle >= 3 else uint32_t(0)))
    sim_assert(third.halt == (cycle >= 2))
    sim_assert(device_ticks == cycle, f"device clock stalled at {device_ticks}")
    if cycle >= 2:
        sim_assert(third.pc == 0x10C)
        sim_assert(third.return_value == 2)
    sim_print(
        f"cycle={cycle} first={first.pc} second={second.pc} third={third.pc}",
        debug=True,
    )
    if cycle == 9:
        sim_finish()
    cycle += 1
