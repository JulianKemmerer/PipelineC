# pyright: reportInvalidTypeForm=none
"""Fixture for cocotb_verdict_test.py: a sim_assert that fails on the cycle
another @MAIN calls sim_finish(). `finisher` is registered first, so native
simulation stops at its sim_finish() call before `checker` runs, and passes.
VHDL simulation completes the cycle, so the failure must fail the run. A
finish in the clock edge's own postponed phase would let GHDL, which runs
`finisher`'s postponed process first, end the run with exit 0.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, Wire, sim_assert, sim_finish, uint8_t

# The finisher's count, for the checker
count_w: Wire[uint8_t]


@MAIN
def finisher():
    c: Reg[uint8_t]
    c = c + 1
    count_w = c
    if c == 3:
        sim_finish()


@MAIN
def checker():
    sim_assert(count_w != 3, f"count reached {count_w}")
