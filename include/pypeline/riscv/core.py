"""Status interface shared by RISC-V core implementations."""

from typing import NamedTuple
from pypeline import *


@struct
class riscv_out_t(NamedTuple):
    halt: uint1_t
    return_value: uint32_t
    pc: uint32_t
    unknown_op: uint1_t
    mem_out_of_range: uint1_t
