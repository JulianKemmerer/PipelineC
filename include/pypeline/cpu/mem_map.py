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

    imem_size: int = 1024
    dmem_size: int = 2048
    mmio_size: int = 0x8000_0000

    def memory_windows(self):
        """Validate the byte ranges and return RAMs in firmware image order."""
        imem = (self.imem_base, self.imem_size)
        dmem = (self.dmem_base, self.dmem_size)
        mmio = (self.mmio_base, self.mmio_size)
        previous_end = 0
        for base, size in sorted((imem, dmem, mmio)):
            if base < 0 or base % 4 or size <= 0 or size % 4 or base + size > 2**32:
                raise ValueError(
                    "regions must be whole words within the RV32 address space"
                )
            if base < previous_end:
                raise ValueError("address regions overlap")
            previous_end = base + size
        if (
            self.tohost % 4
            or not self.mmio_base <= self.tohost <= self.mmio_base + self.mmio_size - 8
        ):
            raise ValueError(
                "both words of the aligned TOHOST mailbox must fit in MMIO"
            )
        return imem, dmem
