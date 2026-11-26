"""Single-cycle memory-mapped exit mailbox for firmware and ISA tests."""

from pypeline import (
    Reg,
    array_to_uint_le,
    hw_func,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint32_t,
)
from cpu.mem_map import MEM_MAP_BASE_ADDR, riscv_mem_map_mod_out_t

# Low word of the riscv-tests exit mailbox.
TOHOST = MEM_MAP_BASE_ADDR


@hw_func
def sim_ctrl_device(
    addr: uint32_t, wr_data: uint32_t, wr_byte_ens: uint1_t[4], rd_byte_ens: uint1_t[4]
) -> riscv_mem_map_mod_out_t:
    halt: Reg[uint1_t]
    return_value: Reg[uint32_t]
    rv: riscv_mem_map_mod_out_t
    rv.addr_is_mapped = (addr == TOHOST) | (addr == TOHOST + 4)
    wr = array_to_uint_le(wr_byte_ens)
    if (addr == TOHOST) & (wr != 0):
        sim_assert(wr == 15, f"partial TOHOST store, byte enables {wr}")
        return_value = wr_data >> 1
        halt = 1
        sim_print(f"TOHOST code={wr_data} return_value={return_value}", debug=True)
        sim_assert(
            wr_data == 1, f"TOHOST failure code={wr_data} return_value={return_value}"
        )
        sim_finish()
    rv.halt = halt
    rv.return_value = return_value
    return rv
