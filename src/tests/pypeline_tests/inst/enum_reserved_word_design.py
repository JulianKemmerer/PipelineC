"""Known issue #358: an @enum member named like a VHDL reserved word.

The member NEXT reaches c_structs_pkg unchanged. Native simulation passes
and GHDL rejects the package.
"""

from enum import IntEnum
from pypeline import *


@enum
class step_t(IntEnum):
    STAY = 0
    NEXT = 1


@MAIN
def reserved_word():
    cycle: Reg[uint8_t]
    s: step_t = step_t.NEXT
    sim_assert(s == step_t.NEXT, "NEXT")
    if cycle == 1:
        sim_finish()
    cycle += 1
