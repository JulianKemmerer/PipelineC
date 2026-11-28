"""Device response and byte-address arithmetic for memory-mapped CPU ports."""

from typing import NamedTuple
from pypeline import *


@struct
class riscv_mem_map_mod_out_t(NamedTuple):
    addr_is_mapped: uint1_t
    rd_data: uint32_t
    halt: uint1_t
    device_status: uint32_t


@hw_func
def address_in_range(addr: uint32_t, base: uint32_t, last: uint32_t) -> uint1_t:
    return (addr >= base) & (addr <= last)


@hw_func
def region_offset(addr: uint32_t, base: uint32_t) -> uint32_t:
    return addr - base
