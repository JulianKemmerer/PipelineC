# pyright: reportInvalidTypeForm=none
"""Native simulation of a @MAIN that takes arguments.

A @MAIN's arguments are top-level input ports (<main>_<arg>) that nothing drives
in native simulation. pypeline_sim used to call every MAIN with no arguments, so
any such design crashed on cycle 0 with "missing N required positional
arguments". It now passes a fresh typed zero per argument on every call, like an
undriven Input[T], and drops the return value (an output port).

checked_main asserts all three argument kinds (scalar, struct, array) read as
zero every cycle, then writes the array argument; the next evaluation (pypeline_sim
runs each MAIN at least twice per clock) must still read zeros. no_args_main covers
a mixed design and ends the run.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

from typing import NamedTuple

from pypeline import MAIN, Reg, sim_assert, sim_finish, struct, uint4_t, uint8_t


@struct
class pair_t(NamedTuple):
    a: uint8_t
    b: uint8_t


@MAIN
def checked_main(x: uint8_t, p: pair_t, arr: uint8_t[4]) -> uint8_t:
    sim_assert(x == 0, "scalar MAIN argument not zero")
    sim_assert(p.a == 0, "struct MAIN argument field a not zero")
    sim_assert(p.b == 0, "struct MAIN argument field b not zero")
    for i in range(4):
        sim_assert(arr[i] == 0, "array MAIN argument element not zero")
    arr[0] = 7
    return x + arr[0]


@MAIN
def no_args_main():
    cycle: Reg[uint4_t]
    if cycle == 5:
        sim_finish()
    cycle = cycle + 1
