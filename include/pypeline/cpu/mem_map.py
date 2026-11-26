"""Single-cycle CPU address windows and memory-mapped device response."""

from typing import NamedTuple
from pypeline import struct, uint1_t, uint32_t

# First byte of data RAM.
DMEM_BASE_ADDR = 0x4000_0000
# First byte claimed by the memory map.
MEM_MAP_BASE_ADDR = 0x8000_0000


@struct
class riscv_mem_map_mod_out_t(NamedTuple):
    addr_is_mapped: uint1_t
    rd_data: uint32_t
    halt: uint1_t
    return_value: uint32_t


def memory_windows(imem_size, dmem_size):
    """Check the IMEM and DMEM byte sizes; return their (base, size) windows."""
    for name, size, limit in (
        ("IMEM", imem_size, DMEM_BASE_ADDR),
        ("DMEM", dmem_size, MEM_MAP_BASE_ADDR - DMEM_BASE_ADDR),
    ):
        if size <= 0 or size % 4 or size > limit:
            raise ValueError(
                f"{name} size {size} must be a positive multiple of 4 up to {limit}"
            )
    return [(0, imem_size), (DMEM_BASE_ADDR, dmem_size)]
