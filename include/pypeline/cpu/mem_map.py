"""Compile-time CPU address windows for firmware and hardware."""

from dataclasses import dataclass

# First byte of data RAM.
DMEM_BASE_ADDR = 0x4000_0000
# First byte claimed by the memory map.
MEM_MAP_BASE_ADDR = 0x8000_0000


@dataclass(frozen=True)
class AddressMap:
    """Byte addresses shared by the hardware, ELF loader and firmware linker."""

    imem_base: int = 0
    dmem_base: int = DMEM_BASE_ADDR
    mmio_base: int = MEM_MAP_BASE_ADDR
    tohost: int = MEM_MAP_BASE_ADDR

    imem_size: int = 1024
    dmem_size: int = 2048
    mmio_size: int = 0x8000_0000

    def __post_init__(self):
        imem, dmem = self.memory_windows()
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
            or not self.mmio_base <= self.tohost <= self.mmio_last - 7
        ):
            raise ValueError(
                "both words of the aligned TOHOST mailbox must fit in MMIO"
            )

    def memory_windows(self):
        """Return RAM base and size pairs in firmware image order."""
        return (self.imem_base, self.imem_size), (self.dmem_base, self.dmem_size)

    # Inclusive endpoints fit on a 32-bit hardware port even at the top of memory.
    @property
    def imem_last(self):
        return self.imem_base + self.imem_size - 1

    @property
    def dmem_last(self):
        return self.dmem_base + self.dmem_size - 1

    @property
    def mmio_last(self):
        return self.mmio_base + self.mmio_size - 1
