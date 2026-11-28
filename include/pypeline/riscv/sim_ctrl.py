"""Firmware exit mailbox shared by the C startup and the trap-free ISA tests.

A store to the linked tohost symbol publishes the program result. Hardware
latches it and halts the core so a board can expose success on a pin. Simulation
also checks the encoded result and ends the run at that same store.
"""

from pypeline import *
from cpu.mem_map import MEM_MAP_BASE_ADDR
from cpu.mem_map_port import riscv_mem_map_mod_out_t

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
        exit_code: Reg[uint32_t]
        rv: riscv_mem_map_mod_out_t
        rv.addr_is_mapped = (addr == tohost) | (addr == tohost + 4)
        wr = array_to_uint_le(wr_byte_ens)
        if (addr == tohost) & (wr != 0):
            sim_assert(wr == 15, f"partial TOHOST store, byte enables {wr}")
            if wr == 15:
                exit_code = wr_data
            return_value: uint32_t = wr_data >> 1
            rv.halt = 1
            sim_print(f"TOHOST code={wr_data} return_value={return_value}", debug=True)
            sim_assert(
                wr_data == 1,
                f"TOHOST failure code={wr_data} return_value={return_value}",
            )
            sim_finish()
        rv.device_status = exit_code
        return rv

    return sim_ctrl_device
