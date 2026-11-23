# pyright: reportInvalidTypeForm=none
"""Known-issue fixture: a reversed bit slice, x[0:7].

The guide documents slices high index first (x[7:0]). x[0:7] is accepted
anyway: the generated VHDL reads x(7 downto 0), the bits in their original
order, while native simulation raises "ValueError: negative shift count". The
C front end's x(0, 7) reverses the bits; StreamSoC's FFT rev() uses it.

Registered in known_issues_tests.py (expect_fail) through
pypeline_sim_debug.py. It fails while native simulation raises, and GHDL's
sim_assert fails while the hardware does not reverse. It passes once both
reverse the bits. A fix that rejects x[0:7] with an error instead also fails
it; turn it into an error check then.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, sim_assert, sim_finish, sim_print, uint1_t, uint8_t


@MAIN
def top():
    x: Reg[uint8_t] = 0x01
    done: Reg[uint1_t]
    y: uint8_t = x[0:7]
    sim_assert(y == 0x80, "x[0:7] does not reverse the bits")
    # Print in cycle 0, finish in cycle 1 without a print: a print on the
    # sim_finish() cycle is missing from VHDL output (#361).
    if done:
        sim_finish()
    else:
        sim_print(f"x={x} y={y}", debug=True)
    done = 1
