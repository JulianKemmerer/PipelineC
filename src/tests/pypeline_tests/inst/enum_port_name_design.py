"""Known issue #358: an @enum member named like a port of a function using it.

VHDL names ignore case, so inside `pick` the port `read_data` hides the
member READ_DATA. Native simulation passes and GHDL rejects `pick`.
"""

from enum import IntEnum
from pypeline import *


@enum
class src_t(IntEnum):
    ALU = 0
    READ_DATA = 1


@hw_func
def pick(sel: src_t, alu: uint8_t, read_data: uint8_t) -> uint8_t:
    rv = alu
    if sel == src_t.READ_DATA:
        rv = read_data
    return rv


@MAIN
def port_name():
    cycle: Reg[uint8_t]
    # A register keeps `sel` from folding to a constant inside `pick`.
    sel: Reg[src_t] = src_t.READ_DATA
    y = pick(sel=sel, alu=1, read_data=2)
    sim_assert(y == 2, f"pick returned {y}")
    if cycle == 1:
        sim_finish()
    cycle += 1
