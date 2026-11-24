# pyright: reportInvalidTypeForm=none
"""Known-issue fixture: bit-slice assignment, x[hi:lo] = v, in native simulation.

The guide documents bit-slice assignment. Elaboration builds it and GHDL gives
the values asserted below, but native simulation stops with "TypeError:
'SimVal' object does not support item assignment", on a local or a Reg, for a
one-bit slice too. (A single-bit store, x[i] = v, stops elaboration instead:
issue #362.)

Registered in known_issues_tests.py (expect_fail) as a native run. It fails
while native simulation raises, and passes once native simulation stores the
bits and every sim_assert holds.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, sim_assert, sim_finish, sim_print, uint1_t, uint8_t, uint32_t


@MAIN
def top():
    n: Reg[uint8_t] = 0x5A
    r: Reg[uint32_t]
    done: Reg[uint1_t]
    y: uint32_t = 0xFF
    y[0:0] = 0  # one-bit slice of a local
    y[15:8] = n  # slice of a local
    sim_assert(y == 0x5AFE, "bit stores into a local")
    if done:
        sim_assert(r == 0x5A, "slice store into a Reg")
        # Finish without a print on this cycle: a print on the sim_finish()
        # cycle is missing from VHDL output (#361).
        sim_finish()
    else:
        sim_print(f"y={y}", debug=True)
    r[7:0] = n  # slice of a Reg
    done = 1
