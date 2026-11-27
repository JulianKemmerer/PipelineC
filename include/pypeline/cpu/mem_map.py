"""CPU address windows and memory-mapped device response."""

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


class AddressMap(NamedTuple):
    """Byte addresses shared by the hardware, ELF loader and firmware linker."""

    imem_base: int = 0
    dmem_base: int = DMEM_BASE_ADDR
    mmio_base: int = MEM_MAP_BASE_ADDR
    tohost: int = MEM_MAP_BASE_ADDR

    def memory_windows(self, imem_size, dmem_size):
        windows = [(self.imem_base, imem_size), (self.dmem_base, dmem_size)]
        for base, size in windows:
            if base < 0 or base % 4 or size <= 0 or size % 4:
                raise ValueError(
                    "RAM windows require aligned bases and positive word sizes"
                )
            if base + size > self.mmio_base:
                raise ValueError("RAM window extends into MMIO")
        if max(self.imem_base, self.dmem_base) < min(
            self.imem_base + imem_size, self.dmem_base + dmem_size
        ):
            raise ValueError("IMEM and DMEM overlap")
        if (
            self.mmio_base % 4
            or not self.mmio_base <= self.tohost <= 2**32 - 8
            or self.tohost % 4
        ):
            raise ValueError(
                "TOHOST and its upper word must fit in aligned 32-bit MMIO"
            )
        return windows


# Size-only callers use the standard memory layout.
memory_windows = AddressMap().memory_windows
