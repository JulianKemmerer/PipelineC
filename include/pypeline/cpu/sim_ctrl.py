"""Single-cycle memory-mapped exit mailbox for firmware and ISA tests."""

from pypeline import *
from cpu.mem_map import MEM_MAP_BASE_ADDR, riscv_mem_map_mod_out_t

# Low word of the riscv-tests exit mailbox.
TOHOST = MEM_MAP_BASE_ADDR


def make_sim_ctrl_device(tohost=TOHOST):
    """Build a mailbox for this core at the linker's tohost address."""

    @hw_func
    def sim_ctrl_device(
        addr: uint32_t,
        wr_data: uint32_t,
        wr_byte_ens: uint1_t[4],
        rd_byte_ens: uint1_t[4],
    ) -> riscv_mem_map_mod_out_t:
        halt: Reg[uint1_t]
        return_value: Reg[uint32_t]
        rv: riscv_mem_map_mod_out_t
        rv.addr_is_mapped = (addr == tohost) | (addr == tohost + 4)
        wr = array_to_uint_le(wr_byte_ens)
        if (addr == tohost) & (wr != 0):
            sim_assert(wr == 15, f"partial TOHOST store, byte enables {wr}")
            return_value = wr_data >> 1
            halt = 1
            sim_print(f"TOHOST code={wr_data} return_value={return_value}", debug=True)
            sim_assert(
                wr_data == 1,
                f"TOHOST failure code={wr_data} return_value={return_value}",
            )
            sim_finish()
        rv.halt = halt
        rv.return_value = return_value
        return rv

    return sim_ctrl_device


# Default mailbox for designs using the standard address layout.
sim_ctrl_device = make_sim_ctrl_device()
